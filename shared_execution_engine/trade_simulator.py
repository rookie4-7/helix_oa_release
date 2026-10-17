from __future__ import annotations

from datetime import date, timedelta
from typing import Any

try:
    from .entry_exit_logic import entry_execution_price
    from .entry_exit_logic import entry_spread_pips
    from .entry_exit_logic import entry_trigger_price_touched
    from .entry_exit_logic import find_exit_hit
    from .entry_exit_logic import forced_close_price
    from .entry_exit_logic import MIDPOINT_TP_PROTECTIVE_EXIT_REASON
    from .entry_exit_logic import pips_for_exit
    from .entry_exit_logic import r_multiple_from_pips
    from .entry_exit_logic import risk_pips_from_prices
    from .market_sessions import forced_close_utc_naive
    from .models import StrategyParams
except ImportError:
    from entry_exit_logic import entry_execution_price
    from entry_exit_logic import entry_spread_pips
    from entry_exit_logic import entry_trigger_price_touched
    from entry_exit_logic import find_exit_hit
    from entry_exit_logic import forced_close_price
    from entry_exit_logic import MIDPOINT_TP_PROTECTIVE_EXIT_REASON
    from entry_exit_logic import pips_for_exit
    from entry_exit_logic import r_multiple_from_pips
    from entry_exit_logic import risk_pips_from_prices
    from market_sessions import forced_close_utc_naive
    from models import StrategyParams


NEWS_FORCED_CLOSE_REASON = "News Forced Close"
FORCED_CLOSE_REASONS = {"18:00 London Close", NEWS_FORCED_CLOSE_REASON}


def generate_trades_with_execution_data(
    signal_rows: list[dict[str, Any]],
    execution_rows: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    params: StrategyParams,
) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    if not execution_rows:
        return trades

    signal_tf_minutes = infer_timeframe_minutes(signal_rows)
    max_exit_minutes = params.max_exit_bars_after_entry * signal_tf_minutes
    filled_london_days: set[date] = set()
    filled_directions_by_london_day: dict[date, set[str]] = {}

    start_hint = 0
    for signal in signals:
        line_events = sorted(
            signal.get("entry_line_events") or [],
            key=lambda event: event["available_from"],
        )
        if signal["status"] != "Valid" and not line_events:
            continue

        execution_start_time = (
            line_events[0]["available_from"]
            if line_events
            else signal_execution_start_time(signal, signal_tf_minutes, params)
        )
        while start_hint < len(execution_rows) and execution_rows[start_hint]["time"] < execution_start_time:
            start_hint += 1

        if line_events:
            entry_event, entry_row, executed_entry_price = find_entry_row_for_line_events(
                execution_rows=execution_rows,
                start_idx=start_hint,
                line_events=line_events,
                params=params,
            )
        else:
            entry_event = None
            entry_row, executed_entry_price = find_entry_row(execution_rows, start_hint, signal, params)

        base = trade_base(signal, entry_event, execution_start_time, params, executed_entry_price)
        if entry_row is None:
            trades.append(base | empty_execution("No fill"))
            continue

        entry_london_day = execution_rows[entry_row]["london_date"]
        if params.only_first_filled_trade_per_day and entry_london_day in filled_london_days:
            trades.append(
                base
                | empty_execution("Blocked")
                | {
                    "entry_row": entry_row + 2,
                    "entry_time": execution_rows[entry_row]["time"],
                    "spread_at_entry": entry_spread_pips(execution_rows[entry_row], params.pip_size),
                    "blocked_reason": "After first filled trade of London day",
                }
            )
            continue

        filled_directions = filled_directions_by_london_day.setdefault(entry_london_day, set())
        if params.block_same_direction_after_first_trade_per_day and base["direction"] in filled_directions:
            trades.append(
                base
                | empty_execution("Blocked")
                | {
                    "entry_row": entry_row + 2,
                    "entry_time": execution_rows[entry_row]["time"],
                    "spread_at_entry": entry_spread_pips(execution_rows[entry_row], params.pip_size),
                    "blocked_reason": "Same direction as first filled trade in that direction of London day",
                }
            )
            continue

        filled_london_days.add(entry_london_day)
        filled_directions.add(base["direction"])

        max_exit_time = execution_rows[entry_row]["time"] + timedelta(minutes=max_exit_minutes)
        exit_row, exit_reason, exit_price = find_exit(
            execution_rows=execution_rows,
            entry_row=entry_row,
            max_exit_time=max_exit_time,
            direction=base["direction"],
            stop_price=base["stop_price"],
            target_price=base["target_price"],
            entry_price=base["entry_price"],
            params=params,
        )

        if exit_row is None:
            trades.append(
                base
                | {
                    "entry_row": entry_row + 2,
                    "entry_time": execution_rows[entry_row]["time"],
                    "exit_row": None,
                    "exit_time": None,
                    "exit_price": None,
                    "exit_reason": "Open",
                    "pips": None,
                    "r_multiple": None,
                    "pnl_pct": None,
                }
            )
            continue

        trades.append(
            base
            | completed_execution(
                execution_rows=execution_rows,
                entry_row=entry_row,
                exit_row=exit_row,
                exit_reason=exit_reason,
                exit_price=exit_price,
                params=params,
                direction=base["direction"],
                entry=base["entry_price"],
                stop_price=base["stop_price"],
            )
        )

    return attach_equity_and_outcome(trades)


def apply_news_forced_close(
    trades: list[dict[str, Any]],
    execution_rows: list[dict[str, Any]],
    news_events: list[Any],
    params: StrategyParams,
) -> list[dict[str, Any]]:
    if not news_events:
        return attach_equity_and_outcome(trades)

    adjusted: list[dict[str, Any]] = []
    times = [row["time"] for row in execution_rows]
    close_before = timedelta(minutes=max(0, params.news_forced_close_minutes_before))
    events_by_london_day = news_events_by_london_day(news_events)

    for trade in trades:
        if trade.get("entry_row") is None or trade.get("outcome") in {"No fill", "Blocked"}:
            adjusted.append(trade)
            continue

        entry_idx = trade["entry_row"] - 2
        entry_time = trade["entry_time"]
        entry_london_day = execution_rows[entry_idx]["london_date"]
        event = next_trade_news_event(entry_time, entry_london_day, events_by_london_day)
        if event is None:
            adjusted.append(trade)
            continue

        close_time = event.time_utc - close_before
        if entry_time > close_time:
            close_time = entry_time
        if trade.get("exit_time") is not None and trade["exit_time"] <= close_time:
            adjusted.append(trade)
            continue

        exit_row, exit_reason, exit_price = find_exit(
            execution_rows=execution_rows,
            entry_row=entry_idx,
            max_exit_time=close_time,
            direction=trade["direction"],
            stop_price=trade["stop_price"],
            target_price=trade["target_price"],
            entry_price=trade["entry_price"],
            params=params,
        )

        news_metadata = {}
        if exit_row is None:
            exit_row = next((idx for idx in range(entry_idx, len(times)) if times[idx] >= close_time), len(times) - 1)
            exit_reason = NEWS_FORCED_CLOSE_REASON
            exit_price = forced_close_price(execution_rows[exit_row], trade["direction"])
            news_metadata = news_forced_close_metadata(event, close_time)

        adjusted.append(
            trade
            | completed_execution(
                execution_rows=execution_rows,
                entry_row=entry_idx,
                exit_row=exit_row,
                exit_reason=exit_reason,
                exit_price=exit_price,
                params=params,
                direction=trade["direction"],
                entry=trade["entry_price"],
                stop_price=trade["stop_price"],
            )
            | news_metadata
        )

    return attach_equity_and_outcome(adjusted)


def news_events_by_london_day(news_events: list[Any]) -> dict[date, list[Any]]:
    events_by_day: dict[date, list[Any]] = {}
    for event in news_events:
        london_time = getattr(event, "time_london", None)
        if london_time is None:
            continue
        events_by_day.setdefault(london_time.date(), []).append(event)

    for events in events_by_day.values():
        events.sort(key=lambda event: event.time_utc)
    return events_by_day


def next_trade_news_event(
    entry_time: Any,
    london_day: date,
    events_by_london_day: dict[date, list[Any]],
) -> Any | None:
    for event in events_by_london_day.get(london_day, []):
        if event.time_utc > entry_time:
            return event
    return None


def news_forced_close_metadata(event: Any, close_time: Any) -> dict[str, Any]:
    return {
        "news_forced_close_time": close_time,
        "news_event_time": event.time_utc,
        "news_event_id": event.event_id,
        "news_event": f"{event.currency} {event.impact} {event.title}",
    }


def trade_base(
    signal: dict[str, Any],
    entry_event: dict[str, Any] | None,
    execution_start_time: Any,
    params: StrategyParams,
    executed_entry_price: float | None = None,
) -> dict[str, Any]:
    if entry_event is None:
        entry = signal["entry"]
        stop_price = signal["stop_loss"]
        target_price = signal["take_profit"]
        actual_entry = executed_entry_price if executed_entry_price is not None else entry
        return {
            **signal,
            "execution_start_time": execution_start_time,
            "planned_entry_price": entry,
            "entry_price": actual_entry,
            "stop_price": stop_price,
            "target_price": target_price,
            "risk_pips": risk_pips_from_prices(actual_entry, stop_price, params.pip_size),
        }

    entry = entry_event["entry"]
    actual_entry = executed_entry_price if executed_entry_price is not None else entry
    stop_price = entry_event["stop_loss"]
    return {
        **signal,
        "line_version": entry_event.get("line_version"),
        "line_time": entry_event.get("line_time"),
        "line_available_from": entry_event.get("available_from"),
        "line_active_until": entry_event.get("active_until"),
        "execution_start_time": entry_event.get("available_from"),
        "direction": entry_event.get("direction") or signal.get("direction"),
        "signal_direction": entry_event.get("signal_direction") or signal.get("signal_direction"),
        "entry": entry,
        "entry_deadline": entry_event.get("active_until"),
        "planned_entry_price": entry,
        "entry_price": actual_entry,
        "stop_price": stop_price,
        "target_price": entry_event["take_profit"],
        "risk_pips": risk_pips_from_prices(actual_entry, stop_price, params.pip_size),
        "setup_type": entry_event.get("setup_type") or signal.get("setup_type"),
        "signal_text": entry_event.get("signal_text") or signal.get("signal_text"),
    }


def signal_execution_start_time(
    signal: dict[str, Any],
    signal_tf_minutes: float,
    params: StrategyParams,
) -> Any:
    if signal.get("execution_start_time") is not None:
        return signal["execution_start_time"]
    if params.execution_starts_after_signal_close:
        return signal["signal_time"] + timedelta(minutes=signal_tf_minutes)
    return signal["signal_time"]


def apply_same_day_18_close(
    trades: list[dict[str, Any]],
    execution_rows: list[dict[str, Any]],
    params: StrategyParams,
) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    times = [row["time"] for row in execution_rows]

    for trade in trades:
        if trade.get("entry_row") is None or trade.get("outcome") in {"No fill", "Blocked"}:
            adjusted.append(trade)
            continue

        entry_idx = trade["entry_row"] - 2
        close_time = forced_close_utc_naive(trade["entry_time"])
        if trade["entry_time"] > close_time:
            close_time = trade["entry_time"]
        if trade.get("exit_time") is not None and trade["exit_time"] <= close_time:
            adjusted.append(trade)
            continue

        exit_row, exit_reason, exit_price = find_exit(
            execution_rows=execution_rows,
            entry_row=entry_idx,
            max_exit_time=close_time,
            direction=trade["direction"],
            stop_price=trade["stop_price"],
            target_price=trade["target_price"],
            entry_price=trade["entry_price"],
            params=params,
        )

        if exit_row is None:
            exit_row = next((idx for idx in range(entry_idx, len(times)) if times[idx] >= close_time), len(times) - 1)
            exit_reason = "18:00 London Close"
            exit_price = forced_close_price(execution_rows[exit_row], trade["direction"])

        adjusted.append(
            trade
            | completed_execution(
                execution_rows=execution_rows,
                entry_row=entry_idx,
                exit_row=exit_row,
                exit_reason=exit_reason,
                exit_price=exit_price,
                params=params,
                direction=trade["direction"],
                entry=trade["entry_price"],
                stop_price=trade["stop_price"],
            )
        )

    return attach_equity_and_outcome(adjusted)


def find_entry_row(
    execution_rows: list[dict[str, Any]],
    start_idx: int,
    signal: dict[str, Any],
    params: StrategyParams,
) -> tuple[int | None, float | None]:
    trigger_mode = params.entry_fill_trigger_price_mode
    for idx in range(start_idx, len(execution_rows)):
        row = execution_rows[idx]
        if row["time"] > signal["entry_deadline"]:
            break
        if entry_trigger_price_touched(row, signal["direction"], signal["entry"], trigger_mode):
            return idx, entry_execution_price(
                row,
                signal["direction"],
                signal["entry"],
                trigger_mode,
            )
    return None, None


def find_entry_row_for_line_events(
    execution_rows: list[dict[str, Any]],
    start_idx: int,
    line_events: list[dict[str, Any]],
    params: StrategyParams,
) -> tuple[dict[str, Any] | None, int | None, float | None]:
    hint = start_idx
    for event in line_events:
        available_from = event["available_from"]
        active_until = event.get("active_until") or event.get("expires_at")
        if active_until is not None and active_until <= available_from:
            continue

        while hint < len(execution_rows) and execution_rows[hint]["time"] < available_from:
            hint += 1

        idx = hint
        while idx < len(execution_rows):
            row = execution_rows[idx]
            if active_until is not None and row["time"] >= active_until:
                break
            direction = event.get("direction")
            if entry_trigger_price_touched(row, direction, event["entry"], params.entry_fill_trigger_price_mode):
                return (
                    event,
                    idx,
                    entry_execution_price(row, direction, event["entry"], params.entry_fill_trigger_price_mode),
                )
            idx += 1

    return None, None, None


def find_exit(
    execution_rows: list[dict[str, Any]],
    entry_row: int,
    max_exit_time: Any,
    direction: str,
    stop_price: float,
    target_price: float,
    entry_price: float | None = None,
    params: StrategyParams | None = None,
) -> tuple[int | None, str, float | None]:
    hit = find_exit_hit(
        execution_rows=execution_rows,
        entry_row=entry_row,
        max_exit_time=max_exit_time,
        direction=direction,
        stop_price=stop_price,
        target_price=target_price,
        entry_price=entry_price,
        use_midpoint_tp_protective_exit=(
            params.use_midpoint_tp_protective_exit if params is not None else False
        ),
        midpoint_tp_protective_exit_r_multiple=(
            params.midpoint_tp_protective_exit_r_multiple if params is not None else 2.0
        ),
    )
    return hit.row_idx, hit.reason, hit.price


def empty_execution(reason: str) -> dict[str, Any]:
    return {
        "entry_row": None,
        "entry_time": None,
        "exit_row": None,
        "exit_time": None,
        "exit_price": None,
        "exit_reason": reason,
        "pips": None,
        "r_multiple": None,
        "pnl_pct": None,
    }


def completed_execution(
    execution_rows: list[dict[str, Any]],
    entry_row: int,
    exit_row: int,
    exit_reason: str,
    exit_price: float,
    params: StrategyParams,
    direction: str,
    entry: float,
    stop_price: float,
) -> dict[str, Any]:
    pips = pips_for_exit(direction, entry, exit_price, params.pip_size)
    risk_pips = risk_pips_from_prices(entry, stop_price, params.pip_size)
    r_multiple = r_multiple_from_pips(pips, risk_pips)
    return {
        "entry_row": entry_row + 2,
        "entry_time": execution_rows[entry_row]["time"],
        "exit_row": exit_row + 2,
        "exit_time": execution_rows[exit_row]["time"],
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pips": pips,
        "risk_pips": risk_pips,
        "r_multiple": r_multiple,
        "pnl_pct": r_multiple * params.risk_per_trade,
        "spread_at_entry": entry_spread_pips(execution_rows[entry_row], params.pip_size),
    }


def attach_equity_and_outcome(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    equity = 0.0
    for trade in trades:
        if trade.get("pnl_pct") is not None:
            equity += trade["pnl_pct"]
        trade["equity_pct"] = equity
        reason = trade.get("exit_reason")
        if reason in {"TP", MIDPOINT_TP_PROTECTIVE_EXIT_REASON} or (
            reason in FORCED_CLOSE_REASONS and (trade.get("r_multiple") or 0) > 0
        ):
            trade["outcome"] = "Win"
        elif reason == "SL" or (reason in FORCED_CLOSE_REASONS and (trade.get("r_multiple") or 0) < 0):
            trade["outcome"] = "Loss"
        elif reason in FORCED_CLOSE_REASONS:
            trade["outcome"] = "Breakeven"
        else:
            trade["outcome"] = reason
    return trades


def infer_timeframe_minutes(rows: list[dict[str, Any]]) -> float:
    deltas: dict[float, int] = {}
    for left, right in zip(rows, rows[1:]):
        minutes = (right["time"] - left["time"]).total_seconds() / 60
        if minutes > 0:
            deltas[minutes] = deltas.get(minutes, 0) + 1
    return max(deltas, key=deltas.get) if deltas else 15.0
