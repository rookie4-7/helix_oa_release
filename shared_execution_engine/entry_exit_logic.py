from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from .models import StrategyParams
except ImportError:
    from models import StrategyParams


@dataclass(frozen=True)
class EntryExitLevels:
    entry: float
    stop_loss: float
    take_profit: float


@dataclass(frozen=True)
class ExitHit:
    row_idx: int | None
    reason: str
    price: float | None


MIDPOINT_TP_PROTECTIVE_EXIT_REASON = "Midpoint TP Protective Exit"


def entry_price_from_range(
    high: float,
    low: float,
    side: str,
    retracement: float,
) -> float:
    range_size = high - low
    if side == "Buy":
        return high - range_size * retracement
    return low + range_size * retracement


def signal_entry_exit_levels(
    run_obj: dict[str, Any],
    side: str,
    params: StrategyParams,
) -> EntryExitLevels:
    if run_obj["entry_frozen"]:
        entry = run_obj["frozen_entry_price"]
    else:
        entry = entry_price_from_range(
            high=run_obj["high"],
            low=run_obj["low"],
            side=side,
            retracement=params.entry_retracement,
        )
    if params.use_flexible_sl_tp:
        stop_loss, take_profit = flexible_structure_stop_target_prices(
            body_high=run_obj["high"],
            body_low=run_obj["low"],
            wick_high=run_obj.get("wick_high", run_obj["high"]),
            wick_low=run_obj.get("wick_low", run_obj["low"]),
            entry=entry,
            side=side,
            pip_size=params.pip_size,
            buffer_pips=params.flexible_structure_buffer_pips,
            min_stop_loss_pips=params.flexible_min_stop_loss_pips,
            max_stop_loss_pips=params.flexible_max_stop_loss_pips,
            take_profit_r_multiple=params.flexible_take_profit_r_multiple,
        )
    else:
        stop_loss, take_profit = stop_target_prices(
            entry=entry,
            side=side,
            pip_size=params.pip_size,
            stop_loss_pips=params.fixed_stop_loss_pips,
            take_profit_pips=params.fixed_take_profit_pips,
        )
    return EntryExitLevels(entry=entry, stop_loss=stop_loss, take_profit=take_profit)


def live_entry_price(run_obj: dict[str, Any], params: StrategyParams) -> float:
    side = "Buy" if run_obj["direction"] == 1 else "Sell"
    return entry_price_from_range(
        high=run_obj["high"],
        low=run_obj["low"],
        side=side,
        retracement=params.entry_retracement,
    )


def stop_target_prices(
    entry: float,
    side: str,
    pip_size: float,
    stop_loss_pips: float,
    take_profit_pips: float,
) -> tuple[float, float]:
    if side == "Buy":
        return (
            entry - stop_loss_pips * pip_size,
            entry + take_profit_pips * pip_size,
        )
    return (
        entry + stop_loss_pips * pip_size,
        entry - take_profit_pips * pip_size,
    )


def flexible_structure_stop_target_prices(
    body_high: float,
    body_low: float,
    wick_high: float,
    wick_low: float,
    entry: float,
    side: str,
    pip_size: float,
    buffer_pips: float,
    min_stop_loss_pips: float,
    max_stop_loss_pips: float,
    take_profit_r_multiple: float,
) -> tuple[float, float]:
    if pip_size <= 0:
        raise ValueError("pip_size must be greater than zero.")
    if max_stop_loss_pips < min_stop_loss_pips:
        raise ValueError("Flexible max stop loss pips must be greater than or equal to min stop loss pips.")

    if side == "Buy":
        body_distance = entry - body_low
        wick_distance = entry - wick_low
    else:
        body_distance = body_high - entry
        wick_distance = wick_high - entry

    structure_distance = (body_distance + wick_distance) / 2
    risk_pips = structure_distance / pip_size + buffer_pips
    risk_pips = min(max(risk_pips, min_stop_loss_pips), max_stop_loss_pips)
    risk_distance = risk_pips * pip_size
    if risk_distance <= 0:
        raise ValueError("Flexible structure stop must create a positive risk distance.")

    if side == "Buy":
        stop_loss = entry - risk_distance
        return stop_loss, entry + risk_distance * take_profit_r_multiple

    stop_loss = entry + risk_distance
    return stop_loss, entry - risk_distance * take_profit_r_multiple


def risk_pips_from_prices(
    entry: float,
    stop_price: float,
    pip_size: float,
) -> float:
    return abs(entry - stop_price) / pip_size


def entry_price_touched(row: dict[str, Any], direction: str, entry: float) -> bool:
    if direction == "Buy":
        return row["ask_low"] <= entry <= row["ask_high"]
    return row["bid_low"] <= entry <= row["bid_high"]


def midpoint_entry_price_touched(row: dict[str, Any], entry: float) -> bool:
    return row["mid_low"] <= entry <= row["mid_high"]


def entry_trigger_price_touched(
    row: dict[str, Any],
    direction: str,
    entry: float,
    trigger_price_mode: str,
) -> bool:
    if normalized_entry_trigger_mode(trigger_price_mode) == "midpoint":
        return midpoint_entry_price_touched(row, entry)
    return entry_price_touched(row, direction, entry)


def entry_execution_price(
    row: dict[str, Any],
    direction: str,
    midpoint_entry: float,
    trigger_price_mode: str,
) -> float:
    if normalized_entry_trigger_mode(trigger_price_mode) != "midpoint":
        return midpoint_entry

    if direction == "Buy":
        return midpoint_entry + buy_side_half_spread(row)
    return midpoint_entry - sell_side_half_spread(row)


def entry_spread_pips(row: dict[str, Any], pip_size: float) -> float | None:
    if pip_size <= 0:
        return None
    ask = row.get("ask_close")
    bid = row.get("bid_close")
    if ask is None or bid is None:
        return None
    return (ask - bid) / pip_size


def buy_side_half_spread(row: dict[str, Any]) -> float:
    spread = row.get("ask_low", 0) - row.get("mid_low", 0)
    if spread >= 0:
        return spread
    return max(0.0, row.get("ask_close", 0) - row.get("mid_close", 0))


def sell_side_half_spread(row: dict[str, Any]) -> float:
    spread = row.get("mid_high", 0) - row.get("bid_high", 0)
    if spread >= 0:
        return spread
    return max(0.0, row.get("mid_close", 0) - row.get("bid_close", 0))


def normalized_entry_trigger_mode(trigger_price_mode: str) -> str:
    normalized = str(trigger_price_mode or "bid_ask").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"mid", "midpoint", "mid_point", "midprice", "mid_price"}:
        return "midpoint"
    if normalized in {"bid_ask", "bidask", "bid", "ask", "executable", "legacy"}:
        return "bid_ask"
    raise ValueError("entry_fill_trigger_price_mode must be 'midpoint' or 'bid_ask'.")


def entry_price_touched_by_direction(row: dict[str, Any], direction: int, entry: float) -> bool:
    if direction == 1:
        return row["ask_low"] <= entry <= row["ask_high"]
    return row["bid_low"] <= entry <= row["bid_high"]


def exit_hit_for_row(
    row: dict[str, Any],
    direction: str,
    stop_price: float,
    target_price: float,
) -> tuple[str, float] | None:
    if direction == "Buy":
        if row["bid_low"] <= stop_price:
            return "SL", stop_price
        if row["bid_high"] >= target_price:
            return "TP", target_price
        return None

    if row["ask_high"] >= stop_price:
        return "SL", stop_price
    if row["ask_low"] <= target_price:
        return "TP", target_price
    return None


def executable_stop_touched(
    row: dict[str, Any],
    direction: str,
    stop_price: float,
) -> bool:
    if direction == "Buy":
        return row["bid_low"] <= stop_price
    return row["ask_high"] >= stop_price


def executable_target_touched(
    row: dict[str, Any],
    direction: str,
    target_price: float,
) -> bool:
    if direction == "Buy":
        return row["bid_high"] >= target_price
    return row["ask_low"] <= target_price


def midpoint_target_touched(
    row: dict[str, Any],
    direction: str,
    target_price: float,
) -> bool:
    if direction == "Buy":
        return row["mid_high"] >= target_price
    return row["mid_low"] <= target_price


def protective_exit_price(
    direction: str,
    entry_price: float,
    stop_price: float,
    r_multiple: float,
) -> float:
    risk_distance = abs(entry_price - stop_price)
    if direction == "Buy":
        return entry_price + risk_distance * r_multiple
    return entry_price - risk_distance * r_multiple


def protective_exit_touched(
    row: dict[str, Any],
    direction: str,
    exit_price: float,
) -> bool:
    if direction == "Buy":
        return row["bid_low"] <= exit_price
    return row["ask_high"] >= exit_price


def find_exit_hit(
    execution_rows: list[dict[str, Any]],
    entry_row: int,
    max_exit_time: Any,
    direction: str,
    stop_price: float,
    target_price: float,
    entry_price: float | None = None,
    use_midpoint_tp_protective_exit: bool = False,
    midpoint_tp_protective_exit_r_multiple: float = 2.0,
) -> ExitHit:
    midpoint_tp_protection_active = False
    protective_price = None
    if use_midpoint_tp_protective_exit:
        if entry_price is None:
            raise ValueError("entry_price is required for midpoint TP protective exit.")
        protective_price = protective_exit_price(
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            r_multiple=midpoint_tp_protective_exit_r_multiple,
        )

    for idx in range(entry_row, len(execution_rows)):
        row = execution_rows[idx]
        if row["time"] > max_exit_time:
            break
        if midpoint_tp_protection_active and protective_price is not None:
            if executable_target_touched(row, direction, target_price):
                return ExitHit(row_idx=idx, reason="TP", price=target_price)
            if protective_exit_touched(row, direction, protective_price):
                return ExitHit(
                    row_idx=idx,
                    reason=MIDPOINT_TP_PROTECTIVE_EXIT_REASON,
                    price=protective_price,
                )
            if executable_stop_touched(row, direction, stop_price):
                return ExitHit(row_idx=idx, reason="SL", price=stop_price)
            continue

        hit = exit_hit_for_row(row, direction, stop_price, target_price)
        if hit is not None:
            reason, price = hit
            return ExitHit(row_idx=idx, reason=reason, price=price)
        if use_midpoint_tp_protective_exit and protective_price is not None:
            if not midpoint_tp_protection_active and midpoint_target_touched(row, direction, target_price):
                midpoint_tp_protection_active = True
    return ExitHit(row_idx=None, reason="Open", price=None)


def forced_close_price(row: dict[str, Any], direction: str) -> float:
    return row["bid_close"] if direction == "Buy" else row["ask_close"]


def pips_for_exit(
    direction: str,
    entry: float,
    exit_price: float,
    pip_size: float,
) -> float:
    if direction == "Buy":
        return (exit_price - entry) / pip_size
    return (entry - exit_price) / pip_size


def r_multiple_from_pips(pips: float, stop_loss_pips: float) -> float:
    if stop_loss_pips <= 0:
        raise ValueError("Stop loss distance must be greater than zero.")
    return pips / stop_loss_pips
