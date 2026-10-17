from __future__ import annotations

import math
from datetime import date, datetime
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo


TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365.25
LONDON_TZ = ZoneInfo("Europe/London")
UTC_TZ = ZoneInfo("UTC")


def summarize_strategy(
    signals: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    risk_per_trade: float = 0.01,
    period_start: Any | None = None,
    period_end: Any | None = None,
) -> dict[str, Any]:
    wins = count_outcome(trades, "Win")
    losses = count_outcome(trades, "Loss")
    breakeven = count_outcome(trades, "Breakeven")
    no_fill = count_outcome(trades, "No fill")
    blocked = count_outcome(trades, "Blocked")
    open_trades = count_outcome(trades, "Open")
    completed = wins + losses + breakeven

    r_values = numeric_values(trade.get("r_multiple") for trade in trades)
    winning_r = [value for value in r_values if value > 0]
    losing_r = [value for value in r_values if value < 0]
    pnl_values = numeric_values(trade.get("pnl_pct") for trade in trades)
    trade_dates = trade_datetimes(trades)
    years = elapsed_years(trade_dates)
    trades_per_year = len(r_values) / years if years > 0 else 0.0
    equity_r = cumulative_values(r_values)
    equity_pct = cumulative_values(pnl_values)
    trade_sharpe = sharpe_ratio(r_values)
    annual_trade_sharpe = annualized_sharpe(r_values, trades_per_year)
    daily_r_values = daily_return_series(trades, period_start=period_start, period_end=period_end)
    daily_sharpe = sharpe_ratio(daily_r_values)
    annual_daily_sharpe = annualized_sharpe(daily_r_values, TRADING_DAYS_PER_YEAR)

    return {
        "signals": len(signals),
        "valid_signals": sum(1 for signal in signals if signal.get("status") == "Valid"),
        "invalid_signals": sum(1 for signal in signals if signal.get("status") != "Valid"),
        "news_blocked_signals": sum(1 for signal in signals if signal.get("news_blocked")),
        "news_invalidated_signals": sum(1 for signal in signals if signal.get("news_blocked")),
        "context_blocked_signals": sum(
            1 for signal in signals if signal.get("context_filter_blocked")
        ),
        "trades": len(trades),
        "completed": completed,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "no_fill": no_fill,
        "blocked": blocked,
        "open": open_trades,
        "forced": sum(trade.get("exit_reason") in {"18:00 London Close", "News Forced Close"} for trade in trades),
        "news_forced": sum(trade.get("exit_reason") == "News Forced Close" for trade in trades),
        "win_rate": safe_divide(wins, wins + losses),
        "loss_rate": safe_divide(losses, wins + losses),
        "net_r": sum(r_values),
        "avg_r": mean(r_values),
        "median_r": median(r_values),
        "best_r": max(r_values) if r_values else 0.0,
        "worst_r": min(r_values) if r_values else 0.0,
        "gross_profit_r": sum(winning_r),
        "gross_loss_r": sum(losing_r),
        "profit_factor": profit_factor(r_values),
        "expectancy_r": mean(r_values),
        "trade_based_sharpe": trade_sharpe,
        "trade_sharpe": trade_sharpe,
        "annualized_trade_sharpe": annual_trade_sharpe,
        "annualised_trade_sharpe": annual_trade_sharpe,
        "annualized_sharpe": annual_trade_sharpe,
        "annualised_sharpe": annual_trade_sharpe,
        "daily_sharpe": daily_sharpe,
        "annualized_daily_sharpe": annual_daily_sharpe,
        "annualised_daily_sharpe": annual_daily_sharpe,
        "daily_return_days": len(daily_r_values),
        "trades_per_year": trades_per_year,
        "return_pct": sum(pnl_values) if pnl_values else sum(r_values) * risk_per_trade,
        "max_drawdown_r": max_drawdown(equity_r),
        "max_drawdown_pct": max_drawdown(equity_pct),
    }


def summarize_strategy_by_year(
    signals: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    risk_per_trade: float = 0.01,
    years: list[int] | None = None,
) -> dict[int, dict[str, Any]]:
    years_to_summarize = years or sorted(
        {
            year
            for year in [
                *(year_from_timestamp(signal.get("signal_time")) for signal in signals),
                *(year_from_timestamp(trade.get("exit_time") or trade.get("entry_time")) for trade in trades),
            ]
            if year is not None
        }
    )
    output: dict[int, dict[str, Any]] = {}
    for year in years_to_summarize:
        year_start = datetime(year, 1, 1)
        year_end = datetime(year, 12, 31, 23, 59, 59)
        year_signals = [
            signal
            for signal in signals
            if year_from_timestamp(signal.get("signal_time")) == year
        ]
        year_trades = [
            trade
            for trade in trades
            if year_from_timestamp(trade.get("exit_time") or trade.get("entry_time")) == year
        ]
        output[year] = summarize_strategy(
            year_signals,
            year_trades,
            risk_per_trade=risk_per_trade,
            period_start=year_start,
            period_end=year_end,
        )
    return output


def build_equity_curve(
    trades: list[dict[str, Any]],
    risk_per_trade: float = 0.01,
) -> list[dict[str, Any]]:
    realized_trades = [
        trade for trade in trades
        if _finite_number(trade.get("r_multiple")) is not None
        and normalize_datetime(trade.get("exit_time") or trade.get("entry_time")) is not None
    ]
    realized_trades.sort(
        key=lambda trade: normalize_datetime(trade.get("exit_time") or trade.get("entry_time")) or datetime.max
    )

    cumulative_r = 0.0
    peak_r = 0.0
    rows: list[dict[str, Any]] = []
    for trade_number, trade in enumerate(realized_trades, start=1):
        r_multiple = _finite_number(trade.get("r_multiple")) or 0.0
        cumulative_r += r_multiple
        peak_r = max(peak_r, cumulative_r)
        drawdown_r = cumulative_r - peak_r
        cumulative_return_pct = cumulative_r * risk_per_trade
        rows.append(
            {
                "trade_number": trade_number,
                "signal_id": trade.get("signal_id"),
                "entry_time": trade.get("entry_time"),
                "exit_time": trade.get("exit_time"),
                "direction": trade.get("direction"),
                "setup_type": trade.get("setup_type"),
                "outcome": trade.get("outcome"),
                "exit_reason": trade.get("exit_reason"),
                "r_multiple": r_multiple,
                "pnl_pct": trade.get("pnl_pct"),
                "cumulative_r": cumulative_r,
                "equity_peak_r": peak_r,
                "drawdown_r": drawdown_r,
                "cumulative_return_pct": cumulative_return_pct,
            }
        )
    return rows


def build_signal_audit(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for signal in signals:
        status = signal.get("status") or ""
        reason = signal.get("reason") or ""
        rows.append(
            {
                "signal_id": signal.get("signal_id"),
                "signal_time": signal.get("signal_time"),
                "execution_start_time": signal.get("execution_start_time"),
                "direction": signal.get("direction"),
                "setup_type": signal.get("setup_type"),
                "status": status,
                "final_status": signal.get("final_status"),
                "reject_category": signal_reject_category(signal),
                "reason": reason,
                "final_reason": signal.get("final_reason"),
                "obstacle_hit": bool(signal.get("obstacle_hit")),
                "news_blocked": bool(signal.get("news_blocked")),
                "news_event_ids": signal.get("news_event_ids"),
                "news_events": signal.get("news_events"),
                "run_count": signal.get("run_count"),
                "largest_body_pips": signal.get("largest_body_pips"),
                "entry_frozen": bool(signal.get("entry_frozen")),
                "entry": signal.get("entry"),
                "stop_loss": signal.get("stop_loss"),
                "take_profit": signal.get("take_profit"),
                "entry_deadline": signal.get("entry_deadline"),
                "source_row": signal.get("source_row"),
                "run_start": signal.get("run_start"),
                "run_end": signal.get("run_end"),
                "signal_text": signal.get("signal_text"),
                "extension_freeze": bool(signal.get("extension_freeze")),
                "extension_freeze_reason": signal.get("extension_freeze_reason"),
                "extension_freeze_touch_time": signal.get("extension_freeze_touch_time"),
                "extension_freeze_candidate_time": signal.get("extension_freeze_candidate_time"),
                "extension_freeze_line_version": signal.get("extension_freeze_line_version"),
                "context_filter_blocked": bool(signal.get("context_filter_blocked")),
                "context_filter_reason": signal.get("context_filter_reason"),
                "adverse_asia_reversal_sell_filter_triggered": bool(
                    signal.get("adverse_asia_reversal_sell_filter_triggered")
                ),
                "active_price_cluster_stop_filter_triggered": bool(
                    signal.get("active_price_cluster_stop_filter_triggered")
                ),
                "adverse_order_block_stop_filter_triggered": bool(
                    signal.get("adverse_order_block_stop_filter_triggered")
                ),
                "pre_run_structure_direction": signal.get("pre_run_structure_direction"),
                "previous_day_signed_pfe_trade_direction": signal.get(
                    "previous_day_signed_pfe_trade_direction"
                ),
                "pre_run_asia_signed_pfe_trade_direction": signal.get(
                    "pre_run_asia_signed_pfe_trade_direction"
                ),
                "adverse_asia_reversal_sell": bool(
                    signal.get("adverse_asia_reversal_sell")
                ),
                "active_cluster_present_ahead": bool(
                    signal.get("active_cluster_present_ahead")
                ),
                "active_cluster_count_ahead": signal.get("active_cluster_count_ahead"),
                "active_terminal_cluster_id": signal.get("active_terminal_cluster_id"),
                "active_terminal_cluster_low": signal.get("active_terminal_cluster_low"),
                "active_terminal_cluster_high": signal.get("active_terminal_cluster_high"),
                "active_terminal_cluster_source_move_id": signal.get(
                    "active_terminal_cluster_source_move_id"
                ),
                "active_terminal_cluster_source_move_start_time": signal.get(
                    "active_terminal_cluster_source_move_start_time"
                ),
                "active_terminal_cluster_source_move_end_time": signal.get(
                    "active_terminal_cluster_source_move_end_time"
                ),
                "active_cluster_interaction": signal.get("active_cluster_interaction"),
                "run_stopped_at_active_cluster": bool(
                    signal.get("run_stopped_at_active_cluster")
                ),
                "run_cleared_active_cluster_count": signal.get(
                    "run_cleared_active_cluster_count"
                ),
                "active_order_block_count_ahead": signal.get(
                    "active_order_block_count_ahead"
                ),
                "terminal_order_block_id": signal.get("terminal_order_block_id"),
                "terminal_order_block_low": signal.get("terminal_order_block_low"),
                "terminal_order_block_high": signal.get("terminal_order_block_high"),
                "terminal_order_block_source_move_id": signal.get(
                    "terminal_order_block_source_move_id"
                ),
                "terminal_order_block_source_move_start_time": signal.get(
                    "terminal_order_block_source_move_start_time"
                ),
                "terminal_order_block_source_move_end_time": signal.get(
                    "terminal_order_block_source_move_end_time"
                ),
                "order_block_broad_interaction": signal.get(
                    "order_block_broad_interaction"
                ),
                "order_block_reached_without_clean_close": bool(
                    signal.get("order_block_reached_without_clean_close")
                ),
                "run_cleared_order_block_count": signal.get(
                    "run_cleared_order_block_count"
                ),
                "adverse_order_block_stop": bool(
                    signal.get("adverse_order_block_stop")
                ),
            }
        )
    return rows


def signal_reject_category(signal: dict[str, Any]) -> str:
    if signal.get("status") == "Valid":
        return "Accepted"
    reason = str(signal.get("reason") or "")
    categories: list[str] = []
    if signal.get("news_blocked") or "News invalidation" in reason or "News blackout" in reason:
        categories.append("News")
    if signal.get("obstacle_hit") or "obstacle" in reason.lower():
        categories.append("Obstacle")
    if signal.get("context_filter_blocked"):
        categories.append("Market Context")
    if "Too many candles" in reason:
        categories.append("Run Length")
    if "Imb candle too small" in reason:
        categories.append("Imbalance")
    if "Same direction as first valid tradable signal" in reason:
        categories.append("Signal Frequency")
    if not categories:
        categories.append("Other")
    return " + ".join(categories)


def count_outcome(trades: list[dict[str, Any]], outcome: str) -> int:
    return sum(trade.get("outcome") == outcome for trade in trades)


def numeric_values(values: Any) -> list[float]:
    output: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            output.append(number)
    return output


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def sample_stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def sharpe_ratio(values: list[float]) -> float:
    stdev = sample_stdev(values)
    return mean(values) / stdev if stdev else 0.0


def annualized_sharpe(values: list[float], periods_per_year: float) -> float:
    if periods_per_year <= 0:
        return 0.0
    return sharpe_ratio(values) * math.sqrt(periods_per_year)


def profit_factor(values: list[float]) -> float:
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = abs(sum(value for value in values if value < 0))
    if gross_loss == 0:
        return 0.0 if gross_profit == 0 else math.inf
    return gross_profit / gross_loss


def cumulative_values(values: list[float]) -> list[float]:
    equity = 0.0
    output: list[float] = []
    for value in values:
        equity += value
        output.append(equity)
    return output


def max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = max(0.0, equity_curve[0])
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        worst = min(worst, value - peak)
    return worst


def daily_return_series(
    trades: list[dict[str, Any]],
    period_start: Any | None = None,
    period_end: Any | None = None,
) -> list[float]:
    daily_r: dict[date, float] = {}
    trade_dates: list[date] = []
    for trade in trades:
        r_multiple = trade.get("r_multiple")
        if r_multiple is None:
            continue
        normalized_date = london_date(trade.get("exit_time") or trade.get("entry_time"))
        if normalized_date is None:
            continue
        trade_dates.append(normalized_date)
        daily_r[normalized_date] = daily_r.get(normalized_date, 0.0) + float(r_multiple)

    start_date = london_date(period_start) if period_start is not None else None
    end_date = london_date(period_end) if period_end is not None else None
    if start_date is None and trade_dates:
        start_date = min(trade_dates)
    if end_date is None and trade_dates:
        end_date = max(trade_dates)
    if start_date is None or end_date is None or end_date < start_date:
        return []

    values: list[float] = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            values.append(daily_r.get(current, 0.0))
        current += timedelta(days=1)
    return values


def trade_datetimes(trades: list[dict[str, Any]]) -> list[datetime]:
    values: list[datetime] = []
    for trade in trades:
        timestamp = trade.get("entry_time") or trade.get("exit_time")
        normalized = normalize_datetime(timestamp)
        if normalized is not None:
            values.append(normalized)
    return sorted(values)


def normalize_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def london_date(value: Any) -> date | None:
    normalized = normalize_datetime(value)
    if normalized is None:
        return None
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=UTC_TZ)
    return normalized.astimezone(LONDON_TZ).date()


def year_from_timestamp(value: Any) -> int | None:
    normalized_date = london_date(value)
    return normalized_date.year if normalized_date is not None else None


def elapsed_years(values: list[datetime]) -> float:
    if len(values) < 2:
        return 0.0
    elapsed_days = (max(values) - min(values)).total_seconds() / 86400
    return max(elapsed_days / CALENDAR_DAYS_PER_YEAR, 1 / CALENDAR_DAYS_PER_YEAR)
