from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BreakFlags:
    bull_break: bool
    bear_break: bool
    bull_setup: bool
    bear_setup: bool


@dataclass(frozen=True)
class ConsolidationBreakFlags:
    raw_buy_break: bool
    raw_sell_break: bool
    buy_break: bool
    sell_break: bool
    buy_setup: bool
    sell_setup: bool


@dataclass(frozen=True)
class SetupSignals:
    asia: bool
    daily_swing: bool
    consolidation: bool
    internal_structure: bool

    @property
    def any_setup(self) -> bool:
        return self.asia or self.daily_swing or self.consolidation or self.internal_structure


def asia_break_flags(
    row: dict[str, Any],
    bull: bool,
    bear: bool,
    asia_high: float | None,
    asia_low: float | None,
    asia_bull_done: bool,
    asia_bear_done: bool,
    prev_buy_body_high: float | None,
    prev_sell_body_low: float | None,
    structure_break: float,
    setup_break: float,
) -> BreakFlags:
    bull_break = bool(
        bull
        and asia_high is not None
        and not asia_bull_done
        and row["buy_body_high"] > asia_high + structure_break
        and prev_buy_body_high is not None
        and prev_buy_body_high <= asia_high
    )
    bear_break = bool(
        bear
        and asia_low is not None
        and not asia_bear_done
        and row["sell_body_low"] < asia_low - structure_break
        and prev_sell_body_low is not None
        and prev_sell_body_low >= asia_low
    )
    return BreakFlags(
        bull_break=bull_break,
        bear_break=bear_break,
        bull_setup=bool(bull_break and asia_high is not None and row["buy_body_high"] > asia_high + setup_break),
        bear_setup=bool(bear_break and asia_low is not None and row["sell_body_low"] < asia_low - setup_break),
    )


def daily_swing_break_flags(
    row: dict[str, Any],
    bull: bool,
    bear: bool,
    daily_swing_high: float | None,
    daily_swing_low: float | None,
    ds_bull_done: bool,
    ds_bear_done: bool,
    prev_buy_body_high: float | None,
    prev_sell_body_low: float | None,
    structure_break: float,
    setup_break: float,
) -> BreakFlags:
    bull_break = bool(
        bull
        and daily_swing_high is not None
        and not ds_bull_done
        and row["buy_body_high"] > daily_swing_high + structure_break
        and prev_buy_body_high is not None
        and prev_buy_body_high <= daily_swing_high
    )
    bear_break = bool(
        bear
        and daily_swing_low is not None
        and not ds_bear_done
        and row["sell_body_low"] < daily_swing_low - structure_break
        and prev_sell_body_low is not None
        and prev_sell_body_low >= daily_swing_low
    )
    return BreakFlags(
        bull_break=bull_break,
        bear_break=bear_break,
        bull_setup=bool(
            bull_break
            and daily_swing_high is not None
            and row["buy_body_high"] > daily_swing_high + setup_break
        ),
        bear_setup=bool(
            bear_break
            and daily_swing_low is not None
            and row["sell_body_low"] < daily_swing_low - setup_break
        ),
    )


def internal_structure_break_flags(
    rows: list[dict[str, Any]],
    idx: int,
    bull: bool,
    bear: bool,
    prev_buy_body_high: float | None,
    prev_sell_body_low: float | None,
    lookback_bars: int,
    level_tolerance: float,
    min_touches: int,
    min_spacing_bars: int,
    max_shelf_body_range: float,
    structure_break: float,
    setup_break: float,
) -> BreakFlags:
    window = internal_structure_window(rows, idx, lookback_bars)
    buy_level = clustered_internal_level(
        window=window,
        mode="high",
        current_break_level=rows[idx]["buy_body_high"] if bull else None,
        tolerance=level_tolerance,
        min_touches=min_touches,
        min_spacing_bars=min_spacing_bars,
        max_shelf_body_range=max_shelf_body_range,
        break_distance=structure_break,
    )
    sell_level = clustered_internal_level(
        window=window,
        mode="low",
        current_break_level=rows[idx]["sell_body_low"] if bear else None,
        tolerance=level_tolerance,
        min_touches=min_touches,
        min_spacing_bars=min_spacing_bars,
        max_shelf_body_range=max_shelf_body_range,
        break_distance=structure_break,
    )
    bull_break = bool(
        bull
        and buy_level is not None
        and rows[idx]["buy_body_high"] > buy_level + structure_break
        and prev_buy_body_high is not None
        and prev_buy_body_high <= buy_level
    )
    bear_break = bool(
        bear
        and sell_level is not None
        and rows[idx]["sell_body_low"] < sell_level - structure_break
        and prev_sell_body_low is not None
        and prev_sell_body_low >= sell_level
    )
    return BreakFlags(
        bull_break=bull_break,
        bear_break=bear_break,
        bull_setup=bool(bull_break and buy_level is not None and rows[idx]["buy_body_high"] > buy_level + setup_break),
        bear_setup=bool(bear_break and sell_level is not None and rows[idx]["sell_body_low"] < sell_level - setup_break),
    )


def internal_structure_window(
    rows: list[dict[str, Any]],
    idx: int,
    lookback_bars: int,
) -> list[tuple[int, dict[str, Any]]]:
    if idx <= 0:
        return []
    current_date = rows[idx]["london_date"]
    start_idx = max(0, idx - lookback_bars)
    return [
        (row_idx, row)
        for row_idx, row in enumerate(rows[start_idx:idx], start=start_idx)
        if row["london_date"] == current_date
    ]


def clustered_internal_level(
    window: list[tuple[int, dict[str, Any]]],
    mode: str,
    current_break_level: float | None,
    tolerance: float,
    min_touches: int,
    min_spacing_bars: int,
    max_shelf_body_range: float,
    break_distance: float,
) -> float | None:
    if current_break_level is None or len(window) < min_touches:
        return None
    body_high = max(row["mid_body_high"] for _, row in window)
    body_low = min(row["mid_body_low"] for _, row in window)
    if body_high - body_low > max_shelf_body_range:
        return None

    if mode == "high":
        levels = sorted({row["buy_body_high"] for _, row in window}, reverse=True)
        for level in levels:
            if current_break_level <= level + break_distance:
                continue
            cluster = [
                row_idx
                for row_idx, row in window
                if abs(row["buy_body_high"] - level) <= tolerance
            ]
            if level_cluster_valid(cluster, min_touches, min_spacing_bars):
                return max(row["buy_body_high"] for _, row in window if abs(row["buy_body_high"] - level) <= tolerance)
        return None

    levels = sorted({row["sell_body_low"] for _, row in window})
    for level in levels:
        if current_break_level >= level - break_distance:
            continue
        cluster = [
            row_idx
            for row_idx, row in window
            if abs(row["sell_body_low"] - level) <= tolerance
        ]
        if level_cluster_valid(cluster, min_touches, min_spacing_bars):
            return min(row["sell_body_low"] for _, row in window if abs(row["sell_body_low"] - level) <= tolerance)
    return None


def level_cluster_valid(
    indexes: list[int],
    min_touches: int,
    min_spacing_bars: int,
) -> bool:
    return len(indexes) >= min_touches and (
        min_spacing_bars <= 0 or max(indexes) - min(indexes) >= min_spacing_bars
    )


def update_first_break_locks(
    in_london_setup: bool,
    first_buy_locked: bool,
    first_sell_locked: bool,
    asia: BreakFlags,
    daily_swing: BreakFlags,
    consolidation: ConsolidationBreakFlags,
    internal_structure: BreakFlags,
) -> tuple[bool, bool]:
    if in_london_setup and not first_buy_locked and (
        asia.bull_break or daily_swing.bull_break or consolidation.buy_break or internal_structure.bull_break
    ):
        first_buy_locked = True
    if in_london_setup and not first_sell_locked and (
        asia.bear_break or daily_swing.bear_break or consolidation.sell_break or internal_structure.bear_break
    ):
        first_sell_locked = True
    return first_buy_locked, first_sell_locked


def setup_signals(
    in_london_setup: bool,
    bull: bool,
    bear: bool,
    first_buy_locked: bool,
    first_sell_locked: bool,
    asia: BreakFlags,
    daily_swing: BreakFlags,
    consolidation: ConsolidationBreakFlags,
    internal_structure: BreakFlags,
) -> SetupSignals:
    return SetupSignals(
        asia=(
            (in_london_setup and first_buy_locked and asia.bull_setup)
            if bull
            else (in_london_setup and first_sell_locked and asia.bear_setup)
            if bear
            else False
        ),
        daily_swing=(
            (in_london_setup and first_buy_locked and daily_swing.bull_setup)
            if bull
            else (in_london_setup and first_sell_locked and daily_swing.bear_setup)
            if bear
            else False
        ),
        consolidation=(
            (in_london_setup and first_buy_locked and consolidation.buy_setup)
            if bull
            else (in_london_setup and first_sell_locked and consolidation.sell_setup)
            if bear
            else False
        ),
        internal_structure=(
            (in_london_setup and first_buy_locked and internal_structure.bull_setup)
            if bull
            else (in_london_setup and first_sell_locked and internal_structure.bear_setup)
            if bear
            else False
        ),
    )


def setup_sources_text(run_obj: dict[str, Any]) -> str:
    return "+".join(
        name
        for name, ok in [
            ("A", run_obj["asia"]),
            ("DS", run_obj["ds"]),
            ("Consol", run_obj["consol"]),
            ("IBOS", run_obj["internal"]),
        ]
        if ok
    )


def signal_text(run_obj: dict[str, Any], side: str, buy_b: bool, sell_b: bool) -> str:
    bits: list[str] = []
    if side == "Buy":
        if buy_b:
            bits.append("Buy B")
        else:
            if run_obj["asia_valid"]:
                bits.append("A Buy")
            if run_obj["ds_valid"]:
                bits.append("DS Buy")
            if run_obj["internal_valid"]:
                bits.append("IBOS Buy")
        if run_obj["consol_valid"]:
            bits.append("Consol.BUY")
    else:
        if sell_b:
            bits.append("Sell B")
        else:
            if run_obj["asia_valid"]:
                bits.append("A Sell")
            if run_obj["ds_valid"]:
                bits.append("DS Sell")
            if run_obj["internal_valid"]:
                bits.append("IBOS Sell")
        if run_obj["consol_valid"]:
            bits.append("Consol.SELL")
    return "+".join(bits)


def buy_b_triggered(
    run_obj: dict[str, Any],
    valid_base: bool,
    obstacle_hit: bool,
    buy_b_done: bool,
    asia_bull_confirmed: bool,
    ds_bull_confirmed: bool,
) -> bool:
    return bool(
        valid_base
        and not obstacle_hit
        and not buy_b_done
        and (
            (run_obj["asia_valid"] and run_obj["ds_valid"])
            or (run_obj["asia_valid"] and ds_bull_confirmed)
            or (run_obj["ds_valid"] and asia_bull_confirmed)
        )
    )


def sell_b_triggered(
    run_obj: dict[str, Any],
    valid_base: bool,
    obstacle_hit: bool,
    sell_b_done: bool,
    asia_bear_confirmed: bool,
    ds_bear_confirmed: bool,
) -> bool:
    return bool(
        valid_base
        and not obstacle_hit
        and not sell_b_done
        and (
            (run_obj["asia_valid"] and run_obj["ds_valid"])
            or (run_obj["asia_valid"] and ds_bear_confirmed)
            or (run_obj["ds_valid"] and asia_bear_confirmed)
        )
    )
