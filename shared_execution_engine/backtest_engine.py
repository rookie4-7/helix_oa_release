from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.workbook.properties import CalcProperties
from openpyxl.workbook.workbook import Workbook

from excel_writer import append_run_log_row
from excel_writer import append_trade_log_rows
from excel_writer import append_year_analysis_rows
from excel_writer import append_is_run_comparison_row
from excel_writer import append_is_run_review_row
from excel_writer import append_equity_curve_rows
from excel_writer import append_signal_audit_rows
from excel_writer import append_oos_result_review_row
from excel_writer import append_parameter_snapshot_row
from excel_writer import empty_run_log_rows
from excel_writer import empty_trade_log_rows
from excel_writer import empty_year_analysis_rows
from excel_writer import empty_is_run_comparison_rows
from excel_writer import empty_is_run_review_rows
from excel_writer import empty_equity_curve_rows
from excel_writer import empty_signal_audit_rows
from excel_writer import empty_oos_result_review_rows
from excel_writer import empty_parameter_snapshot_rows
from excel_writer import ensure_analysis_metric_columns
from excel_writer import ensure_default_signal_model
from excel_writer import ensure_trade_log_signal_columns
from excel_writer import ExcelWriterError
from excel_writer import next_run_ids
from excel_writer import write_data_catalog
from excel_writer import write_data_quality_report
from excel_writer import write_analysis_run_summary
from models import PlannedRun
from models import SelectedWindow
from models import StrategyParams
from news_loader import inspect_news_files
from news_loader import NewsDataError
from news_loader import news_stats_to_manifest_item
from price_data_loader import discover_price_files
from price_data_loader import inspect_price_files
from price_data_loader import PriceDataError
from price_data_loader import stats_to_manifest_item
from price_data_loader import years_between
from strategy_logic import run_strategy_for_period
from strategy_logic import strategy_config
from workbook_config import read_config
from workbook_config import read_rule_config
from workbook_config import read_strategy_params
from workbook_config import read_table
from workbook_config import require_sheets
from workbook_config import samples_to_run
from workbook_config import selected_window
from workbook_config import WorkbookConfigError


ENGINE_VERSION = "0.8.0"

KEY_STRATEGY_PARAM_NAMES = (
    "structure_break_pips",
    "setup_break_pips",
    "min_imbalance_pips",
    "max_imbalance_candles",
    "entry_retracement",
    "reverse_trade_direction",
    "use_flexible_sl_tp",
    "flexible_stop_fib_level",
    "flexible_structure_buffer_pips",
    "flexible_min_stop_loss_pips",
    "flexible_max_stop_loss_pips",
    "flexible_take_profit_r_multiple",
    "fixed_stop_loss_pips",
    "fixed_take_profit_pips",
    "use_midpoint_tp_protective_exit",
    "midpoint_tp_protective_exit_r_multiple",
    "execution_starts_after_signal_close",
    "entry_fill_trigger_price_mode",
    "use_asia_buy_setup",
    "use_asia_sell_setup",
    "use_daily_swing_buy_setup",
    "use_daily_swing_sell_setup",
    "use_consolidation_buy_setup",
    "use_consolidation_sell_setup",
    "use_internal_structure_buy_setup",
    "use_internal_structure_sell_setup",
    "internal_structure_lookback_hours",
    "internal_structure_level_tolerance_pips",
    "internal_structure_min_touches",
    "internal_structure_min_spacing_bars",
    "internal_structure_max_shelf_body_range_pips",
    "use_internal_structure_asia_move_filter",
    "internal_structure_min_asia_body_move_pct",
    "use_buy_b_setup",
    "use_sell_b_setup",
    "use_buy_b_asia_range_filter",
    "buy_b_max_asia_body_range_pips",
    "use_first_london_break_filter",
    "use_imbalance_validation",
    "use_pivot_obstacles",
    "use_consolidation_obstacles",
    "use_obstacle_strength_override",
    "obstacle_override_min_run_range_ratio",
    "obstacle_override_min_largest_body_pips",
    "obstacle_override_require_setup_confluence",
    "obstacle_override_apply_to_pivot",
    "obstacle_override_apply_to_consolidation",
    "use_trendline_obstacles",
    "trendline_obstacle_pips",
    "trendline_validation_tolerance_pips",
    "use_adverse_asia_reversal_sell_filter",
    "use_active_price_cluster_stop_filter",
    "use_adverse_order_block_stop_filter",
    "context_structure_confirm_bars",
    "context_structure_break_buffer_pips",
    "context_strong_move_min_net_pips",
    "context_strong_move_min_pfe",
    "context_strong_move_min_intervals",
    "context_strong_move_max_intervals",
    "context_strong_move_local_pivot_lookback_bars",
    "context_strong_move_episode_max_bars",
    "context_structural_tolerance_pips",
    "context_order_block_gap_tolerance_pips",
    "context_cluster_min_bars",
    "context_cluster_max_body_width_pips",
    "context_cluster_max_net_progress_pips",
    "context_cluster_max_pfe",
    "block_same_direction_after_first_signal_per_day",
    "block_same_direction_after_first_trade_per_day",
    "only_first_filled_trade_per_day",
    "force_close_at_18_london",
    "use_news_filter",
    "use_news_forced_close",
    "news_forced_close_minutes_before",
    "news_blackout_minutes_before",
    "news_blackout_minutes_after",
)


class EngineError(Exception):
    """Raised when the workbook cannot be used for a backtest run."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read the Excel backtest model and create audited backtest run records.",
    )
    parser.add_argument(
        "--workbook",
        default="outputs/backtest_model_v1/Backtest_Model_v1.xlsx",
        help="Path to the Excel backtest model.",
    )
    parser.add_argument(
        "--output-workbook",
        default=None,
        help="Optional output workbook path. With --write, the input workbook is copied here before editing.",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root used for relative archive paths.",
    )
    parser.add_argument(
        "--archive-root",
        default=None,
        help="Override archive folder. Defaults to Config Snapshot_Folder or archive/backtest_runs.",
    )
    parser.add_argument(
        "--window-id",
        default=None,
        help="Override Config Selected_Window_ID.",
    )
    parser.add_argument(
        "--sample",
        choices=["IS", "OOS", "Both"],
        default=None,
        help="Override Config Run_Sample.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write Run_Log rows and archive files. Default is a safe dry run.",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Mark generated run rows Active_For_Analysis = Yes.",
    )
    parser.add_argument(
        "--official-oos",
        action="store_true",
        help="Mark generated OOS run rows Official_OOS_Run = Yes.",
    )
    parser.add_argument(
        "--allow-empty-data",
        action="store_true",
        help="Allow --write even when Data_Catalog has no data files yet.",
    )
    parser.add_argument(
        "--hash-data-files",
        action="store_true",
        help="Calculate SHA256 for catalog files. Use carefully on large raw data files.",
    )
    parser.add_argument(
        "--price-data-root",
        default=None,
        help="Folder containing GBP_USD_M1_MBA and GBP_USD_M15_MBA_2015_2025_by_year.xlsx. Defaults to project root.",
    )
    parser.add_argument(
        "--validate-price-data",
        action="store_true",
        help="Open discovered price workbooks and validate headers/row metadata.",
    )
    parser.add_argument(
        "--scan-price-data",
        action="store_true",
        help="Scan discovered price rows for timestamp and bid/ask issues. Slower.",
    )
    parser.add_argument(
        "--max-scan-rows",
        type=int,
        default=None,
        help="Optional max rows to scan per discovered sheet when --scan-price-data is used.",
    )
    parser.add_argument(
        "--run-strategy",
        action="store_true",
        help="Run the Python strategy logic and write generated trades when used with --write.",
    )
    parser.add_argument(
        "--news-data-root",
        default=None,
        help="Folder containing the news calendar. Defaults to project root.",
    )
    parser.add_argument(
        "--disable-news-filter",
        action="store_true",
        help="Run strategy without news-caused imbalance invalidation.",
    )
    parser.add_argument(
        "--disable-news-forced-close",
        action="store_true",
        help="Run strategy without pre-news forced closes on open trades.",
    )
    parser.add_argument(
        "--news-source-timezone",
        default=None,
        help="Timezone for naive calendar times. Defaults to StrategyParams news_source_timezone.",
    )
    return parser.parse_args()


def load_local_env(project_root: Path) -> None:
    env_path = project_root / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=to_jsonable, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def key_params_text(strategy_config_payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for name in KEY_STRATEGY_PARAM_NAMES:
        value = strategy_config_payload.get(name)
        if isinstance(value, (list, tuple)):
            formatted = ",".join(str(item) for item in value)
        else:
            formatted = str(value)
        parts.append(f"{name}={formatted}")
        if name == "entry_retracement":
            parts.append("entry_line_expiry=12:00 Europe/London")
    return "; ".join(parts)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=to_jsonable) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not fieldnames:
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: to_jsonable(value) for key, value in row.items()})


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_data_manifest(
    workbook: Workbook,
    workbook_path: Path,
    project_root: Path,
    price_data_root: Path,
    selected: SelectedWindow,
    sample_types: list[str],
    hash_data_files: bool,
    validate_price_data: bool,
    scan_price_data: bool,
    max_scan_rows: int | None,
) -> dict[str, Any]:
    catalog_rows = read_table(workbook["Data_Catalog"], header_row=3, first_data_row=4, last_data_row=35)
    files: list[dict[str, Any]] = []

    if validate_price_data or scan_price_data:
        # Execution discovers these year sheets independently of the catalog.
        # Reinspect the actual inputs, not cached rows from an earlier window.
        years: set[int] = set()
        for sample_type in sample_types:
            start, end = ((selected.is_start, selected.is_end) if sample_type == "IS"
                          else (selected.oos_start, selected.oos_end))
            years.update(years_between(start, end))
        discovered_files = discover_price_files(price_data_root, years=sorted(years))
        stats = inspect_price_files(
            discovered_files, scan_rows=scan_price_data, max_scan_rows=max_scan_rows,
        )
        files = [stats_to_manifest_item(item, price_data_root) for item in stats]
        hashes: dict[str, str] = {}
        for item in files:
            if hash_data_files and item["exists"]:
                path = item["resolved_path"]
                if path not in hashes:
                    hashes[path] = sha256_file(Path(path))
                item["sha256"] = hashes[path]
        return {
            "workbook": str(workbook_path),
            "source": "validated_selected_price_files",
            "price_data_root": str(price_data_root),
            "files": files,
            "file_count": len(files),
        }

    for row in catalog_rows:
        file_path_value = row.get("File_Path")
        resolved_path: Path | None = None
        exists = False
        size_bytes: int | None = None
        file_sha256: str | None = None

        if file_path_value:
            candidate = Path(str(file_path_value)).expanduser()
            if not candidate.is_absolute():
                candidate = (project_root / candidate).resolve()
            resolved_path = candidate
            exists = candidate.exists()
            if exists and candidate.is_file():
                size_bytes = candidate.stat().st_size
                if hash_data_files:
                    file_sha256 = sha256_file(candidate)

        files.append(
            {
                "data_id": row.get("Data_ID"),
                "symbol": row.get("Symbol"),
                "timeframe": row.get("Timeframe"),
                "data_type": row.get("Data_Type"),
                "file_path": file_path_value,
                "resolved_path": str(resolved_path) if resolved_path else None,
                "file_format": row.get("File_Format"),
                "start_date": row.get("Start_Date"),
                "end_date": row.get("End_Date"),
                "rows": row.get("Rows"),
                "timezone": row.get("Timezone"),
                "data_version": row.get("Data_Version"),
                "checksum": row.get("Checksum"),
                "status": row.get("Status"),
                "exists": exists,
                "size_bytes": size_bytes,
                "sha256": file_sha256,
            }
        )

    if not files:
        years: set[int] = set()
        for sample_type in sample_types:
            if sample_type == "IS":
                years.update(years_between(selected.is_start, selected.is_end))
            else:
                years.update(years_between(selected.oos_start, selected.oos_end))

        discovered_files = discover_price_files(price_data_root, years=sorted(years))
        if validate_price_data or scan_price_data:
            stats = inspect_price_files(
                discovered_files,
                scan_rows=scan_price_data,
                max_scan_rows=max_scan_rows,
            )
            files = [stats_to_manifest_item(item, price_data_root) for item in stats]
        else:
            files = [
                {
                    "data_id": f"{item.symbol}_{item.timeframe}_{item.year}",
                    "symbol": item.symbol,
                    "timeframe": item.timeframe,
                    "year": item.year,
                    "data_type": "MBA",
                    "file_path": relative_to_root(item.path, price_data_root),
                    "resolved_path": str(item.path),
                    "file_format": "xlsx",
                    "sheet_name": item.sheet_name,
                    "source_type": item.source_type,
                    "start_date": None,
                    "end_date": None,
                    "rows": None,
                    "timezone": "UTC",
                    "data_version": f"{item.symbol}_{item.timeframe}_{item.year}",
                    "checksum": None,
                    "status": "Pending",
                    "exists": item.path.exists(),
                    "size_bytes": item.path.stat().st_size if item.path.exists() else None,
                    "headers": [],
                    "missing_required_columns": [],
                    "duplicate_timestamps": 0,
                    "out_of_order_timestamps": 0,
                    "bad_bid_ask_rows": 0,
                    "negative_spread_rows": 0,
                    "rows_checked": 0,
                }
                for item in discovered_files
            ]

    return {
        "workbook": str(workbook_path),
        "source": "Data_Catalog" if catalog_rows else "discovered_local_price_files",
        "price_data_root": str(price_data_root),
        "files": files,
        "file_count": len(files),
    }


def data_version_from_manifest(manifest: dict[str, Any]) -> str:
    versions = sorted(
        {
            str(item.get("data_version"))
            for item in manifest["files"]
            if item.get("data_version") not in (None, "")
        }
    )
    return "+".join(versions) if versions else "UNSET"


def read_news_manifest(news_data_root: Path, params: StrategyParams) -> dict[str, Any]:
    if not (params.use_news_filter or params.use_news_forced_close):
        return {
            "source": "disabled",
            "news_data_root": str(news_data_root),
            "files": [],
            "file_count": 0,
            "parsed_events": 0,
            "skipped_rows": 0,
            "currencies": [],
            "impacts": [],
            "blackout_minutes_before": params.news_blackout_minutes_before,
            "blackout_minutes_after": params.news_blackout_minutes_after,
            "forced_close_minutes_before": params.news_forced_close_minutes_before,
        }

    stats = inspect_news_files(
        news_data_root,
        paths=list(params.news_calendar_paths) if params.news_calendar_paths else None,
        source_timezone=params.news_source_timezone,
    )
    currencies = sorted({currency for item in stats for currency in item.currencies})
    impacts = sorted({impact for item in stats for impact in item.impacts})
    return {
        "source": "discovered_local_news_files",
        "news_data_root": str(news_data_root),
        "files": [news_stats_to_manifest_item(item, news_data_root) for item in stats],
        "file_count": len(stats),
        "parsed_events": sum(item.parsed_events for item in stats),
        "skipped_rows": sum(item.skipped_rows for item in stats),
        "currencies": currencies,
        "impacts": impacts,
        "filter_currencies": list(params.news_currencies),
        "filter_impacts": list(params.news_impacts),
        "blackout_minutes_before": params.news_blackout_minutes_before,
        "blackout_minutes_after": params.news_blackout_minutes_after,
        "forced_close_minutes_before": params.news_forced_close_minutes_before,
        "source_timezone": params.news_source_timezone,
    }


def resolve_archive_root(config: dict[str, Any], args: argparse.Namespace, project_root: Path) -> Path:
    configured = args.archive_root or config.get("Snapshot_Folder") or "archive/backtest_runs"
    archive_root = Path(str(configured)).expanduser()
    if not archive_root.is_absolute():
        archive_root = project_root / archive_root
    return archive_root.resolve()


def prepare_planned_runs(
    run_ids: list[str],
    selected: SelectedWindow,
    sample_types: list[str],
    archive_root: Path,
) -> list[PlannedRun]:
    planned: list[PlannedRun] = []
    for run_id, sample_type in zip(run_ids, sample_types):
        if sample_type == "IS":
            period_start = selected.is_start
            period_end = selected.is_end
        else:
            period_start = selected.oos_start
            period_end = selected.oos_end
        archive_dir = archive_root / run_id
        planned.append(
            PlannedRun(
                run_id=run_id,
                sample_type=sample_type,
                period_start=period_start,
                period_end=period_end,
                archive_dir=archive_dir,
                workbook_before_path=archive_dir / "workbook_before.xlsx",
                workbook_after_path=archive_dir / "workbook_after.xlsx",
            )
        )
    return planned


def selected_is_run_id_for_window(workbook: Workbook, window_id: str) -> str:
    rows = read_table(workbook["Walk_Forward"], header_row=3, first_data_row=4, last_data_row=11)
    for row in rows:
        if row.get("Window_ID") == window_id:
            return str(row.get("Selected_IS_Run_ID") or "")
    return ""


def copy_for_output(workbook_path: Path, output_workbook: str | None, write: bool) -> Path:
    if not output_workbook:
        return workbook_path
    output_path = Path(output_workbook).expanduser()
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    if write:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(workbook_path, output_path)
    return output_path.resolve()


def build_summary(
    workbook_path: Path,
    selected: SelectedWindow,
    sample_types: list[str],
    planned_runs: list[PlannedRun],
    manifest: dict[str, Any],
    news_manifest: dict[str, Any],
    rule_hash: str,
    engine_hash: str,
    strategy_params_hash: str,
    key_params: str,
    write: bool,
    strategy_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    files_by_timeframe: dict[str, int] = {}
    for item in manifest["files"]:
        timeframe = str(item.get("timeframe") or "unknown")
        files_by_timeframe[timeframe] = files_by_timeframe.get(timeframe, 0) + 1

    summary = {
        "mode": "write" if write else "dry-run",
        "workbook": str(workbook_path),
        "window_id": selected.window_id,
        "samples": sample_types,
        "planned_run_ids": [run.run_id for run in planned_runs],
        "periods": [
            {
                "run_id": run.run_id,
                "sample_type": run.sample_type,
                "period_start": run.period_start,
                "period_end": run.period_end,
                "archive_dir": str(run.archive_dir),
            }
            for run in planned_runs
        ],
        "data_source": manifest.get("source"),
        "price_data_root": manifest.get("price_data_root"),
        "data_file_count": manifest["file_count"],
        "data_files_by_timeframe": files_by_timeframe,
        "news_data_source": news_manifest.get("source"),
        "news_data_root": news_manifest.get("news_data_root"),
        "news_file_count": news_manifest.get("file_count", 0),
        "news_events_parsed": news_manifest.get("parsed_events", 0),
        "news_blackout_minutes_before": news_manifest.get("blackout_minutes_before"),
        "news_blackout_minutes_after": news_manifest.get("blackout_minutes_after"),
        "news_forced_close_minutes_before": news_manifest.get("forced_close_minutes_before"),
        "missing_data_files": [
            item.get("file_path")
            for item in manifest["files"]
            if item.get("file_path") and not item.get("exists")
        ],
        "missing_news_files": [
            item.get("file_path")
            for item in news_manifest.get("files", [])
            if item.get("file_path") and not item.get("exists")
        ],
        "failed_data_files": [
            {
                "data_id": item.get("data_id"),
                "missing_required_columns": item.get("missing_required_columns"),
                "bad_bid_ask_rows": item.get("bad_bid_ask_rows"),
                "negative_spread_rows": item.get("negative_spread_rows"),
                "out_of_order_timestamps": item.get("out_of_order_timestamps"),
                "duplicate_timestamps": item.get("duplicate_timestamps"),
            }
            for item in manifest["files"]
            if item.get("status") == "Failed"
            or item.get("missing_required_columns")
            or item.get("bad_bid_ask_rows")
            or item.get("negative_spread_rows")
            or item.get("out_of_order_timestamps")
            or item.get("duplicate_timestamps")
        ],
        "rule_config_hash": rule_hash,
        "engine_config_hash": engine_hash,
        "strategy_params_hash": strategy_params_hash,
        "key_params": key_params,
    }
    if strategy_results:
        summary["strategy"] = {
            run_id: result["summary"]
            for run_id, result in strategy_results.items()
        }
        summary["strategy_yearly"] = {
            run_id: result["yearly_summary"]
            for run_id, result in strategy_results.items()
        }
        summary["strategy_audit_counts"] = {
            run_id: {
                "equity_curve_points": len(result.get("equity_curve", [])),
                "signal_audit_rows": len(result.get("signal_audit", [])),
            }
            for run_id, result in strategy_results.items()
        }
    return summary


def run_engine(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).expanduser().resolve()
    load_local_env(project_root)
    price_data_root = Path(args.price_data_root or project_root).expanduser()
    if not price_data_root.is_absolute():
        price_data_root = (project_root / price_data_root).resolve()
    price_data_root = price_data_root.resolve()
    news_data_root = Path(args.news_data_root or project_root).expanduser()
    if not news_data_root.is_absolute():
        news_data_root = (project_root / news_data_root).resolve()
    news_data_root = news_data_root.resolve()

    workbook_path = Path(args.workbook).expanduser()
    if not workbook_path.is_absolute():
        workbook_path = (project_root / workbook_path).resolve()
    if not workbook_path.exists():
        raise EngineError(f"Workbook not found: {workbook_path}")

    working_workbook_path = copy_for_output(workbook_path, args.output_workbook, args.write)
    workbook = load_workbook(
        working_workbook_path,
        keep_vba=working_workbook_path.suffix.lower() in {".xlsm", ".xlam"},
    )
    require_sheets(workbook)
    ensure_default_signal_model(workbook["Signal_Model"])
    ensure_analysis_metric_columns(workbook)

    config = read_config(workbook["Config"])
    window_id = args.window_id or config.get("Selected_Window_ID")
    sample = args.sample or config.get("Run_Sample")
    if not window_id:
        raise EngineError("No selected window. Set Config Selected_Window_ID or pass --window-id.")
    if sample not in {"IS", "OOS", "Both"}:
        raise EngineError("No valid sample. Set Config Run_Sample to IS, OOS, or Both.")

    selected = selected_window(workbook, str(window_id))
    sample_types = samples_to_run(str(sample))
    archive_root = resolve_archive_root(config, args, project_root)
    rule_config = read_rule_config(workbook, config)
    strategy_params = read_strategy_params(workbook, StrategyParams())
    if args.disable_news_filter:
        strategy_params = replace(strategy_params, use_news_filter=False)
    if getattr(args, "disable_news_forced_close", False):
        strategy_params = replace(strategy_params, use_news_forced_close=False)
    if args.news_source_timezone:
        strategy_params = replace(strategy_params, news_source_timezone=args.news_source_timezone)
    strategy_config_payload = strategy_config(strategy_params)
    rule_config["python_strategy_config"] = strategy_config_payload
    strategy_params_hash = canonical_hash(strategy_config_payload)
    key_params = key_params_text(strategy_config_payload)
    data_manifest = read_data_manifest(
        workbook=workbook,
        workbook_path=working_workbook_path,
        project_root=project_root,
        price_data_root=price_data_root,
        selected=selected,
        sample_types=sample_types,
        hash_data_files=args.hash_data_files,
        validate_price_data=args.validate_price_data,
        scan_price_data=args.scan_price_data,
        max_scan_rows=args.max_scan_rows,
    )
    news_manifest = read_news_manifest(news_data_root, strategy_params)

    missing_data_files = [
        item.get("file_path")
        for item in data_manifest["files"]
        if item.get("file_path") and not item.get("exists")
    ]
    failed_data_files = [
        item.get("data_id")
        for item in data_manifest["files"]
        if item.get("status") == "Failed" or item.get("missing_required_columns")
    ]
    failed_news_files = [
        item.get("data_id")
        for item in news_manifest.get("files", [])
        if item.get("status") in {"Missing", "No Events"}
    ]

    if args.write and not data_manifest["files"] and not args.allow_empty_data:
        raise EngineError(
            "Data_Catalog has no data rows. Populate it first, or pass --allow-empty-data "
            "while testing the scaffold."
        )
    if args.write and missing_data_files and not args.allow_empty_data:
        raise EngineError(
            "Missing data files: "
            + ", ".join(str(item) for item in missing_data_files[:5])
            + (" ..." if len(missing_data_files) > 5 else "")
        )
    if args.write and failed_data_files and not args.allow_empty_data:
        raise EngineError(
            "Failed data validation for: "
            + ", ".join(str(item) for item in failed_data_files[:5])
            + (" ..." if len(failed_data_files) > 5 else "")
        )
    news_layer_enabled = strategy_params.use_news_filter or strategy_params.use_news_forced_close
    if args.write and news_layer_enabled and not news_manifest.get("files") and not args.allow_empty_data:
        raise EngineError(
            "A news layer is enabled but no news calendar files were found. "
            "Add news_calendar_2015_2025_clean.xlsx or disable news invalidation/forced close."
        )
    if args.write and news_layer_enabled and failed_news_files and not args.allow_empty_data:
        raise EngineError(
            "Failed news calendar validation for: "
            + ", ".join(str(item) for item in failed_news_files[:5])
            + (" ..." if len(failed_news_files) > 5 else "")
        )

    engine_config = {
        "engine_version": ENGINE_VERSION,
        "selected_mode": config.get("Selected_Mode"),
        "selected_window_id": str(window_id),
        "sample": str(sample),
        "activate": bool(args.activate),
        "official_oos": bool(args.official_oos),
        "archive_root": relative_to_root(archive_root, project_root),
        "price_data_root": relative_to_root(price_data_root, project_root),
        "news_data_root": relative_to_root(news_data_root, project_root),
        "validate_price_data": bool(args.validate_price_data),
        "scan_price_data": bool(args.scan_price_data),
        "max_scan_rows": args.max_scan_rows,
        "run_strategy": bool(args.run_strategy),
        "strategy_params_source": "Strategy_Params",
        "strategy_params_hash": strategy_params_hash,
        "use_news_filter": bool(strategy_params.use_news_filter),
        "use_news_forced_close": bool(strategy_params.use_news_forced_close),
        "news_source_timezone": strategy_params.news_source_timezone,
        "news_blackout_minutes_before": strategy_params.news_blackout_minutes_before,
        "news_blackout_minutes_after": strategy_params.news_blackout_minutes_after,
    }
    rule_hash = canonical_hash(rule_config)
    engine_hash = canonical_hash(engine_config)
    data_version = data_version_from_manifest(data_manifest)

    run_log = workbook["Run_Log"]
    run_ids = next_run_ids(run_log, len(sample_types))
    planned_runs = prepare_planned_runs(run_ids, selected, sample_types, archive_root)
    strategy_results: dict[str, Any] = {}
    if args.run_strategy:
        for planned in planned_runs:
            strategy_results[planned.run_id] = run_strategy_for_period(
                project_root=price_data_root,
                news_root=news_data_root,
                period_start=planned.period_start,
                period_end=planned.period_end,
                params=strategy_params,
            )

    summary = build_summary(
        workbook_path=working_workbook_path,
        selected=selected,
        sample_types=sample_types,
        planned_runs=planned_runs,
        manifest=data_manifest,
        news_manifest=news_manifest,
        rule_hash=rule_hash,
        engine_hash=engine_hash,
        strategy_params_hash=strategy_params_hash,
        key_params=key_params,
        write=args.write,
        strategy_results=strategy_results,
    )

    if not args.write:
        return summary

    empty_rows = empty_run_log_rows(run_log, len(planned_runs))
    now = datetime.now().replace(microsecond=0)

    for planned in planned_runs:
        planned.archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(working_workbook_path, planned.workbook_before_path)
        write_json(planned.archive_dir / "rule_config.json", rule_config)
        write_json(planned.archive_dir / "engine_config.json", engine_config)
        write_json(planned.archive_dir / "strategy_params.json", strategy_config_payload)
        write_json(planned.archive_dir / "data_manifest.json", data_manifest)
        write_json(planned.archive_dir / "news_manifest.json", news_manifest)
        if planned.run_id in strategy_results:
            result = strategy_results[planned.run_id]
            write_json(planned.archive_dir / "strategy_summary.json", result["summary"])
            write_json(planned.archive_dir / "strategy_yearly_summary.json", result["yearly_summary"])
            write_json(planned.archive_dir / "strategy_news_events.json", result["news_events"])
            write_json(planned.archive_dir / "strategy_signals.json", result["signals"])
            write_json(planned.archive_dir / "strategy_trades.json", result["trades"])
            write_json(planned.archive_dir / "strategy_equity_curve.json", result["equity_curve"])
            write_csv(planned.archive_dir / "strategy_equity_curve.csv", result["equity_curve"])
            write_json(planned.archive_dir / "strategy_signal_audit.json", result["signal_audit"])
            write_csv(planned.archive_dir / "strategy_signal_audit.csv", result["signal_audit"])

    for row_idx, planned in zip(empty_rows, planned_runs):
        strategy_summary = strategy_results.get(planned.run_id, {}).get("summary")
        run_message = (
            f"Strategy run complete: {strategy_summary['trades']} trades, "
            f"{strategy_summary['net_r']:.2f} net R."
            if strategy_summary
            else "Scaffold run created; strategy not executed."
        )
        append_run_log_row(
            sheet=run_log,
            row_idx=row_idx,
            planned=planned,
            selected=selected,
            config=config,
            rule_hash=rule_hash,
            engine_version=ENGINE_VERSION,
            engine_hash=engine_hash,
            data_version=data_version,
            project_root=project_root,
            now=now,
            activate=args.activate,
            official_oos=args.official_oos,
            run_message=run_message,
        )

    parameter_snapshot = workbook["Parameter_Snapshot"]
    parameter_rows = empty_parameter_snapshot_rows(parameter_snapshot, len(planned_runs))
    for row_idx, planned in zip(parameter_rows, planned_runs):
        append_parameter_snapshot_row(
            sheet=parameter_snapshot,
            row_idx=row_idx,
            planned=planned,
            selected=selected,
            config=config,
            rule_hash=rule_hash,
            engine_version=ENGINE_VERSION,
            engine_hash=engine_hash,
            data_version=data_version,
            strategy_params_hash=strategy_params_hash,
            key_params=key_params,
            project_root=project_root,
            now=now,
        )

    write_data_catalog(workbook["Data_Catalog"], data_manifest, now)
    write_data_quality_report(
        sheet=workbook["Data_Quality_Report"],
        manifest=data_manifest,
        run_id=planned_runs[0].run_id if planned_runs else "",
        engine_version=ENGINE_VERSION,
        project_root=project_root,
        now=now,
        manifest_path=planned_runs[0].archive_dir / "data_manifest.json" if planned_runs else None,
    )
    for planned in planned_runs:
        strategy_summary = strategy_results.get(planned.run_id, {}).get("summary")
        if planned.sample_type == "IS":
            write_analysis_run_summary(
                sheet=workbook["IS_Analysis"],
                planned=planned,
                selected=selected,
                config=config,
                engine_version=ENGINE_VERSION,
                data_version=data_version,
                summary=strategy_summary,
                activate=args.activate,
                official_oos=args.official_oos,
            )
        else:
            write_analysis_run_summary(
                sheet=workbook["OOS_Analysis"],
                planned=planned,
                selected=selected,
                config=config,
                engine_version=ENGINE_VERSION,
                data_version=data_version,
                summary=strategy_summary,
                activate=args.activate,
                official_oos=args.official_oos,
            )

    if args.run_strategy:
        trade_log = workbook["Trade_Log"]
        ensure_trade_log_signal_columns(trade_log)
        for planned in planned_runs:
            trades = strategy_results.get(planned.run_id, {}).get("trades", [])
            trade_rows = empty_trade_log_rows(trade_log, len(trades))
            append_trade_log_rows(
                sheet=trade_log,
                rows=trade_rows,
                trades=trades,
                planned=planned,
                selected=selected,
                config=config,
            )

        year_analysis = workbook["Year_Analysis"]
        for planned in planned_runs:
            yearly_summary = strategy_results.get(planned.run_id, {}).get("yearly_summary", {})
            year_rows = empty_year_analysis_rows(year_analysis, len(yearly_summary))
            append_year_analysis_rows(
                sheet=year_analysis,
                rows=year_rows,
                planned=planned,
                selected=selected,
                config=config,
                engine_version=ENGINE_VERSION,
                data_version=data_version,
                yearly_summary=yearly_summary,
                activate=args.activate,
                official_oos=args.official_oos,
            )

        equity_curve_sheet = workbook["Equity_Curve"]
        for planned in planned_runs:
            equity_curve = strategy_results.get(planned.run_id, {}).get("equity_curve", [])
            equity_rows = empty_equity_curve_rows(equity_curve_sheet, len(equity_curve))
            append_equity_curve_rows(
                sheet=equity_curve_sheet,
                rows=equity_rows,
                equity_curve=equity_curve,
                planned=planned,
                selected=selected,
            )

        signal_audit_sheet = workbook["Signal_Audit"]
        for planned in planned_runs:
            signal_audit = strategy_results.get(planned.run_id, {}).get("signal_audit", [])
            audit_rows = empty_signal_audit_rows(signal_audit_sheet, len(signal_audit))
            append_signal_audit_rows(
                sheet=signal_audit_sheet,
                rows=audit_rows,
                signal_audit=signal_audit,
                planned=planned,
                selected=selected,
            )

        is_runs = [planned for planned in planned_runs if planned.sample_type == "IS"]
        is_review = workbook["IS_Run_Review"]
        review_rows = empty_is_run_review_rows(is_review, len(is_runs))
        for row_idx, planned in zip(review_rows, is_runs):
            append_is_run_review_row(
                sheet=is_review,
                row_idx=row_idx,
                planned=planned,
                selected=selected,
                config=config,
                rule_hash=rule_hash,
                engine_hash=engine_hash,
                summary=strategy_results.get(planned.run_id, {}).get("summary"),
                yearly_summary=strategy_results.get(planned.run_id, {}).get("yearly_summary"),
                now=now,
            )

        is_comparison = workbook["IS_Run_Comparison"]
        comparison_rows = empty_is_run_comparison_rows(is_comparison, len(is_runs))
        for row_idx, planned in zip(comparison_rows, is_runs):
            append_is_run_comparison_row(
                sheet=is_comparison,
                row_idx=row_idx,
                planned=planned,
                selected=selected,
                config=config,
                rule_hash=rule_hash,
                engine_hash=engine_hash,
                data_version=data_version,
                summary=strategy_results.get(planned.run_id, {}).get("summary"),
                yearly_summary=strategy_results.get(planned.run_id, {}).get("yearly_summary"),
                now=now,
                activate=args.activate,
            )

        oos_runs = [planned for planned in planned_runs if planned.sample_type == "OOS"]
        linked_is_run_id = selected_is_run_id_for_window(workbook, selected.window_id) or next(
            (planned.run_id for planned in planned_runs if planned.sample_type == "IS"),
            "",
        )
        oos_review = workbook["OOS_Result_Review"]
        oos_review_rows = empty_oos_result_review_rows(oos_review, len(oos_runs))
        for row_idx, planned in zip(oos_review_rows, oos_runs):
            append_oos_result_review_row(
                sheet=oos_review,
                row_idx=row_idx,
                planned=planned,
                selected=selected,
                config=config,
                rule_hash=rule_hash,
                engine_hash=engine_hash,
                linked_is_run_id=linked_is_run_id,
                summary=strategy_results.get(planned.run_id, {}).get("summary"),
                yearly_summary=strategy_results.get(planned.run_id, {}).get("yearly_summary"),
                now=now,
                official_oos=args.official_oos,
            )

    if workbook.calculation is None:
        workbook.calculation = CalcProperties(calcMode="auto")
    workbook.calculation.calcMode = "auto"
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.save(working_workbook_path)

    for planned in planned_runs:
        shutil.copy2(working_workbook_path, planned.workbook_after_path)

    return summary


def main() -> int:
    args = parse_args()
    try:
        summary = run_engine(args)
    except (EngineError, PriceDataError, NewsDataError, ExcelWriterError, WorkbookConfigError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True, default=to_jsonable))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
