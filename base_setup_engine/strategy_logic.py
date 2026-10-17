from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import asdict
from dataclasses import replace as replace_dataclass
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any

try:
    from .context_filter_logic import context_filters_enabled
    from .context_filter_logic import MarketContextIndex
    from .entry_exit_logic import entry_trigger_price_touched
    from .entry_exit_logic import live_entry_price
    from .entry_exit_logic import signal_entry_exit_levels
    from .market_sessions import LONDON_SETUP_START
    from .market_sessions import PRE_LONDON_STRUCTURE_START
    from .market_sessions import london_setup_end_utc_naive
    from .market_sessions import normalize_utc_naive
    from .market_sessions import is_asia_session
    from .market_sessions import session_flags
    from .market_sessions import to_london
    from .metrics import build_equity_curve
    from .metrics import build_signal_audit
    from .metrics import summarize_strategy
    from .metrics import summarize_strategy_by_year
    from .models import PriceFile
    from .models import StrategyParams
    from .news_loader import event_to_record
    from .news_loader import load_news_events
    from .news_loader import NewsFilterConfig
    from .obstacle_logic import add_consolidation_obstacle
    from .obstacle_logic import add_pivot_obstacle
    from .obstacle_logic import add_resistance_trendlines
    from .obstacle_logic import add_support_trendlines
    from .obstacle_logic import check_run_obstacles
    from .obstacle_logic import deactivate_pivot_obstacles
    from .obstacle_logic import deactivate_trendline_obstacles
    from .obstacle_logic import update_consolidation_obstacles
    from .price_data_loader import discover_price_files
    from .price_data_loader import iter_mba_rows
    from .price_data_loader import years_between
    from .setup_logic import asia_break_flags
    from .setup_logic import BreakFlags
    from .setup_logic import buy_b_triggered
    from .setup_logic import consolidation_break_flags
    from .setup_logic import consolidation_snapshot
    from .setup_logic import daily_swing_break_flags
    from .setup_logic import internal_structure_break_flags
    from .setup_logic import sell_b_triggered
    from .setup_logic import setup_signals
    from .setup_logic import setup_sources_text
    from .setup_logic import signal_text
    from .setup_logic import update_first_break_locks
    from .strategy_state import StrategyRuntimeState
    from .trade_simulator import apply_news_forced_close
    from .trade_simulator import apply_same_day_18_close
    from .trade_simulator import generate_trades_with_execution_data
except ImportError:
    from context_filter_logic import context_filters_enabled
    from context_filter_logic import MarketContextIndex
    from entry_exit_logic import entry_trigger_price_touched
    from entry_exit_logic import live_entry_price
    from entry_exit_logic import signal_entry_exit_levels
    from market_sessions import LONDON_SETUP_START
    from market_sessions import PRE_LONDON_STRUCTURE_START
    from market_sessions import london_setup_end_utc_naive
    from market_sessions import normalize_utc_naive
    from market_sessions import is_asia_session
    from market_sessions import session_flags
    from market_sessions import to_london
    from metrics import build_equity_curve
    from metrics import build_signal_audit
    from metrics import summarize_strategy
    from metrics import summarize_strategy_by_year
    from models import PriceFile
    from models import StrategyParams
    from news_loader import event_to_record
    from news_loader import load_news_events
    from news_loader import NewsFilterConfig
    from obstacle_logic import add_consolidation_obstacle
    from obstacle_logic import add_pivot_obstacle
    from obstacle_logic import add_resistance_trendlines
    from obstacle_logic import add_support_trendlines
    from obstacle_logic import check_run_obstacles
    from obstacle_logic import deactivate_pivot_obstacles
    from obstacle_logic import deactivate_trendline_obstacles
    from obstacle_logic import update_consolidation_obstacles
    from price_data_loader import discover_price_files
    from price_data_loader import iter_mba_rows
    from price_data_loader import years_between
    from setup_logic import asia_break_flags
    from setup_logic import BreakFlags
    from setup_logic import buy_b_triggered
    from setup_logic import consolidation_break_flags
    from setup_logic import consolidation_snapshot
    from setup_logic import daily_swing_break_flags
    from setup_logic import internal_structure_break_flags
    from setup_logic import sell_b_triggered
    from setup_logic import setup_signals
    from setup_logic import setup_sources_text
    from setup_logic import signal_text
    from setup_logic import update_first_break_locks
    from strategy_state import StrategyRuntimeState
    from trade_simulator import apply_news_forced_close
    from trade_simulator import apply_same_day_18_close
    from trade_simulator import generate_trades_with_execution_data


def strategy_config(params: StrategyParams) -> dict[str, Any]:
    return asdict(params) | {
        "rules_source": [
            "Shared_Candle_Session_Rules.docx",
            "Asia_Break_Setup_Rules.docx",
            "DS_Setup_Rules.docx",
            "Consolidation_Setup_Rules.docx",
            "Internal_Structure_BOS_Setup_Rules",
            "First_London_Break_Filter_Rules.docx",
            "Imbalance_Run_Signal_Validation_Rules.docx",
            "Buy_B_Sell_B_Rules.docx",
            "Entry_Line_Freeze_Rules.docx",
            "Obstacle_Filter_Rules.docx",
        ],
        "price_model": "MBA: 15m signals and entry lines use midpoint bodies; 1m execution uses ask buy fills and bid sell fills.",
        "news_filter": "High-impact GBP/USD calendar events invalidate imbalance runs when the event occurs inside the run candle window.",
        "news_forced_close": "Open trades can be managed separately with a pre-news forced close before same-day high-impact GBP/USD events.",
        "params_source": "Excel Strategy_Params sheet values override Python defaults at run time.",
    }


def buy_b_asia_range_pips(state: StrategyRuntimeState, params: StrategyParams) -> float | None:
    if state.asia_high is None or state.asia_low is None:
        return None
    return (state.asia_high - state.asia_low) / params.pip_size


def buy_b_asia_range_allowed(state: StrategyRuntimeState, params: StrategyParams) -> bool:
    if not params.use_buy_b_asia_range_filter:
        return True
    current_range = buy_b_asia_range_pips(state, params)
    return current_range is not None and current_range <= params.buy_b_max_asia_body_range_pips + 1e-9


def buy_b_asia_range_reject_reason(state: StrategyRuntimeState, params: StrategyParams) -> str:
    current_range = buy_b_asia_range_pips(state, params)
    if current_range is None:
        return "Buy B Asia body range unavailable"
    return (
        "Buy B Asia body range too wide: "
        f"{current_range:.1f}p > {params.buy_b_max_asia_body_range_pips:g}p"
    )


def maybe_create_pre_london_observation_pivot(
    state: StrategyRuntimeState,
    prev: dict[str, Any] | None,
    row: dict[str, Any],
    structure_break: float,
    setup_break: float,
) -> None:
    if prev is None or not is_pre_london_observation_pair(prev, row):
        return

    pre_london_bull_pivot_break = bool(
        state.asia_high is not None
        and prev["buy_body_high"] > state.asia_high + structure_break
        and prev["mid_close"] > state.asia_high + structure_break
    )
    pre_london_bear_pivot_break = bool(
        state.asia_low is not None
        and prev["sell_body_low"] < state.asia_low - structure_break
        and prev["mid_close"] < state.asia_low - structure_break
    )
    pre_london_bull_setup_break = bool(
        state.asia_high is not None
        and prev["buy_body_high"] > state.asia_high + setup_break
        and prev["mid_close"] > state.asia_high + setup_break
    )
    pre_london_bear_setup_break = bool(
        state.asia_low is not None
        and prev["sell_body_low"] < state.asia_low - setup_break
        and prev["mid_close"] < state.asia_low - setup_break
    )
    london_bull_structure_break = bool(
        state.asia_high is not None
        and row["buy_body_high"] > state.asia_high + structure_break
        and row["mid_close"] > state.asia_high + structure_break
    )
    london_bear_structure_break = bool(
        state.asia_low is not None
        and row["sell_body_low"] < state.asia_low - structure_break
        and row["mid_close"] < state.asia_low - structure_break
    )
    london_bull_setup_break = bool(
        state.asia_high is not None
        and row["buy_body_high"] > state.asia_high + setup_break
        and row["mid_close"] > state.asia_high + setup_break
    )
    london_bear_setup_break = bool(
        state.asia_low is not None
        and row["sell_body_low"] < state.asia_low - setup_break
        and row["mid_close"] < state.asia_low - setup_break
    )

    if (
        pre_london_bull_pivot_break
        and row["direction"] == -1
    ):
        state.pre_london_resistance_pivot = pre_london_pivot_zone(prev, row, "resistance")
    elif (
        pre_london_bull_pivot_break
        and row["direction"] == 1
        and (
            london_bull_setup_break
            or (pre_london_bull_setup_break and london_bull_structure_break)
        )
    ):
        state.consume_pre_london_asia_break("Buy")

    if (
        pre_london_bear_pivot_break
        and row["direction"] == 1
    ):
        state.pre_london_support_pivot = pre_london_pivot_zone(prev, row, "support")
    elif (
        pre_london_bear_pivot_break
        and row["direction"] == -1
        and (
            london_bear_setup_break
            or (pre_london_bear_setup_break and london_bear_structure_break)
        )
    ):
        state.consume_pre_london_asia_break("Sell")


def is_pre_london_observation_pair(prev: dict[str, Any], row: dict[str, Any]) -> bool:
    if prev["london_date"] != row["london_date"]:
        return False
    prev_time = prev["london_time"].time()
    row_time = row["london_time"].time()
    return (
        prev_time.hour == 7
        and prev_time.minute == 45
        and row_time.hour == 8
        and row_time.minute == 0
    )


def pre_london_pivot_zone(
    first_row: dict[str, Any],
    second_row: dict[str, Any],
    side: str,
) -> dict[str, Any]:
    body_prices = [
        first_row["mid_open"],
        first_row["mid_close"],
        second_row["mid_open"],
        second_row["mid_close"],
    ]
    if side == "resistance":
        ranked = sorted(body_prices, reverse=True)
        return {
            "side": side,
            "top": ranked[0],
            "bottom": ranked[2],
            "pivot_level": ranked[0],
            "formed_from": (first_row["time"], second_row["time"]),
        }

    ranked = sorted(body_prices)
    return {
        "side": side,
        "top": ranked[2],
        "bottom": ranked[0],
        "pivot_level": ranked[0],
        "formed_from": (first_row["time"], second_row["time"]),
    }


def apply_pre_london_pivot_to_asia_break(
    flags: BreakFlags,
    state: StrategyRuntimeState,
    row: dict[str, Any],
    bull: bool,
    bear: bool,
    prev_buy_body_high: float | None,
    prev_sell_body_low: float | None,
    structure_break: float,
    setup_break: float,
) -> BreakFlags:
    bull_break = flags.bull_break
    bull_setup = flags.bull_setup
    bear_break = flags.bear_break
    bear_setup = flags.bear_setup

    resistance = state.pre_london_resistance_pivot
    if resistance is not None:
        pivot_top = resistance["top"]
        bull_break = bool(
            bull
            and not state.asia_bull_done
            and row["buy_body_high"] > pivot_top + structure_break
            and prev_buy_body_high is not None
            and prev_buy_body_high <= pivot_top
        )
        bull_setup = bool(
            bull_break
            and row["buy_body_high"] > pivot_top + setup_break
            and row["mid_close"] > pivot_top + setup_break
        )

    support = state.pre_london_support_pivot
    if support is not None:
        pivot_bottom = support["bottom"]
        bear_break = bool(
            bear
            and not state.asia_bear_done
            and row["sell_body_low"] < pivot_bottom - structure_break
            and prev_sell_body_low is not None
            and prev_sell_body_low >= pivot_bottom
        )
        bear_setup = bool(
            bear_break
            and row["sell_body_low"] < pivot_bottom - setup_break
            and row["mid_close"] < pivot_bottom - setup_break
        )

    return BreakFlags(
        bull_break=bull_break,
        bear_break=bear_break,
        bull_setup=bull_setup,
        bear_setup=bear_setup,
    )

def prior_body_reached_a_run_extreme(
    rows: list[dict[str, Any]],
    idx: int,
    current_run: dict[str, Any] | None,
    side: str,
    pip_size: float,
) -> str | None:
    row = rows[idx]
    same_direction_run = current_run if current_run and current_run["direction"] == row["direction"] else None
    run_start_i = same_direction_run["start_i"] if same_direction_run else idx
    if run_start_i <= 0:
        return None

    london_date = row["london_date"]
    prior_rows = [
        prior
        for prior in rows[:run_start_i]
        if prior["london_date"] == london_date
        and prior["london_time"].time() >= PRE_LONDON_STRUCTURE_START
    ]
    if not prior_rows:
        return None

    if side == "Buy":
        current_extreme = row["buy_body_high"]
        run_extreme = max(same_direction_run["high"], current_extreme) if same_direction_run else current_extreme
        prior_extreme = max(prior["buy_body_high"] for prior in prior_rows)
        if prior_extreme >= run_extreme:
            gap_pips = (run_extreme - prior_extreme) / pip_size
            return (
                "A setup blocked: prior 07:45+ body high already reached "
                f"run high ({prior_extreme:.5f} >= {run_extreme:.5f}, {gap_pips:.1f}p)"
            )
        return None

    current_extreme = row["sell_body_low"]
    run_extreme = min(same_direction_run["low"], current_extreme) if same_direction_run else current_extreme
    prior_extreme = min(prior["sell_body_low"] for prior in prior_rows)
    if prior_extreme <= run_extreme:
        gap_pips = (prior_extreme - run_extreme) / pip_size
        return (
            "A setup blocked: prior 07:45+ body low already reached "
            f"run low ({prior_extreme:.5f} <= {run_extreme:.5f}, {gap_pips:.1f}p)"
        )
    return None


def same_impulse_created_asia_extreme(
    rows: list[dict[str, Any]],
    idx: int,
    current_run: dict[str, Any] | None,
    state: StrategyRuntimeState,
    side: str,
) -> str | None:
    row = rows[idx]
    same_direction_run = current_run if current_run and current_run["direction"] == row["direction"] else None
    if same_direction_run is None:
        return None

    if side == "Buy":
        asia_extreme = state.asia_high
        extreme_key = "buy_body_high"
        wanted_direction = 1
        label = "high"
    else:
        asia_extreme = state.asia_low
        extreme_key = "sell_body_low"
        wanted_direction = -1
        label = "low"

    if asia_extreme is None:
        return None

    for run_i in range(same_direction_run["start_i"], idx):
        run_row = rows[run_i]
        if run_row["london_date"] != row["london_date"]:
            continue
        if not is_asia_session(run_row["london_time"]):
            continue
        if run_row["direction"] != wanted_direction:
            continue
        if abs(run_row[extreme_key] - asia_extreme) > 1e-9:
            continue
        return (
            "A setup blocked: same directional imbalance run created Asia "
            f"{label} before the London break"
        )

    return None


def obstacle_strength_override_details(
    rows: list[dict[str, Any]],
    run_obj: dict[str, Any],
    params: StrategyParams,
    obstacle_check: Any,
) -> tuple[bool, str]:
    if not params.use_obstacle_strength_override or not obstacle_check.hit:
        return False, ""
    if not obstacle_override_applies_to_hit(obstacle_check, params):
        return False, ""
    if (
        params.obstacle_override_require_setup_confluence
        and not (run_obj.get("asia_valid") and run_obj.get("ds_valid"))
    ):
        return False, ""
    if run_obj.get("largest_body_pips", 0.0) + 1e-9 < params.obstacle_override_min_largest_body_pips:
        return False, ""

    ratio = obstacle_run_pre_run_asia_range_ratio(rows, run_obj, params)
    threshold = normalized_obstacle_override_threshold(params)
    if ratio is None or ratio + 1e-12 < threshold:
        return False, ""

    return (
        True,
        f"Obstacle override: run/pre-run Asia body range {ratio:.1%} >= {threshold:.1%}",
    )


def obstacle_override_applies_to_hit(obstacle_check: Any, params: StrategyParams) -> bool:
    trendline_hit = obstacle_check.buy_trendline_hit or obstacle_check.sell_trendline_hit
    if trendline_hit:
        return False
    pivot_hit = obstacle_check.buy_resistance_hit or obstacle_check.sell_support_hit
    consolidation_hit = obstacle_check.buy_consolidation_hit or obstacle_check.sell_consolidation_hit
    if pivot_hit and not params.obstacle_override_apply_to_pivot:
        return False
    if consolidation_hit and not params.obstacle_override_apply_to_consolidation:
        return False
    return pivot_hit or consolidation_hit


def normalized_obstacle_override_threshold(params: StrategyParams) -> float:
    threshold = float(params.obstacle_override_min_run_range_ratio)
    if threshold > 1.0:
        threshold /= 100.0
    return max(0.0, threshold)


def obstacle_run_pre_run_asia_range_ratio(
    rows: list[dict[str, Any]],
    run_obj: dict[str, Any],
    params: StrategyParams,
) -> float | None:
    run_start_i = run_obj.get("start_i")
    if not isinstance(run_start_i, int) or run_start_i <= 0 or run_start_i >= len(rows):
        return None

    london_date = rows[run_start_i]["london_date"]
    pre_run_rows = [row for row in rows[:run_start_i] if row["london_date"] == london_date]
    if not pre_run_rows:
        return None

    pre_run_high = max(row["mid_body_high"] for row in pre_run_rows)
    pre_run_low = min(row["mid_body_low"] for row in pre_run_rows)
    pre_run_range = pre_run_high - pre_run_low
    run_range = float(run_obj["high"]) - float(run_obj["low"])
    if pre_run_range <= 1e-12 or run_range <= 0:
        return None
    return run_range / pre_run_range


def internal_structure_asia_move_allowed(
    rows: list[dict[str, Any]],
    idx: int,
    side: str,
    params: StrategyParams,
) -> bool:
    if not params.use_internal_structure_asia_move_filter:
        return True

    asia_rows = [
        row
        for row in rows[:idx]
        if row["london_date"] == rows[idx]["london_date"]
        and is_asia_session(row["london_time"])
    ]
    if len(asia_rows) < 2:
        return False

    threshold = normalized_percent_param(params.internal_structure_min_asia_body_move_pct)
    if side == "Buy":
        return max_forward_body_drop_pct(asia_rows) + 1e-12 >= threshold
    return max_forward_body_rise_pct(asia_rows) + 1e-12 >= threshold


def internal_structure_asia_move_allowed_from_state(
    state: StrategyRuntimeState,
    side: str,
    params: StrategyParams,
) -> bool:
    if not params.use_internal_structure_asia_move_filter:
        return True
    threshold = normalized_percent_param(params.internal_structure_min_asia_body_move_pct)
    if side == "Buy":
        return state.asia_max_body_drop_pct + 1e-12 >= threshold
    return state.asia_max_body_rise_pct + 1e-12 >= threshold


def normalized_percent_param(value: float) -> float:
    numeric = float(value)
    if numeric > 0.05:
        return numeric / 100.0
    return numeric


def max_forward_body_drop_pct(rows: list[dict[str, Any]]) -> float:
    peak = float(rows[0]["mid_body_high"])
    best = 0.0
    for row in rows:
        body_low = float(row["mid_body_low"])
        if peak > 0:
            best = max(best, (peak - body_low) / peak)
        peak = max(peak, float(row["mid_body_high"]))
    return best


def max_forward_body_rise_pct(rows: list[dict[str, Any]]) -> float:
    trough = float(rows[0]["mid_body_low"])
    best = 0.0
    for row in rows:
        body_high = float(row["mid_body_high"])
        if trough > 0:
            best = max(best, (body_high - trough) / trough)
        trough = min(trough, float(row["mid_body_low"]))
    return best


def run_strategy_for_period(
    project_root: Path,
    period_start: Any,
    period_end: Any,
    params: StrategyParams | None = None,
    news_root: Path | None = None,
) -> dict[str, Any]:
    params = params or StrategyParams()
    years = years_between(period_start, period_end)
    m15_rows = load_price_rows(project_root, years, "15m")
    m1_rows = load_price_rows(project_root, years, "1m")
    news_events = load_strategy_news_events(news_root or project_root, period_start, period_end, params)
    signals = generate_signals(m15_rows, params, news_events=news_events, execution_rows=m1_rows)
    trades = generate_trades_with_execution_data(m15_rows, m1_rows, signals, params)
    if params.use_news_forced_close:
        trades = apply_news_forced_close(trades, m1_rows, news_events, params)
    if params.force_close_at_18_london:
        trades = apply_same_day_18_close(trades, m1_rows, params)
    equity_curve = build_equity_curve(trades, risk_per_trade=params.risk_per_trade)
    signal_audit = build_signal_audit(signals)
    return {
        "years": years,
        "news_events": [event_to_record(event) for event in news_events],
        "signals": signals,
        "trades": trades,
        "equity_curve": equity_curve,
        "signal_audit": signal_audit,
        "summary": summarize_strategy(
            signals,
            trades,
            risk_per_trade=params.risk_per_trade,
            period_start=period_start,
            period_end=period_end,
        ),
        "yearly_summary": summarize_strategy_by_year(
            signals,
            trades,
            risk_per_trade=params.risk_per_trade,
            years=years,
        ),
        "params": strategy_config(params),
    }


def load_strategy_news_events(
    project_root: Path,
    period_start: Any,
    period_end: Any,
    params: StrategyParams,
) -> list[Any]:
    if not (params.use_news_filter or params.use_news_forced_close):
        return []
    years = years_between(period_start, period_end)
    start = datetime(min(years), 1, 1)
    end = datetime(max(years), 12, 31, 23, 59, 59)
    return load_news_events(
        project_root=project_root,
        start=start,
        end=end,
        currencies=params.news_currencies,
        impacts=params.news_impacts,
        paths=list(params.news_calendar_paths) if params.news_calendar_paths else None,
        source_timezone=params.news_source_timezone,
    )


def load_price_rows(project_root: Path, years: list[int], timeframe: str) -> list[dict[str, Any]]:
    price_files = [
        item for item in discover_price_files(project_root, years=years)
        if item.timeframe == timeframe
    ]
    rows: list[dict[str, Any]] = []
    for price_file in sorted(price_files, key=lambda item: item.year):
        rows.extend(normalize_price_row(row, price_file) for row in iter_mba_rows(price_file))
    rows.sort(key=lambda item: item["time"])
    return rows


def normalize_price_row(row: dict[str, Any], price_file: PriceFile) -> dict[str, Any]:
    timestamp = normalize_utc_naive(row["time"])
    london_time = to_london(timestamp)
    mid_body_high = body_high(row["mid_open"], row["mid_close"])
    mid_body_low = body_low(row["mid_open"], row["mid_close"])
    return {
        "time": timestamp,
        "london_time": london_time,
        "london_date": london_time.date(),
        "year": price_file.year,
        "mid_open": float(row["mid_open"]),
        "mid_high": float(row["mid_high"]),
        "mid_low": float(row["mid_low"]),
        "mid_close": float(row["mid_close"]),
        "bid_open": float(row["bid_open"]),
        "bid_high": float(row["bid_high"]),
        "bid_low": float(row["bid_low"]),
        "bid_close": float(row["bid_close"]),
        "ask_open": float(row["ask_open"]),
        "ask_high": float(row["ask_high"]),
        "ask_low": float(row["ask_low"]),
        "ask_close": float(row["ask_close"]),
        "volume": row.get("volume"),
        "buy_body_high": mid_body_high,
        "buy_body_low": mid_body_low,
        "buy_body_size": mid_body_high - mid_body_low,
        "sell_body_high": mid_body_high,
        "sell_body_low": mid_body_low,
        "sell_body_size": mid_body_high - mid_body_low,
        "mid_body_high": mid_body_high,
        "mid_body_low": mid_body_low,
        "mid_body_size": mid_body_high - mid_body_low,
        "direction": candle_direction(row["mid_open"], row["mid_close"]),
    }


def generate_signals(
    rows: list[dict[str, Any]],
    params: StrategyParams,
    news_events: list[Any] | None = None,
    execution_rows: list[dict[str, Any]] | None = None,
    context_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not rows:
        return []

    pip = params.pip_size
    structure_break = params.structure_break_pips * pip
    setup_break = params.setup_break_pips * pip
    min_imbalance = params.min_imbalance_pips * pip
    max_range = params.max_consolidation_body_range_pips * pip
    similar_tolerance = params.similar_level_pips * pip
    bars_required = max(2, math.ceil(params.min_consolidation_hours * 60 / 15))
    signal_tf_minutes = infer_timeframe_minutes(rows)
    internal_structure_lookback_bars = max(
        2,
        math.ceil(params.internal_structure_lookback_hours * 60 / signal_tf_minutes),
    )
    internal_structure_tolerance = params.internal_structure_level_tolerance_pips * pip
    internal_structure_max_range = params.internal_structure_max_shelf_body_range_pips * pip
    trendline_obstacle_size = params.trendline_obstacle_pips * pip
    trendline_validation_tolerance = params.trendline_validation_tolerance_pips * pip

    buy_body_highs = [row["buy_body_high"] for row in rows]
    sell_body_lows = [row["sell_body_low"] for row in rows]
    pivot_high_confirmed = find_pivots(buy_body_highs, params.left_bars, params.right_bars, "high")
    pivot_low_confirmed = find_pivots(sell_body_lows, params.left_bars, params.right_bars, "low")
    context_history = context_rows or rows
    context_row_offset = 0
    if context_history is not rows:
        context_row_offset = len(context_history) - len(rows)
        suffix_matches = bool(
            context_row_offset >= 0
            and context_history[context_row_offset]["time"] == rows[0]["time"]
            and context_history[-1]["time"] == rows[-1]["time"]
        )
        if not suffix_matches:
            raise ValueError("context_rows must end with the complete signal rows")
    context_index = (
        MarketContextIndex(context_history, params)
        if context_filters_enabled(params)
        else None
    )

    state = StrategyRuntimeState()
    news_events = news_events or []
    resistance_obstacles: list[dict[str, Any]] = []
    support_obstacles: list[dict[str, Any]] = []
    consolidation_obstacles: list[dict[str, Any]] = []
    resistance_trendlines: list[dict[str, Any]] = []
    support_trendlines: list[dict[str, Any]] = []
    trendline_pivot_highs: list[tuple[int, float]] = []
    trendline_pivot_lows: list[tuple[int, float]] = []
    first_signal_sides_by_london_day: dict[Any, set[str]] = {}
    execution_rows = sorted(execution_rows or [], key=lambda item: item["time"])
    execution_times = [row["time"] for row in execution_rows]

    def execution_available_from(row_time: datetime) -> datetime:
        if params.execution_starts_after_signal_close:
            return row_time + timedelta(minutes=signal_tf_minutes)
        return row_time

    def stop_latest_entry_line(run: dict[str, Any], active_until: datetime) -> None:
        events = run.get("entry_line_events") or []
        if not events:
            return
        latest = events[-1]
        current_until = latest.get("active_until") or latest["expires_at"]
        latest["active_until"] = min(current_until, active_until)

    def latest_entry_line_touch_before_candle_close(
        run: dict[str, Any],
        candle_open: datetime,
        candle_close: datetime,
    ) -> dict[str, Any] | None:
        if not execution_rows:
            return None
        events = run.get("entry_line_events") or []
        if not events:
            return None

        latest = events[-1]
        active_from = latest.get("available_from")
        active_until = latest.get("active_until") or latest.get("expires_at")
        if active_from is None or active_until is None:
            return None

        window_start = max(active_from, candle_open)
        window_end = min(active_until, candle_close)
        if window_end <= window_start:
            return None

        idx = bisect_left(execution_times, window_start)
        while idx < len(execution_rows):
            execution_row = execution_rows[idx]
            row_time = execution_row["time"]
            if row_time >= window_end:
                break
            if entry_trigger_price_touched(
                execution_row,
                latest["direction"],
                latest["entry"],
                params.entry_fill_trigger_price_mode,
            ):
                return {
                    "event": latest,
                    "touch_time": row_time,
                    "touch_row": idx + 2,
                    "candidate_candle_time": candle_open,
                    "candidate_candle_close": candle_close,
                }
            idx += 1
        return None

    def maybe_freeze_run_before_extension(idx: int, row: dict[str, Any]) -> bool:
        run = state.run
        if not run or run["direction"] == 0 or row["direction"] != run["direction"]:
            return False
        touch = latest_entry_line_touch_before_candle_close(
            run,
            row["time"],
            execution_available_from(row["time"]),
        )
        if touch is None:
            return False

        event = touch["event"]
        run["extension_freeze"] = {
            "line_version": event.get("line_version"),
            "line_time": event.get("line_time"),
            "line_entry": event.get("entry"),
            "line_available_from": event.get("available_from"),
            "touch_time": touch["touch_time"],
            "touch_row": touch["touch_row"],
            "candidate_source_row": idx + 2,
            "candidate_candle_time": touch["candidate_candle_time"],
            "candidate_candle_close": touch["candidate_candle_close"],
            "reason": (
                "Run frozen before same-direction extension: live entry line "
                f"v{event.get('line_version')} touched at "
                f"{touch['touch_time'].isoformat(sep=' ', timespec='minutes')} "
                "before candidate candle close "
                f"{touch['candidate_candle_close'].isoformat(sep=' ', timespec='minutes')}"
            ),
        }
        return True

    def append_live_entry_line_event(idx: int) -> None:
        run = state.run
        if not run or not run["has_setup"] or run["direction"] == 0:
            return

        side = "Buy" if run["direction"] == 1 else "Sell"
        trade_side = opposite_side(side) if params.reverse_trade_direction else side
        live_valid_base = run["count"] <= params.max_imbalance_candles and run["valid_imbalance"]
        obstacle_check = check_run_obstacles(
            side=side,
            run_obj=run,
            resistance_obstacles=resistance_obstacles,
            support_obstacles=support_obstacles,
            consolidation_obstacles=consolidation_obstacles,
            resistance_trendlines=resistance_trendlines if params.use_trendline_obstacles else None,
            support_trendlines=support_trendlines if params.use_trendline_obstacles else None,
            trendline_obstacle_size=trendline_obstacle_size,
        )
        obstacle_override, _ = obstacle_strength_override_details(rows, run, params, obstacle_check)
        obstacle_hit = obstacle_check.hit and not obstacle_override
        available_from = execution_available_from(rows[idx]["time"])

        if not live_valid_base or obstacle_hit:
            stop_latest_entry_line(run, available_from)
            return

        if params.use_news_filter and news_events:
            news_hits = run_news_invalidation_events(rows, run, signal_tf_minutes, news_events)
            if news_hits:
                run["news_blocked_events"] = merge_news_events(run.get("news_blocked_events", []), news_hits)
                stop_latest_entry_line(run, available_from)
                return

        entry = live_entry_price(run, params)
        levels = signal_entry_exit_levels(
            run | {"entry_frozen": True, "frozen_entry_price": entry},
            trade_side,
            params,
        )
        events = run.setdefault("entry_line_events", [])
        if events:
            events[-1]["active_until"] = min(events[-1]["active_until"], available_from)

        line_version = len(events) + 1
        setup_sources = setup_sources_text(run)
        buy_b_candidate = (
            params.use_buy_b_setup
            and side == "Buy"
            and buy_b_triggered(
                run_obj=run,
                valid_base=live_valid_base,
                obstacle_hit=False,
                buy_b_done=state.buy_b_done,
                asia_bull_confirmed=state.asia_bull_confirmed,
                ds_bull_confirmed=state.ds_bull_confirmed,
            )
        )
        if buy_b_candidate and not buy_b_asia_range_allowed(state, params):
            stop_latest_entry_line(run, available_from)
            return

        buy_b = buy_b_candidate
        sell_b = (
            params.use_sell_b_setup
            and side == "Sell"
            and sell_b_triggered(
                run_obj=run,
                valid_base=live_valid_base,
                obstacle_hit=False,
                sell_b_done=state.sell_b_done,
                asia_bear_confirmed=state.asia_bear_confirmed,
                ds_bear_confirmed=state.ds_bear_confirmed,
            )
        )
        setup_type = "Buy B" if buy_b else "Sell B" if sell_b else setup_sources
        expires_at = london_setup_end_utc_naive(available_from)
        events.append(
            {
                "line_version": line_version,
                "line_time": rows[idx]["time"],
                "available_from": available_from,
                "active_until": expires_at,
                "expires_at": expires_at,
                "entry": entry,
                "stop_loss": levels.stop_loss,
                "take_profit": levels.take_profit,
                "direction": trade_side,
                "signal_direction": side,
                "setup_type": setup_type,
                "signal_text": signal_text(run, side, buy_b, sell_b),
                "source_row": idx + 2,
                "run_count": run["count"],
                "run_high": run["high"],
                "run_low": run["low"],
                "run_wick_high": run["wick_high"],
                "run_wick_low": run["wick_low"],
                "largest_body_pips": run["largest_body_pips"],
            }
        )

    def finalize_run() -> None:
        run = state.run
        if not run or not run["has_setup"]:
            return

        side = "Buy" if run["direction"] == 1 else "Sell"
        context_side = opposite_side(side) if params.reverse_trade_direction else side
        valid_base = run["count"] <= params.max_imbalance_candles and run["valid_imbalance"]
        final_available_from = execution_available_from(rows[run["end_i"]]["time"])
        obstacle_check = check_run_obstacles(
            side=side,
            run_obj=run,
            resistance_obstacles=resistance_obstacles,
            support_obstacles=support_obstacles,
            consolidation_obstacles=consolidation_obstacles,
            resistance_trendlines=resistance_trendlines if params.use_trendline_obstacles else None,
            support_trendlines=support_trendlines if params.use_trendline_obstacles else None,
            trendline_obstacle_size=trendline_obstacle_size,
        )
        obstacle_override, obstacle_override_reason = obstacle_strength_override_details(
            rows,
            run,
            params,
            obstacle_check,
        )
        obstacle_hit = obstacle_check.hit and not obstacle_override
        news_hits = []
        if params.use_news_filter and news_events:
            news_hits = run_news_invalidation_events(rows, run, signal_tf_minutes, news_events)
            if news_hits:
                run["news_blocked_events"] = merge_news_events(run.get("news_blocked_events", []), news_hits)

        context_decision = (
            context_index.evaluate_run(run, context_side, context_row_offset)
            if context_index is not None
            else {}
        )
        context_blocked = bool(context_decision.get("context_filter_blocked"))

        reason_parts: list[str] = []
        if run["count"] > params.max_imbalance_candles:
            reason_parts.append(f"Too many candles: {run['count']}/{params.max_imbalance_candles}")
        if not run["valid_imbalance"]:
            reason_parts.append(f"Imb candle too small: {run['largest_body_pips']:.1f}p < {params.min_imbalance_pips:g}p")
        if obstacle_hit:
            reason_parts.extend(obstacle_check.reason_parts())
        if news_hits:
            reason_parts.append(news_block_reason(news_hits))
        if context_blocked:
            reason_parts.append(str(context_decision["context_filter_reason"]))

        buy_b = False
        buy_b_range_hit = False
        sell_b = False
        if params.use_buy_b_setup and valid_base and not obstacle_hit and side == "Buy":
            buy_b_candidate = buy_b_triggered(
                run_obj=run,
                valid_base=valid_base,
                obstacle_hit=obstacle_hit,
                buy_b_done=state.buy_b_done,
                asia_bull_confirmed=state.asia_bull_confirmed,
                ds_bull_confirmed=state.ds_bull_confirmed,
            )
            buy_b_range_hit = buy_b_candidate and not buy_b_asia_range_allowed(state, params)
            if buy_b_range_hit:
                reason_parts.append(buy_b_asia_range_reject_reason(state, params))
            buy_b = buy_b_candidate and not buy_b_range_hit
        if params.use_sell_b_setup and valid_base and not obstacle_hit and side == "Sell":
            sell_b = sell_b_triggered(
                run_obj=run,
                valid_base=valid_base,
                obstacle_hit=obstacle_hit,
                sell_b_done=state.sell_b_done,
                asia_bear_confirmed=state.asia_bear_confirmed,
                ds_bear_confirmed=state.ds_bear_confirmed,
            )

        setup_sources = setup_sources_text(run)
        entry_line_events = list(run.get("entry_line_events") or [])
        final_status = (
            "Valid"
            if valid_base
            and not obstacle_hit
            and not buy_b_range_hit
            and not news_hits
            and not context_blocked
            else "Invalid"
        )
        if final_status != "Valid":
            stop_latest_entry_line(run, final_available_from)
            entry_line_events = list(run.get("entry_line_events") or [])
            if news_hits or context_blocked:
                entry_line_events = []

        first_event = entry_line_events[0] if entry_line_events else None
        last_event = entry_line_events[-1] if entry_line_events else None
        signal_i = (
            (first_event["source_row"] - 2)
            if first_event is not None
            else run["first_valid_i"]
            if run["first_valid_i"] is not None
            else run["end_i"]
        )
        signal_time = rows[signal_i]["time"]
        execution_start_time = first_event["available_from"] if first_event else final_available_from
        signal_london_day = rows[signal_i]["london_date"]
        status = "Valid" if entry_line_events else "Invalid"
        duplicate_direction_signal = False
        if params.block_same_direction_after_first_signal_per_day and status == "Valid":
            seen_sides = first_signal_sides_by_london_day.get(signal_london_day, set())
            duplicate_direction_signal = side in seen_sides
            if duplicate_direction_signal:
                reason_parts.append("Same direction as first valid tradable signal of London day")
                final_status = "Invalid"
                stop_latest_entry_line(run, final_available_from)
                entry_line_events = []
                first_event = None
                last_event = None
                execution_start_time = final_available_from
                status = "Invalid"

        if not news_hits and not entry_line_events and run.get("news_blocked_events"):
            news_hits = list(run["news_blocked_events"])
            reason_parts.append(news_block_reason(news_hits))

        entry = None
        stop_loss = None
        take_profit = None
        if last_event:
            entry = last_event["entry"]
            stop_loss = last_event["stop_loss"]
            take_profit = last_event["take_profit"]

        reason = "OK"
        if status != "Valid":
            reason = "; ".join(reason_parts) if reason_parts else "No live entry line event"
        elif final_status != "Valid":
            final_reason = "; ".join(reason_parts) if reason_parts else "Final run invalid"
            reason = f"Live entry line valid; final run invalid: {final_reason}"
        elif obstacle_override:
            reason = f"OK; {obstacle_override_reason}"
        elif run.get("extension_freeze"):
            reason = f"OK; {run['extension_freeze']['reason']}"

        state.signals.append(
            {
                "signal_id": f"SIG_{len(state.signals) + 1:05d}",
                "source_row": signal_i + 2,
                "signal_time": signal_time,
                "execution_start_time": execution_start_time,
                "direction": last_event["direction"] if last_event else opposite_side(side) if params.reverse_trade_direction else side,
                "signal_direction": side,
                "setup_type": last_event["setup_type"] if last_event else "Buy B" if buy_b or buy_b_range_hit else "Sell B" if sell_b else setup_sources,
                "signal_text": last_event["signal_text"] if last_event and status == "Valid" else "",
                "status": status,
                "reason": reason,
                "final_status": final_status,
                "final_reason": "OK" if final_status == "Valid" else "; ".join(reason_parts),
                "run_start": run["start_i"] + 2,
                "run_end": run["end_i"] + 2,
                "run_count": run["count"],
                "run_high": run["high"],
                "run_low": run["low"],
                "run_wick_high": run["wick_high"],
                "run_wick_low": run["wick_low"],
                "largest_body_pips": run["largest_body_pips"],
                "entry": entry,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "entry_deadline": last_event["active_until"] if last_event else execution_start_time,
                "entry_frozen": False,
                "entry_line_events": entry_line_events,
                "obstacle_hit": obstacle_hit,
                "obstacle_override": obstacle_override,
                "obstacle_override_reason": obstacle_override_reason,
                "news_blocked": bool(news_hits),
                "news_event_ids": ", ".join(event.event_id for event in news_hits),
                "news_events": "; ".join(news_event_label(event) for event in news_hits),
                "extension_freeze": bool(run.get("extension_freeze")),
                "extension_freeze_reason": (run.get("extension_freeze") or {}).get("reason"),
                "extension_freeze_touch_time": (run.get("extension_freeze") or {}).get("touch_time"),
                "extension_freeze_candidate_time": (run.get("extension_freeze") or {}).get("candidate_candle_time"),
                "extension_freeze_line_version": (run.get("extension_freeze") or {}).get("line_version"),
                **context_decision,
            }
        )

        if (
            params.block_same_direction_after_first_signal_per_day
            and status == "Valid"
            and not duplicate_direction_signal
        ):
            first_signal_sides_by_london_day.setdefault(signal_london_day, set()).add(side)

        if final_status == "Valid":
            state.mark_valid_setup_confirmations(side, run)
            state.mark_buy_sell_b(buy_b, sell_b)

    for i, row in enumerate(rows):
        prev = rows[i - 1] if i > 0 else None
        sessions = session_flags(
            london_timestamp=row["london_time"],
            previous_london_date=prev["london_date"] if prev else None,
            previous_in_asia=state.previous_in_asia,
            previous_in_london_setup=state.previous_in_london_setup,
        )

        if sessions.new_london_day:
            state.reset_new_london_day()
            state.clear_run()
        if sessions.london_setup_start:
            state.reset_london_setup()

        if params.use_pivot_obstacles:
            deactivate_pivot_obstacles(row, resistance_obstacles, support_obstacles)

        if pivot_high_confirmed[i]:
            pivot_i = i - params.right_bars
            if pivot_i >= 0:
                pivot_high = rows[pivot_i]["buy_body_high"]
                if sessions.in_daily_swing and rows[pivot_i]["london_date"] == row["london_date"]:
                    state.update_daily_swing_high(pivot_high)
                if params.use_pivot_obstacles:
                    add_pivot_obstacle(resistance_obstacles, rows, i, params.right_bars, "res")
        if pivot_low_confirmed[i]:
            pivot_i = i - params.right_bars
            if pivot_i >= 0:
                pivot_low = rows[pivot_i]["sell_body_low"]
                if sessions.in_daily_swing and rows[pivot_i]["london_date"] == row["london_date"]:
                    state.update_daily_swing_low(pivot_low)
                if params.use_pivot_obstacles:
                    add_pivot_obstacle(support_obstacles, rows, i, params.right_bars, "sup")

        if params.use_trendline_obstacles:
            if pivot_high_confirmed[i]:
                add_resistance_trendlines(
                    resistance_trendlines,
                    trendline_pivot_highs,
                    rows,
                    i,
                    params.right_bars,
                    trendline_validation_tolerance,
                )
            if pivot_low_confirmed[i]:
                add_support_trendlines(
                    support_trendlines,
                    trendline_pivot_lows,
                    rows,
                    i,
                    params.right_bars,
                    trendline_validation_tolerance,
                )
            deactivate_trendline_obstacles(
                row,
                i,
                resistance_trendlines,
                support_trendlines,
                trendline_validation_tolerance,
            )

        if sessions.asia_start:
            state.start_asia_session(row)
        elif sessions.in_asia:
            state.extend_asia_session(row)

        maybe_create_pre_london_observation_pivot(state, prev, row, structure_break, setup_break)
        if sessions.london_time.time() < LONDON_SETUP_START:
            state.consume_pre_london_daily_swing_reaches(row)

        consolidation = consolidation_snapshot(
            rows=rows,
            idx=i,
            bars_required=bars_required,
            max_range=max_range,
            similar_tolerance=similar_tolerance,
            similar_level_min_spacing=params.similar_level_min_spacing,
        )
        consol_high = consolidation.high
        consol_low = consolidation.low

        state.reset_consolidation_if_not_ready(consolidation.ready)

        bull = row["direction"] == 1
        bear = row["direction"] == -1
        prev_buy_body_high = prev["buy_body_high"] if prev else None
        prev_sell_body_low = prev["sell_body_low"] if prev else None
        prev_buy_close = prev["mid_close"] if prev else None
        prev_sell_close = prev["mid_close"] if prev else None

        asia_break = asia_break_flags(
            row=row,
            bull=bull,
            bear=bear,
            asia_high=state.asia_high,
            asia_low=state.asia_low,
            asia_bull_done=state.asia_bull_done,
            asia_bear_done=state.asia_bear_done,
            prev_buy_body_high=prev_buy_body_high,
            prev_sell_body_low=prev_sell_body_low,
            structure_break=structure_break,
            setup_break=setup_break,
        )
        asia_break = apply_pre_london_pivot_to_asia_break(
            flags=asia_break,
            state=state,
            row=row,
            bull=bull,
            bear=bear,
            prev_buy_body_high=prev_buy_body_high,
            prev_sell_body_low=prev_sell_body_low,
            structure_break=structure_break,
            setup_break=setup_break,
        )
        asia_break = apply_break_switches(
            asia_break,
            use_buy=params.use_asia_buy_setup,
            use_sell=params.use_asia_sell_setup,
        )

        daily_swing_break = daily_swing_break_flags(
            row=row,
            bull=bull,
            bear=bear,
            daily_swing_high=state.daily_swing_high,
            daily_swing_low=state.daily_swing_low,
            ds_bull_done=state.ds_bull_done,
            ds_bear_done=state.ds_bear_done,
            prev_buy_body_high=prev_buy_body_high,
            prev_sell_body_low=prev_sell_body_low,
            structure_break=structure_break,
            setup_break=setup_break,
        )
        daily_swing_break = apply_break_switches(
            daily_swing_break,
            use_buy=params.use_daily_swing_buy_setup,
            use_sell=params.use_daily_swing_sell_setup,
        )

        internal_structure_break = BreakFlags(False, False, False, False)
        internal_buy_allowed = (
            params.use_internal_structure_buy_setup
            and internal_structure_asia_move_allowed_from_state(state, "Buy", params)
        )
        internal_sell_allowed = (
            params.use_internal_structure_sell_setup
            and internal_structure_asia_move_allowed_from_state(state, "Sell", params)
        )
        if internal_buy_allowed or internal_sell_allowed:
            internal_structure_break = internal_structure_break_flags(
                rows=rows,
                idx=i,
                bull=bull,
                bear=bear,
                prev_buy_body_high=prev_buy_body_high,
                prev_sell_body_low=prev_sell_body_low,
                lookback_bars=internal_structure_lookback_bars,
                level_tolerance=internal_structure_tolerance,
                min_touches=params.internal_structure_min_touches,
                min_spacing_bars=params.internal_structure_min_spacing_bars,
                max_shelf_body_range=internal_structure_max_range,
                structure_break=structure_break,
                setup_break=setup_break,
            )
            internal_structure_break = apply_break_switches(
                internal_structure_break,
                use_buy=internal_buy_allowed,
                use_sell=internal_sell_allowed,
            )
        else:
            internal_structure_break = BreakFlags(False, False, False, False)

        consolidation_break = consolidation_break_flags(
            row=row,
            bull=bull,
            bear=bear,
            snapshot=consolidation,
            consolidation_broken=state.consolidation_broken,
            prev_buy_close=prev_buy_close,
            prev_sell_close=prev_sell_close,
            structure_break=structure_break,
            setup_break=setup_break,
        )
        consolidation_break = apply_consolidation_switches(
            consolidation_break,
            use_buy=params.use_consolidation_buy_setup,
            use_sell=params.use_consolidation_sell_setup,
        )

        side_body_size = row["buy_body_size"] if bull else row["sell_body_size"] if bear else 0
        setup_body_valid = True if not params.use_imbalance_validation else side_body_size >= min_imbalance

        first_buy_locked, first_sell_locked = update_first_break_locks(
            in_london_setup=sessions.in_london_setup,
            first_buy_locked=state.first_buy_locked,
            first_sell_locked=state.first_sell_locked,
            asia=asia_break,
            daily_swing=daily_swing_break,
            consolidation=consolidation_break,
            internal_structure=internal_structure_break,
        )
        state.set_first_break_locks(first_buy_locked, first_sell_locked)
        signal_first_buy_locked = state.first_buy_locked or not params.use_first_london_break_filter
        signal_first_sell_locked = state.first_sell_locked or not params.use_first_london_break_filter
        signals_now = setup_signals(
            in_london_setup=sessions.in_london_setup,
            bull=bull,
            bear=bear,
            first_buy_locked=signal_first_buy_locked,
            first_sell_locked=signal_first_sell_locked,
            asia=asia_break,
            daily_swing=daily_swing_break,
            consolidation=consolidation_break,
            internal_structure=internal_structure_break,
        )
        asia_signal = signals_now.asia
        ds_signal = signals_now.daily_swing
        consol_signal = signals_now.consolidation
        internal_signal = signals_now.internal_structure
        if asia_signal:
            side = "Buy" if bull else "Sell"
            if (
                same_impulse_created_asia_extreme(rows, i, state.run, state, side)
                or prior_body_reached_a_run_extreme(rows, i, state.run, side, pip)
            ):
                asia_signal = False
        current_setup = bool(asia_signal or ds_signal or consol_signal or internal_signal)
        if sessions.in_london_setup:
            state.mark_asia_breaks(asia_break)
            state.mark_daily_swing_breaks(daily_swing_break)

        if (
            (consolidation_break.raw_buy_break or consolidation_break.raw_sell_break)
            and consol_high is not None
            and params.use_consolidation_obstacles
        ):
            add_consolidation_obstacle(
                consolidation_obstacles,
                top=consol_high,
                bottom=consol_low,
                created_idx=i,
            )
            state.consolidation_broken = True

        if params.use_consolidation_obstacles:
            update_consolidation_obstacles(row, consolidation_obstacles, i)

        if state.run and state.run["direction"] != 0 and row["direction"] != state.run["direction"]:
            finalize_run()
            state.clear_run()

        frozen_before_extension = False
        if state.run and state.run["direction"] != 0 and row["direction"] == state.run["direction"]:
            frozen_before_extension = maybe_freeze_run_before_extension(i, row)
            if frozen_before_extension:
                finalize_run()
                state.clear_run()

        if row["direction"] == 0:
            state.clear_run()
        else:
            state.upsert_run(
                idx=i,
                row=row,
                bull=bull,
                asia_signal=asia_signal,
                ds_signal=ds_signal,
                consol_signal=consol_signal,
                internal_signal=internal_signal,
                current_setup=current_setup,
                setup_body_valid=setup_body_valid,
                side_body_size=side_body_size,
                pip_size=pip,
            )

            append_live_entry_line_event(i)

        state.mark_previous_sessions(sessions.in_asia, sessions.in_london_setup)

    if state.run and state.run["has_setup"]:
        finalize_run()
    return state.signals


def apply_break_switches(flags: Any, use_buy: bool, use_sell: bool) -> Any:
    return replace_dataclass(
        flags,
        bull_break=bool(flags.bull_break and use_buy),
        bear_break=bool(flags.bear_break and use_sell),
        bull_setup=bool(flags.bull_setup and use_buy),
        bear_setup=bool(flags.bear_setup and use_sell),
    )


def apply_consolidation_switches(flags: Any, use_buy: bool, use_sell: bool) -> Any:
    return replace_dataclass(
        flags,
        buy_break=bool(flags.buy_break and use_buy),
        sell_break=bool(flags.sell_break and use_sell),
        buy_setup=bool(flags.buy_setup and use_buy),
        sell_setup=bool(flags.sell_setup and use_sell),
    )


def infer_timeframe_minutes(rows: list[dict[str, Any]]) -> float:
    deltas: dict[float, int] = {}
    for left, right in zip(rows, rows[1:]):
        minutes = (right["time"] - left["time"]).total_seconds() / 60
        if minutes > 0:
            deltas[minutes] = deltas.get(minutes, 0) + 1
    return max(deltas, key=deltas.get) if deltas else 15.0


def strategy_news_filter_config(params: StrategyParams) -> NewsFilterConfig:
    return NewsFilterConfig(
        currencies=params.news_currencies,
        impacts=params.news_impacts,
        minutes_before=params.news_blackout_minutes_before,
        minutes_after=params.news_blackout_minutes_after,
        source_timezone="UTC",
    )


def run_news_invalidation_events(
    rows: list[dict[str, Any]],
    run: dict[str, Any],
    signal_tf_minutes: float,
    news_events: list[Any],
) -> list[Any]:
    start_i = run.get("start_i")
    end_i = run.get("end_i")
    if start_i is None or end_i is None:
        return []
    run_start = rows[start_i]["time"]
    run_end = rows[end_i]["time"] + timedelta(minutes=signal_tf_minutes)
    return [
        event
        for event in news_events
        if run_start <= event.time_utc < run_end
    ]


def merge_news_events(existing: list[Any], incoming: list[Any]) -> list[Any]:
    merged = list(existing or [])
    seen = {getattr(event, "event_id", id(event)) for event in merged}
    for event in incoming:
        event_key = getattr(event, "event_id", id(event))
        if event_key in seen:
            continue
        seen.add(event_key)
        merged.append(event)
    return merged


def opposite_side(side: str) -> str:
    return "Sell" if side == "Buy" else "Buy"


def news_block_reason(events: list[Any]) -> str:
    labels = "; ".join(news_event_label(event) for event in events[:3])
    extra = f"; +{len(events) - 3} more" if len(events) > 3 else ""
    return f"News invalidation: imbalance run contains {labels}{extra}"


def news_event_label(event: Any) -> str:
    return f"{event.currency} {event.impact} {event.title} at {event.time_utc:%Y-%m-%d %H:%M} UTC"


def find_pivots(values: list[float], left: int, right: int, mode: str) -> list[bool]:
    out = [False] * len(values)
    for confirm_i in range(len(values)):
        pivot_i = confirm_i - right
        if pivot_i < left or pivot_i + right >= len(values):
            continue
        window = values[pivot_i - left:pivot_i + right + 1]
        if mode == "high" and values[pivot_i] == max(window):
            out[confirm_i] = True
        if mode == "low" and values[pivot_i] == min(window):
            out[confirm_i] = True
    return out


def body_high(open_: Any, close: Any) -> float:
    return max(float(open_), float(close))


def body_low(open_: Any, close: Any) -> float:
    return min(float(open_), float(close))


def candle_direction(open_: Any, close: Any) -> int:
    if float(close) > float(open_):
        return 1
    if float(close) < float(open_):
        return -1
    return 0
