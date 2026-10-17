"""Mark 2 settings, with consolidation permanently removed."""
from dataclasses import asdict, dataclass, fields, replace

import runtime  # Sets the shared-service import path before importing models.
from models import StrategyParams
from workbook_config import WorkbookConfigError, parse_strategy_param_value, read_table

ENGINE_VERSION = "Mark2-0.2.0"
PROFILE = "MARK_2_CURRENT_ENGINE"


@dataclass(frozen=True)
class Mark2Params(StrategyParams):
    pivot_scales: tuple = (2, 3, 5)
    historical_pivot_lookback_bars: int = 1024
    structure_break_pips: float = 0.1
    setup_break_pips: float = 0.1
    min_imbalance_pips: float = 4.0
    max_imbalance_candles: int = 5
    use_consolidation_buy_setup: bool = False
    use_consolidation_sell_setup: bool = False
    use_consolidation_obstacles: bool = False
    use_pivot_obstacles: bool = True
    use_trendline_obstacles: bool = False
    use_active_price_cluster_stop_filter: bool = True
    reject_22_only_setups: bool = True
    pivot_obstacle_scale: int = 5
    pivot_obstacle_expiry_months: int = 0
    price_cluster_expiry_months: int = 0
    price_cluster_min_score: float = 50.0
    price_cluster_candles: int = 6
    price_cluster_reference_bars: int = 96
    obstacle_context_start_year: int = 2020
    use_adverse_order_block_stop_filter: bool = False
    use_adverse_asia_reversal_sell_filter: bool = False
    use_obstacle_strength_override: bool = False
    block_same_direction_after_first_signal_per_day: bool = False
    block_same_direction_after_first_trade_per_day: bool = False
    only_first_filled_trade_per_day: bool = False


REMOVED_SWITCHES = (
    "use_consolidation_buy_setup", "use_consolidation_sell_setup",
    "use_consolidation_obstacles", "use_trendline_obstacles",
    "use_adverse_order_block_stop_filter",
    "use_adverse_asia_reversal_sell_filter", "use_obstacle_strength_override",
)


def validate_params(params):
    unsupported = [name for name in REMOVED_SWITCHES if getattr(params, name)]
    if unsupported:
        raise WorkbookConfigError("Not supported in " + ENGINE_VERSION + ": " + ", ".join(unsupported))
    try:
        scales = tuple(sorted(set(int(x) for x in params.pivot_scales)))
    except (ValueError, TypeError) as exc:
        raise WorkbookConfigError("pivot_scales must contain positive whole numbers.") from exc
    if not scales or min(scales) < 1 or params.historical_pivot_lookback_bars < max(scales):
        raise WorkbookConfigError("Invalid pivot scales or historical lookback.")
    if params.structure_break_pips < 0 or params.setup_break_pips < params.structure_break_pips:
        raise WorkbookConfigError("Setup break must be at least the nonnegative structure break.")
    if params.max_imbalance_candles < 1 or params.min_imbalance_pips < 0:
        raise WorkbookConfigError("Invalid imbalance size or length.")
    if not params.execution_starts_after_signal_close:
        raise WorkbookConfigError("Mark 2 entries must start after signal close.")
    if params.pivot_obstacle_scale != 5:
        raise WorkbookConfigError("The frozen pivot obstacle setting is 5/5 only.")
    integers = ("pivot_obstacle_expiry_months", "price_cluster_expiry_months",
                "price_cluster_candles", "price_cluster_reference_bars", "obstacle_context_start_year")
    if any(type(getattr(params, name)) is not int for name in integers):
        raise WorkbookConfigError("Obstacle lengths and history year must be whole numbers.")
    if min(params.pivot_obstacle_expiry_months, params.price_cluster_expiry_months) < 0:
        raise WorkbookConfigError("Obstacle expiry must be nonnegative; 0 means no expiry.")
    if min(params.price_cluster_candles, params.price_cluster_reference_bars) < 2:
        raise WorkbookConfigError("Cluster window and reference need at least two candles.")
    if not 0 <= params.price_cluster_min_score <= 100 or params.obstacle_context_start_year < 1900:
        raise WorkbookConfigError("Invalid cluster cutoff or historical context year.")
    return replace(params, pivot_scales=scales)


def read_strategy_params(workbook, base=None):
    params = Mark2Params()
    names = {f.name for f in fields(params)}
    updates = {}
    for row in read_table(workbook["Strategy_Params"], header_row=3, first_data_row=4):
        name = str(row.get("Parameter") or "").strip()
        if not name:
            continue
        if name not in names:
            raise WorkbookConfigError("Unknown Mark 2 parameter: " + name)
        updates[name] = parse_strategy_param_value(name, row.get("Value"), getattr(params, name))
    return validate_params(replace(params, **updates))


def strategy_config(params):
    params = validate_params(params)
    return asdict(params) | {
        "engine_profile": PROFILE,
        "engine_version": ENGINE_VERSION,
        "rules_source": "Current engine vs BC engine Rule.docx; consolidation removed by user instruction",
        "historical_pivot_gate": "context only, never a setup; requires a same-direction current-day pivot break in the same run, before or simultaneously",
        "retracement_measurement": "consecutive directional candle bodies; original live-line freeze preserved",
        "ibos_pivot_requirement": "existing IBOS conditions plus a previously confirmed current-London-day body pivot broken in the same directional run during 08:00-12:00 London; neither condition alone authorises IBOS",
        "consolidation": "removed; never calculated, never a setup or obstacle",
        "context_filters": "Gate original candidate live lines without regenerating setups or extending original line lifetimes",
        "pivot_obstacle_definition": "5/5 confirmed body pivot; original side-specific sorted first/third open-close box and body-extreme cancellation",
        "price_cluster_definition": "Equal-weight overlap, compactness, slowness and back-and-forth; wick calculation, body box, score strictly above cutoff",
        "price_cluster_cancellation": "First later close above body-box high cancels resistance; below body-box low cancels support; permanent per direction",
        "obstacle_expiry": "0 months means no calendar expiry; structural cancellation still applies",
        "setup_22_rejection": "Actual setup sources only; retain independent Asia or an actual 3/3 or 5/5 setup pivot; never inspect incidental crossings or outcomes",
    }
