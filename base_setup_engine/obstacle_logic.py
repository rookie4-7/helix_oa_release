from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ObstacleCheck:
    buy_resistance_hit: bool
    sell_support_hit: bool
    buy_consolidation_hit: bool
    sell_consolidation_hit: bool
    buy_trendline_hit: bool = False
    sell_trendline_hit: bool = False

    @property
    def hit(self) -> bool:
        return (
            self.buy_resistance_hit
            or self.sell_support_hit
            or self.buy_consolidation_hit
            or self.sell_consolidation_hit
            or self.buy_trendline_hit
            or self.sell_trendline_hit
        )

    def reason_parts(self) -> list[str]:
        reasons: list[str] = []
        if self.buy_resistance_hit:
            reasons.append("Hit resistance obstacle")
        if self.sell_support_hit:
            reasons.append("Hit support obstacle")
        if self.buy_consolidation_hit or self.sell_consolidation_hit:
            reasons.append("Hit consolidation obstacle")
        if self.buy_trendline_hit or self.sell_trendline_hit:
            reasons.append("Hit trendline obstacle")
        return reasons


def check_run_obstacles(
    side: str,
    run_obj: dict[str, Any],
    resistance_obstacles: list[dict[str, Any]],
    support_obstacles: list[dict[str, Any]],
    consolidation_obstacles: list[dict[str, Any]],
    resistance_trendlines: list[dict[str, Any]] | None = None,
    support_trendlines: list[dict[str, Any]] | None = None,
    trendline_obstacle_size: float = 0.0,
) -> ObstacleCheck:
    buy_resistance_hit = side == "Buy" and any(
        ob["active"]
        and ob["created"] < run_obj["end_i"]
        and ob["bottom"] <= run_obj["high"] <= ob["top"]
        for ob in resistance_obstacles
    )
    sell_support_hit = side == "Sell" and any(
        ob["active"]
        and ob["created"] < run_obj["end_i"]
        and ob["bottom"] <= run_obj["low"] <= ob["top"]
        for ob in support_obstacles
    )
    buy_consolidation_hit = side == "Buy" and any(
        ob["active"]
        and run_obj["start_i"] > ob["created"]
        and ob["bottom"] <= run_obj["high"] <= ob["top"]
        for ob in consolidation_obstacles
    )
    sell_consolidation_hit = side == "Sell" and any(
        ob["active"]
        and run_obj["start_i"] > ob["created"]
        and ob["bottom"] <= run_obj["low"] <= ob["top"]
        for ob in consolidation_obstacles
    )
    buy_trendline_hit = side == "Buy" and any(
        trendline_hits_price(ob, run_obj["end_i"], run_obj["high"], trendline_obstacle_size)
        for ob in (resistance_trendlines or [])
    )
    sell_trendline_hit = side == "Sell" and any(
        trendline_hits_price(ob, run_obj["end_i"], run_obj["low"], trendline_obstacle_size)
        for ob in (support_trendlines or [])
    )
    return ObstacleCheck(
        buy_resistance_hit=buy_resistance_hit,
        sell_support_hit=sell_support_hit,
        buy_consolidation_hit=buy_consolidation_hit,
        sell_consolidation_hit=sell_consolidation_hit,
        buy_trendline_hit=buy_trendline_hit,
        sell_trendline_hit=sell_trendline_hit,
    )


def deactivate_pivot_obstacles(
    row: dict[str, Any],
    resistance_obstacles: list[dict[str, Any]],
    support_obstacles: list[dict[str, Any]],
) -> None:
    for ob in resistance_obstacles:
        if ob["active"] and row["buy_body_high"] > ob["top"]:
            ob["active"] = False
    for ob in support_obstacles:
        if ob["active"] and row["sell_body_low"] < ob["bottom"]:
            ob["active"] = False


def add_pivot_obstacle(
    obstacles: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    confirm_i: int,
    right_bars: int,
    side: str,
) -> None:
    zone = build_turn_zone(rows, confirm_i, right_bars, side)
    if not zone:
        return
    top, bottom = zone
    for ob in obstacles:
        if ob["active"] and same_zone(top, bottom, ob["top"], ob["bottom"]):
            return
    obstacles.append({"top": top, "bottom": bottom, "created": confirm_i, "active": True})


def build_turn_zone(
    rows: list[dict[str, Any]],
    confirm_i: int,
    right_bars: int,
    side: str,
) -> tuple[float, float] | None:
    pivot_i = confirm_i - right_bars
    if pivot_i < 0:
        return None

    left_i, right_i = pivot_forming_candle_indexes(rows, pivot_i, side)
    if left_i is None or right_i is None:
        return None

    prices = [
        rows[left_i]["mid_open"],
        rows[left_i]["mid_close"],
        rows[right_i]["mid_open"],
        rows[right_i]["mid_close"],
    ]
    if side == "res":
        ranked = sorted(prices, reverse=True)
        return ranked[0], ranked[2]

    ranked = sorted(prices)
    return ranked[2], ranked[0]


def pivot_forming_candle_indexes(
    rows: list[dict[str, Any]],
    pivot_i: int,
    side: str,
) -> tuple[int | None, int | None]:
    if pivot_i <= 0 or pivot_i >= len(rows):
        return None, None

    pivot_level = body_extreme(rows[pivot_i], side)
    left_i = pivot_i - 1
    while left_i >= 0 and body_extreme(rows[left_i], side) == pivot_level:
        left_i -= 1
    left_i += 1

    right_i = left_i + 1
    if right_i >= len(rows):
        return None, None

    return left_i, right_i


def body_extreme(row: dict[str, Any], side: str) -> float:
    return row["buy_body_high"] if side == "res" else row["sell_body_low"]


def same_zone(
    top: float,
    bottom: float,
    other_top: float,
    other_bottom: float,
) -> bool:
    return abs(top - other_top) < 1e-12 and abs(bottom - other_bottom) < 1e-12


def add_consolidation_obstacle(
    obstacles: list[dict[str, Any]],
    top: float,
    bottom: float,
    created_idx: int,
) -> None:
    obstacles.append(
        {
            "top": top,
            "bottom": bottom,
            "created": created_idx,
            "active": True,
            "above": False,
            "below": False,
        }
    )


def update_consolidation_obstacles(
    row: dict[str, Any],
    obstacles: list[dict[str, Any]],
    idx: int,
) -> None:
    for ob in obstacles:
        if not ob["active"] or idx <= ob["created"]:
            continue
        if row["buy_body_high"] >= ob["top"]:
            ob["above"] = True
        if row["sell_body_low"] <= ob["bottom"]:
            ob["below"] = True
        if ob["above"] and ob["below"]:
            ob["active"] = False


def trendline_price_at(
    x1: int,
    y1: float,
    x2: int,
    y2: float,
    x: int,
) -> float:
    return y2 if x2 == x1 else y1 + (y2 - y1) * (x - x1) / (x2 - x1)


def trendline_hits_price(
    trendline: dict[str, Any],
    idx: int,
    price: float,
    obstacle_size: float,
) -> bool:
    if not trendline.get("active", False):
        return False
    line_price = trendline_price_at(
        trendline["x1"],
        trendline["y1"],
        trendline["x2"],
        trendline["y2"],
        idx,
    )
    return line_price - obstacle_size <= price <= line_price + obstacle_size


def add_resistance_trendlines(
    trendlines: list[dict[str, Any]],
    active_pivots: list[tuple[int, float]],
    rows: list[dict[str, Any]],
    confirm_i: int,
    right_bars: int,
    validation_tolerance: float,
) -> None:
    current = trendline_high_pivot_point(rows, confirm_i, right_bars)
    if current is None:
        return

    current_i, current_price = current
    for prior_i, prior_price in active_pivots:
        if current_i > prior_i and resistance_trendline_clear(
            rows,
            prior_i,
            prior_price,
            current_i,
            current_price,
            validation_tolerance,
        ):
            trendlines.append(
                {
                    "x1": prior_i,
                    "y1": prior_price,
                    "x2": current_i,
                    "y2": current_price,
                    "created": confirm_i,
                    "active": True,
                }
            )

    active_pivots.append((current_i, current_price))
    if len(active_pivots) > 4:
        active_pivots.pop(0)
    deactivate_lines_using_inactive_pivots(trendlines, active_pivots)


def add_support_trendlines(
    trendlines: list[dict[str, Any]],
    active_pivots: list[tuple[int, float]],
    rows: list[dict[str, Any]],
    confirm_i: int,
    right_bars: int,
    validation_tolerance: float,
) -> None:
    current = trendline_low_pivot_point(rows, confirm_i, right_bars)
    if current is None:
        return

    current_i, current_price = current
    for prior_i, prior_price in active_pivots:
        if current_i > prior_i and support_trendline_clear(
            rows,
            prior_i,
            prior_price,
            current_i,
            current_price,
            validation_tolerance,
        ):
            trendlines.append(
                {
                    "x1": prior_i,
                    "y1": prior_price,
                    "x2": current_i,
                    "y2": current_price,
                    "created": confirm_i,
                    "active": True,
                }
            )

    active_pivots.append((current_i, current_price))
    if len(active_pivots) > 4:
        active_pivots.pop(0)
    deactivate_lines_using_inactive_pivots(trendlines, active_pivots)


def trendline_high_pivot_point(
    rows: list[dict[str, Any]],
    confirm_i: int,
    right_bars: int,
) -> tuple[int, float] | None:
    pivot_i = confirm_i - right_bars
    if pivot_i < 0:
        return None

    older_offset = first_offset_with_direction(rows, confirm_i, range(right_bars, right_bars + 4), 1)
    newer_offset = first_offset_with_direction(rows, confirm_i, range(right_bars, right_bars - 4, -1), -1)
    if older_offset is None or newer_offset is None or older_offset <= newer_offset:
        pivot_is_bull = rows[pivot_i]["mid_close"] > rows[pivot_i]["mid_open"]
        older_offset = right_bars if pivot_is_bull else right_bars + 1 if confirm_i - right_bars - 1 >= 0 else confirm_i
        newer_offset = max(right_bars - 1, 0) if pivot_is_bull else right_bars
    if older_offset <= newer_offset:
        return None

    older_i = confirm_i - older_offset
    newer_i = confirm_i - newer_offset
    if older_i < 0 or newer_i < 0:
        return None

    older_price = max(rows[older_i]["mid_open"], rows[older_i]["mid_close"])
    newer_price = max(rows[newer_i]["mid_open"], rows[newer_i]["mid_close"])
    price = max(older_price, newer_price)
    pivot_point_i = newer_i if newer_price == price else older_i
    return pivot_point_i, price


def trendline_low_pivot_point(
    rows: list[dict[str, Any]],
    confirm_i: int,
    right_bars: int,
) -> tuple[int, float] | None:
    pivot_i = confirm_i - right_bars
    if pivot_i < 0:
        return None

    older_offset = first_offset_with_direction(rows, confirm_i, range(right_bars, right_bars + 4), -1)
    newer_offset = first_offset_with_direction(rows, confirm_i, range(right_bars, right_bars - 4, -1), 1)
    if older_offset is None or newer_offset is None or older_offset <= newer_offset:
        pivot_is_bear = rows[pivot_i]["mid_close"] < rows[pivot_i]["mid_open"]
        older_offset = right_bars if pivot_is_bear else right_bars + 1 if confirm_i - right_bars - 1 >= 0 else confirm_i
        newer_offset = max(right_bars - 1, 0) if pivot_is_bear else right_bars
    if older_offset <= newer_offset:
        return None

    older_i = confirm_i - older_offset
    newer_i = confirm_i - newer_offset
    if older_i < 0 or newer_i < 0:
        return None

    older_price = min(rows[older_i]["mid_open"], rows[older_i]["mid_close"])
    newer_price = min(rows[newer_i]["mid_open"], rows[newer_i]["mid_close"])
    price = min(older_price, newer_price)
    pivot_point_i = newer_i if newer_price == price else older_i
    return pivot_point_i, price


def first_offset_with_direction(
    rows: list[dict[str, Any]],
    confirm_i: int,
    offsets: range,
    direction: int,
) -> int | None:
    for offset in offsets:
        idx = confirm_i - offset
        if offset < 0 or idx < 0:
            continue
        row_direction = 1 if rows[idx]["mid_close"] > rows[idx]["mid_open"] else -1 if rows[idx]["mid_close"] < rows[idx]["mid_open"] else 0
        if row_direction == direction:
            return offset
    return None


def resistance_trendline_clear(
    rows: list[dict[str, Any]],
    prior_i: int,
    prior_price: float,
    current_i: int,
    current_price: float,
    validation_tolerance: float,
) -> bool:
    for test_i in range(prior_i + 1, current_i):
        line_price = trendline_price_at(prior_i, prior_price, current_i, current_price, test_i)
        if rows[test_i]["mid_body_high"] > line_price + validation_tolerance:
            return False
    return True


def support_trendline_clear(
    rows: list[dict[str, Any]],
    prior_i: int,
    prior_price: float,
    current_i: int,
    current_price: float,
    validation_tolerance: float,
) -> bool:
    for test_i in range(prior_i + 1, current_i):
        line_price = trendline_price_at(prior_i, prior_price, current_i, current_price, test_i)
        if rows[test_i]["mid_body_low"] < line_price - validation_tolerance:
            return False
    return True


def deactivate_lines_using_inactive_pivots(
    trendlines: list[dict[str, Any]],
    active_pivots: list[tuple[int, float]],
) -> None:
    active_indexes = {idx for idx, _ in active_pivots}
    for line in trendlines:
        if line["active"] and (line["x1"] not in active_indexes or line["x2"] not in active_indexes):
            line["active"] = False


def deactivate_trendline_obstacles(
    row: dict[str, Any],
    idx: int,
    resistance_trendlines: list[dict[str, Any]],
    support_trendlines: list[dict[str, Any]],
    validation_tolerance: float,
) -> None:
    for line in resistance_trendlines:
        if not line["active"]:
            continue
        line_price = trendline_price_at(line["x1"], line["y1"], line["x2"], line["y2"], idx)
        if row["mid_body_high"] > line_price + validation_tolerance:
            line["active"] = False
    for line in support_trendlines:
        if not line["active"]:
            continue
        line_price = trendline_price_at(line["x1"], line["y1"], line["x2"], line["y2"], idx)
        if row["mid_body_low"] < line_price - validation_tolerance:
            line["active"] = False
