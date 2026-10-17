"""Mark 4: Mark 3 setup rules plus cluster-qualified original trendlines."""
from dataclasses import asdict, dataclass, fields, replace

import runtime  # Sets the shared-service import path before importing models.
import math
from models import StrategyParams
from workbook_config import WorkbookConfigError, parse_strategy_param_value, read_table

ENGINE_VERSION = "Mark4-0.1.0"
PROFILE = "MARK_4_CURRENT_ENGINE"


@dataclass(frozen=True)
class Mark4Params(StrategyParams):
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
    use_trendline_obstacles: bool = True
    use_trendline_cluster_score_filter: bool = True
    trendline_trade_side_oldest_local_min_score: float = 70.0
    trendline_trade_side_latest_local_min_score: float = 65.0
    trendline_opposite_side_latest_trailing_min_score: float = 50.0
    use_active_price_cluster_stop_filter: bool = True
    reject_22_only_setups: bool = True
    pivot_obstacle_scale: int = 5
    pivot_obstacle_expiry_months: int = 24
    price_cluster_expiry_months: int = 24
    price_cluster_min_score: float = 50.0
    price_cluster_candles: int = 6
    price_cluster_reference_bars: int = 96
    obstacle_context_start_year: int = 2020
    use_repeated_visit_pivot_exception: bool = True
    repeated_visit_minimum_visits: int = 3
    repeated_visit_membership_tolerance_pips: float = 4.0
    repeated_visit_departure_pips: float = 5.0
    use_adverse_order_block_stop_filter: bool = False
    use_adverse_asia_reversal_sell_filter: bool = False
    use_obstacle_strength_override: bool = False
    block_same_direction_after_first_signal_per_day: bool = False
    block_same_direction_after_first_trade_per_day: bool = False
    only_first_filled_trade_per_day: bool = False


REMOVED_SWITCHES = (
    "use_consolidation_buy_setup", "use_consolidation_sell_setup",
    "use_consolidation_obstacles",
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
    if type(params.use_repeated_visit_pivot_exception) is not bool:
        raise WorkbookConfigError("Repeated-visit exception must be Yes/No.")
    if type(params.repeated_visit_minimum_visits) is not int or params.repeated_visit_minimum_visits < 2:
        raise WorkbookConfigError("Repeated visits must be a whole number of at least two.")
    for name in ("repeated_visit_membership_tolerance_pips", "repeated_visit_departure_pips"):
        value = getattr(params, name)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise WorkbookConfigError("Repeated-visit distances must be finite and nonnegative.")
    for name in ("use_trendline_obstacles", "use_trendline_cluster_score_filter"):
        if type(getattr(params, name)) is not bool:
            raise WorkbookConfigError("Trendline switches must be Yes/No.")
    for name in ("trendline_trade_side_oldest_local_min_score",
                 "trendline_trade_side_latest_local_min_score",
                 "trendline_opposite_side_latest_trailing_min_score"):
        value = getattr(params, name)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
            raise WorkbookConfigError("Trendline cluster-score cutoffs must be finite numbers from 0 to 100.")
    for name in ("trendline_obstacle_pips", "trendline_validation_tolerance_pips"):
        value = getattr(params, name)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise WorkbookConfigError("Trendline distances must be finite and nonnegative.")
    return replace(params, pivot_scales=scales)


def read_strategy_params(workbook, base=None):
    params = Mark4Params()
    names = {f.name for f in fields(params)}
    updates = {}
    for row in read_table(workbook["Strategy_Params"], header_row=3, first_data_row=4):
        name = str(row.get("Parameter") or "").strip()
        if not name:
            continue
        if name not in names:
            raise WorkbookConfigError("Unknown Mark 4 parameter: " + name)
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
        "pivot_registration": "Consecutive M15 candles sharing a body extreme at previous close = next open are one pivot, timestamped on the first candle; highs and lows separate; per-scale actual confirmation windows preserved; separate returns and gaps are not merged",
        "ibos_pivot_requirement": "existing IBOS conditions plus a previously confirmed current-London-day body pivot broken in the same directional run during 08:00-12:00 London; neither condition alone authorises IBOS",
        "consolidation": "removed; never calculated, never a setup or obstacle",
        "context_filters": "Gate original candidate live lines without regenerating setups or extending original line lifetimes",
        "pivot_obstacle_definition": "5/5 confirmed body pivot; original side-specific sorted first/third open-close box and body-extreme cancellation",
        "price_cluster_definition": "Equal-weight overlap, compactness, slowness and back-and-forth; wick calculation, body box, score strictly above cutoff",
        "price_cluster_cancellation": "First later close above body-box high cancels resistance; below body-box low cancels support; permanent per direction",
        "obstacle_expiry": "Calendar months from confirmation close, inactive at the expiry boundary; 0 disables calendar expiry; structural cancellation still applies",
        "repeated_visit_pivot_exception": "Actual confirmed current-day setup pivot must be a member of a completed departed visit before the break candle opens; at least minimum_visits such visits; intact before the break; first clean close-through in the same imbalance run by line availability. Ignore pivots only, never clusters or 2/2-only rejection. No SD gate or separate repeated-structure age expiry.",
        "setup_22_rejection": "Actual setup sources only; retain independent Asia or an actual 3/3 or 5/5 setup pivot; never inspect incidental crossings or outcomes",
        "trendline_obstacle_definition": "Original two-pivot resistance for buys/support for sells; original validation, four-anchor retention, body-break cancellation and annual reset. Evaluate the completed run body extreme inside the projected line +/- half-width. No regression fitting or slope gate.",
        "trendline_cluster_score_gate": "Block an original trendline hit if trade-side oldest local score >70 OR trade-side latest local score >65 OR opposite-side latest trailing score >50, using the configured cutoffs. Latest three distinct confirmed 5/5 highs and lows before run start are score references only. Missing scores never qualify. Local windows contain the pivot candle and body price, complete by pivot confirmation. Trailing window ends at pivot candle. Wick-based Atlas calculation, body boxes, existing cluster window/reference settings. Pivot exceptions never waive trendlines.",
        "research_period": "Mark 4 development uses 2022-2024; these years are not untouched OOS for this rule. No independently validated alpha claim.",
    }
