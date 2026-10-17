"""Mark 3 strategy wired into the existing Excel backtest services."""
from runtime import load_shared
from config import ENGINE_VERSION, read_strategy_params
from pathlib import Path
from workbook_controls import preserve_runner_controls
from workbook_params import preserve_parameter_sheet

shared = load_shared("backtest_engine")
shared.ENGINE_VERSION = ENGINE_VERSION
shared.read_strategy_params = read_strategy_params
shared.KEY_STRATEGY_PARAM_NAMES += ("pivot_scales", "historical_pivot_lookback_bars",
    "reject_22_only_setups", "pivot_obstacle_scale", "pivot_obstacle_expiry_months",
    "price_cluster_expiry_months", "price_cluster_min_score", "price_cluster_candles",
    "price_cluster_reference_bars", "obstacle_context_start_year",
    "use_repeated_visit_pivot_exception", "repeated_visit_minimum_visits",
    "repeated_visit_membership_tolerance_pips", "repeated_visit_departure_pips")

def run_engine(args):
    if args.write and not args.output_workbook:
        raise shared.EngineError('Mark 3 requires --output-workbook to preserve the input workbook and its controls.')
    if args.write and Path(args.workbook).resolve() == Path(args.output_workbook).resolve():
        raise shared.EngineError('Mark 3 output must differ from the input workbook.')
    result = shared.run_engine(args)
    if args.write:
        source=Path(args.workbook).expanduser()
        if not source.is_absolute(): source=Path(args.project_root)/source
        preserve_runner_controls(source,args.output_workbook)
        preserve_parameter_sheet(source,args.output_workbook)
    return result
to_jsonable = shared.to_jsonable
EngineError = shared.EngineError
PriceDataError = shared.PriceDataError
NewsDataError = shared.NewsDataError
ExcelWriterError = shared.ExcelWriterError
WorkbookConfigError = shared.WorkbookConfigError

if __name__ == "__main__":
    import json
    args=shared.parse_args()
    print(json.dumps(run_engine(args),indent=2,default=to_jsonable))
