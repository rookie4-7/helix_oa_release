from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeAlias


SampleType: TypeAlias = Literal["IS", "OOS"]
RunSample: TypeAlias = Literal["IS", "OOS", "Both"]
Timeframe: TypeAlias = Literal["1m", "15m"]
WorkbookRow: TypeAlias = dict[str, Any]
PriceRow: TypeAlias = dict[str, Any]
SignalRow: TypeAlias = dict[str, Any]
TradeRow: TypeAlias = dict[str, Any]


@dataclass(frozen=True)
class SelectedWindow:
    window_id: str
    is_start: Any
    is_end: Any
    oos_start: Any
    oos_end: Any
    oos_year: Any
    target_rule_version: str


@dataclass(frozen=True)
class PlannedRun:
    run_id: str
    sample_type: SampleType
    period_start: Any
    period_end: Any
    archive_dir: Path
    workbook_before_path: Path
    workbook_after_path: Path


@dataclass(frozen=True)
class PriceFile:
    symbol: str
    timeframe: Timeframe
    year: int
    path: Path
    sheet_name: str
    source_type: str


@dataclass(frozen=True)
class PriceFileStats:
    price_file: PriceFile
    exists: bool
    headers: list[str]
    rows: int
    start_time: Any
    end_time: Any
    missing_required_columns: list[str]
    duplicate_timestamps: int
    out_of_order_timestamps: int
    bad_bid_ask_rows: int
    negative_spread_rows: int
    rows_checked: int
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyParams:
    instrument: str = "GBP_USD"
    pip_size: float = 0.0001
    structure_break_pips: float = 0.1
    setup_break_pips: float = 2.0
    min_imbalance_pips: float = 5.0
    max_imbalance_candles: int = 5
    entry_retracement: float = 0.618
    entry_line_hours: float = 1.0
    left_bars: int = 5
    right_bars: int = 5
    min_consolidation_hours: float = 2.0
    max_consolidation_body_range_pips: float = 10.0
    similar_level_pips: float = 0.5
    similar_level_min_spacing: int = 2
    use_asia_buy_setup: bool = True
    use_asia_sell_setup: bool = True
    use_daily_swing_buy_setup: bool = True
    use_daily_swing_sell_setup: bool = True
    use_consolidation_buy_setup: bool = True
    use_consolidation_sell_setup: bool = True
    use_internal_structure_buy_setup: bool = False
    use_internal_structure_sell_setup: bool = False
    internal_structure_lookback_hours: float = 6.0
    internal_structure_level_tolerance_pips: float = 3.0
    internal_structure_min_touches: int = 2
    internal_structure_min_spacing_bars: int = 4
    internal_structure_max_shelf_body_range_pips: float = 60.0
    use_internal_structure_asia_move_filter: bool = True
    internal_structure_min_asia_body_move_pct: float = 0.7
    use_buy_b_setup: bool = True
    use_sell_b_setup: bool = True
    use_buy_b_asia_range_filter: bool = True
    buy_b_max_asia_body_range_pips: float = 50.0
    use_first_london_break_filter: bool = True
    use_imbalance_validation: bool = True
    use_pivot_obstacles: bool = True
    use_consolidation_obstacles: bool = True
    use_obstacle_strength_override: bool = True
    obstacle_override_min_run_range_ratio: float = 0.70
    obstacle_override_min_largest_body_pips: float = 12.0
    obstacle_override_require_setup_confluence: bool = True
    obstacle_override_apply_to_pivot: bool = True
    obstacle_override_apply_to_consolidation: bool = False
    use_trendline_obstacles: bool = False
    trendline_obstacle_pips: float = 1.0
    trendline_validation_tolerance_pips: float = 1.0
    use_adverse_asia_reversal_sell_filter: bool = False
    use_active_price_cluster_stop_filter: bool = False
    use_adverse_order_block_stop_filter: bool = False
    context_structure_confirm_bars: int = 5
    context_structure_break_buffer_pips: float = 0.1
    context_strong_move_min_net_pips: float = 35.0
    context_strong_move_min_pfe: float = 65.0
    context_strong_move_min_intervals: int = 4
    context_strong_move_max_intervals: int = 16
    context_strong_move_local_pivot_lookback_bars: int = 4
    context_strong_move_episode_max_bars: int = 4
    context_structural_tolerance_pips: float = 3.0
    context_order_block_gap_tolerance_pips: float = 3.0
    context_cluster_min_bars: int = 3
    context_cluster_max_body_width_pips: float = 10.0
    context_cluster_max_net_progress_pips: float = 5.0
    context_cluster_max_pfe: float = 50.0
    reverse_trade_direction: bool = False
    use_flexible_sl_tp: bool = False
    flexible_stop_fib_level: float = 1.025
    flexible_structure_buffer_pips: float = 2.9
    flexible_min_stop_loss_pips: float = 10.3
    flexible_max_stop_loss_pips: float = 14.9
    flexible_take_profit_r_multiple: float = 3.0
    fixed_stop_loss_pips: float = 12.5
    fixed_take_profit_pips: float = 37.5
    risk_per_trade: float = 0.01
    max_exit_bars_after_entry: int = 384
    use_midpoint_tp_protective_exit: bool = False
    midpoint_tp_protective_exit_r_multiple: float = 2.0
    execution_starts_after_signal_close: bool = True
    entry_fill_trigger_price_mode: str = "midpoint"
    block_same_direction_after_first_signal_per_day: bool = False
    block_same_direction_after_first_trade_per_day: bool = False
    only_first_filled_trade_per_day: bool = True
    force_close_at_18_london: bool = True
    use_news_filter: bool = True
    use_news_forced_close: bool = True
    news_forced_close_minutes_before: int = 15
    news_currencies: tuple[str, ...] = ("GBP", "USD")
    news_impacts: tuple[str, ...] = ("High",)
    news_blackout_minutes_before: int = 30
    news_blackout_minutes_after: int = 30
    news_source_timezone: str = "Europe/London"
    news_calendar_paths: tuple[str, ...] = ()
