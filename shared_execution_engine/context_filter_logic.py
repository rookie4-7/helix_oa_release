from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

try:
    from .market_sessions import ASIA_END
    from .market_sessions import ASIA_START
except ImportError:
    from market_sessions import ASIA_END
    from market_sessions import ASIA_START


@dataclass(frozen=True)
class StrongMove:
    move_id: str
    direction: str
    start_i: int
    end_i: int
    cluster_start_i: int
    cluster_end_i: int
    confirm_i: int
    abs_net_pips: float
    pfe: float


@dataclass(frozen=True)
class PriceCluster:
    cluster_id: str
    move_id: str
    move_direction: str
    move_confirm_i: int
    move_abs_net_pips: float
    move_pfe: float
    start_i: int
    end_i: int
    body_low: float
    body_high: float
    cancel_i: int | None = None


@dataclass(frozen=True)
class OrderBlock:
    order_block_id: str
    order_block_type: str
    source_move_id: str
    source_move_direction: str
    source_move_confirm_i: int
    source_move_abs_net_pips: float
    source_move_pfe: float
    pivot_i: int
    zone_low: float
    zone_high: float
    consumed_i: int | None = None


STOPPED_CLUSTER_INTERACTIONS = {
    "wick touched cluster",
    "body entered then closed back before cluster",
    "signal closed inside cluster",
    "wick broke far edge without clean close",
    "body entered cluster without terminal close classification",
}


def context_filters_enabled(params: Any) -> bool:
    return bool(
        params.use_adverse_asia_reversal_sell_filter
        or params.use_active_price_cluster_stop_filter
        or params.use_adverse_order_block_stop_filter
    )


def candle_direction(row: dict[str, Any]) -> int:
    open_price = float(row["mid_open"])
    close_price = float(row["mid_close"])
    return 1 if close_price > open_price else -1 if close_price < open_price else 0


def signed_pfe(rows: list[dict[str, Any]], trade_direction: int) -> float | None:
    if not rows:
        return None
    if len(rows) == 1:
        start = float(rows[0]["mid_open"])
        end = float(rows[0]["mid_close"])
        path = abs(end - start)
    else:
        closes = [float(row["mid_close"]) for row in rows]
        start = closes[0]
        end = closes[-1]
        path = sum(abs(right - left) for left, right in zip(closes, closes[1:]))
    if path <= 1e-12:
        return None
    return 100.0 * (end - start) / path * trade_direction


def detect_body_pivots(
    rows: list[dict[str, Any]],
    confirm_bars: int,
) -> list[dict[str, Any]]:
    if confirm_bars <= 0:
        raise ValueError("confirm_bars must be positive")
    highs = [float(row["mid_body_high"]) for row in rows]
    lows = [float(row["mid_body_low"]) for row in rows]
    pivots: list[dict[str, Any]] = []
    for i in range(confirm_bars, len(rows) - confirm_bars):
        high_window = highs[i - confirm_bars : i + confirm_bars + 1]
        low_window = lows[i - confirm_bars : i + confirm_bars + 1]
        if (
            highs[i] >= max(high_window) - 1e-12
            and not any(
                math.isclose(value, highs[i], abs_tol=1e-12)
                for value in highs[i + 1 : i + confirm_bars + 1]
            )
        ):
            pivots.append(
                {
                    "pivot_kind": "high",
                    "pivot_i": i,
                    "confirm_i": i + confirm_bars,
                    "pivot_level": highs[i],
                }
            )
        if (
            lows[i] <= min(low_window) + 1e-12
            and not any(
                math.isclose(value, lows[i], abs_tol=1e-12)
                for value in lows[i + 1 : i + confirm_bars + 1]
            )
        ):
            pivots.append(
                {
                    "pivot_kind": "low",
                    "pivot_i": i,
                    "confirm_i": i + confirm_bars,
                    "pivot_level": lows[i],
                }
            )
    pivots.sort(key=lambda row: (row["confirm_i"], row["pivot_i"], row["pivot_kind"]))
    for number, pivot in enumerate(pivots):
        pivot["pivot_id"] = f"BP_{number:06d}"
    return pivots


def _latest_unbroken(
    heap: list[tuple[int, str]],
    broken_ids: set[str],
    pivot_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    while heap and heap[0][1] in broken_ids:
        heapq.heappop(heap)
    return pivot_by_id[heap[0][1]] if heap else None


def build_protected_structure_timeline(
    rows: list[dict[str, Any]],
    confirm_bars: int,
    break_buffer_pips: float,
    pip_size: float,
) -> list[int]:
    pivots = detect_body_pivots(rows, confirm_bars)
    by_id = {str(row["pivot_id"]): row for row in pivots}
    confirmations: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for pivot in pivots:
        confirmations[int(pivot["confirm_i"])].append(pivot)

    high_levels: list[tuple[float, int, str]] = []
    low_levels: list[tuple[float, int, str]] = []
    latest_highs: list[tuple[int, str]] = []
    latest_lows: list[tuple[int, str]] = []
    broken_ids: set[str] = set()
    state = 0
    protected: dict[str, Any] | None = None
    timeline = [0] * len(rows)
    buffer_price = break_buffer_pips * pip_size

    for i, row in enumerate(rows):
        for pivot in confirmations.get(i, []):
            pivot_id = str(pivot["pivot_id"])
            pivot_i = int(pivot["pivot_i"])
            if pivot["pivot_kind"] == "high":
                heapq.heappush(
                    high_levels,
                    (float(pivot["pivot_level"]), -pivot_i, pivot_id),
                )
                heapq.heappush(latest_highs, (-pivot_i, pivot_id))
            else:
                heapq.heappush(
                    low_levels,
                    (-float(pivot["pivot_level"]), -pivot_i, pivot_id),
                )
                heapq.heappush(latest_lows, (-pivot_i, pivot_id))

        close = float(row["mid_close"])
        broken_highs: list[dict[str, Any]] = []
        while high_levels:
            level, _, pivot_id = high_levels[0]
            if pivot_id in broken_ids:
                heapq.heappop(high_levels)
                continue
            if close <= level + buffer_price + 1e-12:
                break
            heapq.heappop(high_levels)
            broken_ids.add(pivot_id)
            broken_highs.append(by_id[pivot_id])

        broken_lows: list[dict[str, Any]] = []
        while low_levels:
            negative_level, _, pivot_id = low_levels[0]
            if pivot_id in broken_ids:
                heapq.heappop(low_levels)
                continue
            level = -negative_level
            if close >= level - buffer_price - 1e-12:
                break
            heapq.heappop(low_levels)
            broken_ids.add(pivot_id)
            broken_lows.append(by_id[pivot_id])

        bull_event = max(broken_highs, key=lambda item: item["pivot_i"]) if broken_highs else None
        bear_event = max(broken_lows, key=lambda item: item["pivot_i"]) if broken_lows else None
        protected_broken = bool(
            protected is not None
            and str(protected["pivot_id"]) in broken_ids
            and (
                (state == 1 and protected["pivot_kind"] == "low")
                or (state == -1 and protected["pivot_kind"] == "high")
            )
        )

        if state == 1 and protected_broken:
            state = -1
            protected = _latest_unbroken(latest_highs, broken_ids, by_id)
        elif state == -1 and protected_broken:
            state = 1
            protected = _latest_unbroken(latest_lows, broken_ids, by_id)
        elif state == 1 and bull_event is not None:
            protected = _latest_unbroken(latest_lows, broken_ids, by_id)
        elif state == -1 and bear_event is not None:
            protected = _latest_unbroken(latest_highs, broken_ids, by_id)
        elif state == 0 and (bull_event is not None or bear_event is not None):
            options = [(1, bull_event), (-1, bear_event)]
            selected = max(
                (item for item in options if item[1] is not None),
                key=lambda item: int(item[1]["pivot_i"]),
            )
            state = selected[0]
            protected = _latest_unbroken(
                latest_lows if state == 1 else latest_highs,
                broken_ids,
                by_id,
            )
        timeline[i] = state
    return timeline


def detect_pivot_launched_strong_moves(
    rows: list[dict[str, Any]],
    pip_size: float,
    min_net_pips: float,
    min_pfe: float,
    min_intervals: int,
    max_intervals: int,
    local_pivot_lookback_bars: int,
    episode_max_bars: int,
    pivot_tolerance_pips: float,
    gap_tolerance_pips: float,
) -> list[StrongMove]:
    closes = [float(row["mid_close"]) for row in rows]
    highs = [float(row["mid_high"]) for row in rows]
    lows = [float(row["mid_low"]) for row in rows]
    cumulative_path = [0.0] * len(rows)
    for i in range(1, len(rows)):
        cumulative_path[i] = cumulative_path[i - 1] + abs(closes[i] - closes[i - 1]) / pip_size

    candidates: list[dict[str, Any]] = []
    for start_i in range(local_pivot_lookback_bars, len(rows) - max_intervals):
        first_direction = candle_direction(rows[start_i])
        second_direction = candle_direction(rows[start_i + 1])
        if (first_direction, second_direction) == (1, -1):
            direction = "Bearish"
            pivot_price = max(highs[start_i : start_i + 2])
            prior_pivot = max(highs[start_i - local_pivot_lookback_bars : start_i])
            local_pivot = pivot_price >= prior_pivot - pivot_tolerance_pips * pip_size - 1e-12
        elif (first_direction, second_direction) == (-1, 1):
            direction = "Bullish"
            pivot_price = min(lows[start_i : start_i + 2])
            prior_pivot = min(lows[start_i - local_pivot_lookback_bars : start_i])
            local_pivot = pivot_price <= prior_pivot + pivot_tolerance_pips * pip_size + 1e-12
        else:
            continue
        if not local_pivot:
            continue
        second_open = float(rows[start_i + 1]["mid_open"])
        outside_gap = max(
            0.0,
            second_open - float(rows[start_i]["mid_high"]),
            float(rows[start_i]["mid_low"]) - second_open,
        ) / pip_size
        if outside_gap > gap_tolerance_pips:
            continue

        endpoints: list[dict[str, Any]] = []
        for intervals in range(min_intervals, max_intervals + 1):
            end_i = start_i + intervals
            elapsed = (rows[end_i]["time"] - rows[start_i]["time"]).total_seconds() / 60.0
            if elapsed > intervals * 15 + 30:
                continue
            net_pips = (closes[end_i] - closes[start_i]) / pip_size
            if (direction == "Bearish" and net_pips >= 0) or (
                direction == "Bullish" and net_pips <= 0
            ):
                continue
            abs_net = abs(net_pips)
            if abs_net < min_net_pips:
                continue
            path = cumulative_path[end_i] - cumulative_path[start_i]
            pfe = abs_net / path * 100.0 if path > 0 else 100.0
            if pfe >= min_pfe:
                endpoints.append(
                    {
                        "end_i": end_i,
                        "abs_net_pips": abs_net,
                        "pfe": pfe,
                    }
                )
        if not endpoints:
            continue
        endpoint = max(
            endpoints,
            key=lambda item: (item["abs_net_pips"], item["pfe"], -item["end_i"]),
        )
        candidates.append(
            {
                "direction": direction,
                "start_i": start_i,
                "end_i": int(endpoint["end_i"]),
                "abs_net_pips": float(endpoint["abs_net_pips"]),
                "pfe": float(endpoint["pfe"]),
                "pivot_price": pivot_price,
            }
        )

    episodes: list[list[dict[str, Any]]] = []
    for direction in ("Bullish", "Bearish"):
        directional = sorted(
            (item for item in candidates if item["direction"] == direction),
            key=lambda item: (item["start_i"], item["end_i"]),
        )
        groups: list[list[dict[str, Any]]] = []
        for candidate in directional:
            matching_group = None
            for group in reversed(groups):
                latest_start = max(item["start_i"] for item in group)
                if candidate["start_i"] - latest_start > episode_max_bars:
                    break
                if any(
                    candidate["start_i"] - item["start_i"] <= episode_max_bars
                    and candidate["start_i"] <= item["end_i"]
                    and abs(candidate["pivot_price"] - item["pivot_price"]) / pip_size
                    <= pivot_tolerance_pips + 1e-9
                    for item in group
                ):
                    matching_group = group
                    break
            if matching_group is None:
                groups.append([candidate])
            else:
                matching_group.append(candidate)
        episodes.extend(groups)

    episodes.sort(
        key=lambda group: (
            min(item["start_i"] for item in group),
            max(item["end_i"] for item in group),
        )
    )
    moves: list[StrongMove] = []
    for number, group in enumerate(episodes, start=1):
        best = max(
            group,
            key=lambda item: (item["abs_net_pips"], item["pfe"], -item["end_i"]),
        )
        cluster_start_i = min(int(item["start_i"]) for item in group)
        cluster_end_i = max(int(item["end_i"]) for item in group)
        moves.append(
            StrongMove(
                move_id=f"PSM_{number:05d}",
                direction=str(best["direction"]),
                start_i=int(best["start_i"]),
                end_i=int(best["end_i"]),
                cluster_start_i=cluster_start_i,
                cluster_end_i=cluster_end_i,
                confirm_i=cluster_end_i,
                abs_net_pips=float(best["abs_net_pips"]),
                pfe=float(best["pfe"]),
            )
        )
    return moves


def _interval_metrics(
    rows: list[dict[str, Any]],
    start_i: int,
    end_i: int,
    pip_size: float,
) -> dict[str, float]:
    frame = rows[start_i : end_i + 1]
    body_low = min(float(row["mid_body_low"]) for row in frame)
    body_high = max(float(row["mid_body_high"]) for row in frame)
    closes = [float(row["mid_close"]) for row in frame]
    net = abs(closes[-1] - closes[0]) / pip_size
    path = sum(abs(right - left) for left, right in zip(closes, closes[1:])) / pip_size
    return {
        "body_low": body_low,
        "body_high": body_high,
        "body_width_pips": (body_high - body_low) / pip_size,
        "net_progress_pips": net,
        "compression_pfe": 0.0 if path <= 1e-12 else net / path * 100.0,
    }


def detect_price_clusters(
    rows: list[dict[str, Any]],
    moves: list[StrongMove],
    pip_size: float,
    min_bars: int,
    max_body_width_pips: float,
    max_net_progress_pips: float,
    max_pfe: float,
) -> list[PriceCluster]:
    clusters: list[PriceCluster] = []
    for move in moves:
        candidates: list[dict[str, Any]] = []
        for start_i in range(
            move.cluster_start_i,
            move.cluster_end_i - min_bars + 2,
        ):
            for end_i in range(start_i + min_bars - 1, move.cluster_end_i + 1):
                metrics = _interval_metrics(rows, start_i, end_i, pip_size)
                if metrics["body_width_pips"] > max_body_width_pips:
                    break
                if metrics["net_progress_pips"] > max_net_progress_pips:
                    continue
                if metrics["compression_pfe"] > max_pfe:
                    continue
                candidates.append(
                    {
                        "start_i": start_i,
                        "end_i": end_i,
                        "bars": end_i - start_i + 1,
                        **metrics,
                    }
                )
        selected: list[dict[str, Any]] = []
        occupied: set[int] = set()
        for candidate in sorted(
            candidates,
            key=lambda item: (
                -item["bars"],
                item["body_width_pips"],
                item["compression_pfe"],
                item["start_i"],
            ),
        ):
            bars = set(range(candidate["start_i"], candidate["end_i"] + 1))
            if bars & occupied:
                continue
            selected.append(candidate)
            occupied.update(bars)
        selected.sort(key=lambda item: item["start_i"])
        for rank, item in enumerate(selected, start=1):
            clusters.append(
                PriceCluster(
                    cluster_id=f"{move.move_id}_PC{rank}",
                    move_id=move.move_id,
                    move_direction=move.direction,
                    move_confirm_i=move.confirm_i,
                    move_abs_net_pips=move.abs_net_pips,
                    move_pfe=move.pfe,
                    start_i=int(item["start_i"]),
                    end_i=int(item["end_i"]),
                    body_low=float(item["body_low"]),
                    body_high=float(item["body_high"]),
                )
            )
    return _add_cluster_cancellations(rows, clusters)


def _add_cluster_cancellations(
    rows: list[dict[str, Any]],
    clusters: list[PriceCluster],
) -> list[PriceCluster]:
    by_confirm: dict[int, list[int]] = defaultdict(list)
    for index, cluster in enumerate(clusters):
        by_confirm[cluster.move_confirm_i].append(index)
    resistance: list[tuple[float, int]] = []
    support: list[tuple[float, int]] = []
    active: set[int] = set()
    cancel: dict[int, int] = {}
    for i, row in enumerate(rows):
        close = float(row["mid_close"])
        while resistance and resistance[0][0] < close - 1e-12:
            _, index = heapq.heappop(resistance)
            if index in active:
                active.remove(index)
                cancel[index] = i
        while support and -support[0][0] > close + 1e-12:
            _, index = heapq.heappop(support)
            if index in active:
                active.remove(index)
                cancel[index] = i
        for index in by_confirm.get(i, []):
            cluster = clusters[index]
            active.add(index)
            if cluster.move_direction == "Bearish":
                heapq.heappush(resistance, (cluster.body_high, index))
            else:
                heapq.heappush(support, (-cluster.body_low, index))
    return [
        PriceCluster(**({**cluster.__dict__, "cancel_i": cancel.get(index)}))
        for index, cluster in enumerate(clusters)
    ]


def build_order_blocks(
    rows: list[dict[str, Any]],
    moves: list[StrongMove],
    pip_size: float,
) -> list[OrderBlock]:
    blocks: list[OrderBlock] = []
    for move in moves:
        first_i = move.start_i
        prices = [
            float(rows[first_i]["mid_open"]),
            float(rows[first_i]["mid_close"]),
            float(rows[first_i + 1]["mid_open"]),
            float(rows[first_i + 1]["mid_close"]),
        ]
        ranked = sorted(prices, reverse=move.direction == "Bearish")
        zone_low = min(ranked[0], ranked[2])
        zone_high = max(ranked[0], ranked[2])
        blocks.append(
            OrderBlock(
                order_block_id=f"{move.move_id}_OB1",
                order_block_type=(
                    "resistance_order_block"
                    if move.direction == "Bearish"
                    else "support_order_block"
                ),
                source_move_id=move.move_id,
                source_move_direction=move.direction,
                source_move_confirm_i=move.confirm_i,
                source_move_abs_net_pips=move.abs_net_pips,
                source_move_pfe=move.pfe,
                pivot_i=first_i,
                zone_low=zone_low,
                zone_high=zone_high,
            )
        )
    return _add_order_block_consumption(rows, blocks)


def _add_order_block_consumption(
    rows: list[dict[str, Any]],
    blocks: list[OrderBlock],
) -> list[OrderBlock]:
    by_confirm: dict[int, list[int]] = defaultdict(list)
    for index, block in enumerate(blocks):
        by_confirm[block.source_move_confirm_i].append(index)
    resistance: list[tuple[float, int]] = []
    support: list[tuple[float, int]] = []
    active: set[int] = set()
    consumed: dict[int, int] = {}
    for i, row in enumerate(rows):
        body_high = float(row["mid_body_high"])
        body_low = float(row["mid_body_low"])
        while resistance and resistance[0][0] < body_high - 1e-12:
            _, index = heapq.heappop(resistance)
            if index in active:
                active.remove(index)
                consumed[index] = i
        while support and -support[0][0] > body_low + 1e-12:
            _, index = heapq.heappop(support)
            if index in active:
                active.remove(index)
                consumed[index] = i
        for index in by_confirm.get(i, []):
            block = blocks[index]
            active.add(index)
            if block.order_block_type == "resistance_order_block":
                heapq.heappush(resistance, (block.zone_high, index))
            else:
                heapq.heappush(support, (-block.zone_low, index))
    return [
        OrderBlock(**({**block.__dict__, "consumed_i": consumed.get(index)}))
        for index, block in enumerate(blocks)
    ]


class MarketContextIndex:
    def __init__(self, rows: list[dict[str, Any]], params: Any) -> None:
        self.rows = rows
        self.params = params
        self.pip = float(params.pip_size)
        self.structure = build_protected_structure_timeline(
            rows,
            int(params.context_structure_confirm_bars),
            float(params.context_structure_break_buffer_pips),
            self.pip,
        )
        self.previous_day_raw_pfe = self._build_previous_day_pfe()
        self.asia_rows_by_day = self._build_asia_rows()
        self.moves = detect_pivot_launched_strong_moves(
            rows,
            self.pip,
            float(params.context_strong_move_min_net_pips),
            float(params.context_strong_move_min_pfe),
            int(params.context_strong_move_min_intervals),
            int(params.context_strong_move_max_intervals),
            int(params.context_strong_move_local_pivot_lookback_bars),
            int(params.context_strong_move_episode_max_bars),
            float(params.context_structural_tolerance_pips),
            float(params.context_order_block_gap_tolerance_pips),
        )
        self.clusters = detect_price_clusters(
            rows,
            self.moves,
            self.pip,
            int(params.context_cluster_min_bars),
            float(params.context_cluster_max_body_width_pips),
            float(params.context_cluster_max_net_progress_pips),
            float(params.context_cluster_max_pfe),
        )
        self.order_blocks = build_order_blocks(rows, self.moves, self.pip)
        self.moves_by_id = {move.move_id: move for move in self.moves}

    def _build_previous_day_pfe(self) -> dict[Any, float | None]:
        by_day: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for row in self.rows:
            by_day[row["london_date"]].append(row)
        valid_days = sorted(
            day for day, day_rows in by_day.items() if len(day_rows) >= 20
        )
        raw_by_day = {day: signed_pfe(by_day[day], 1) for day in valid_days}
        return {
            valid_days[index]: raw_by_day[valid_days[index - 1]]
            for index in range(1, len(valid_days))
        }

    def _build_asia_rows(self) -> dict[Any, list[tuple[int, dict[str, Any]]]]:
        output: dict[Any, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        for i, row in enumerate(self.rows):
            current_time = row["london_time"].time()
            if ASIA_START <= current_time <= ASIA_END:
                output[row["london_date"]].append((i, row))
        return output

    def _previous_day_pfe(self, side: str, run_start_i: int) -> float | None:
        raw = self.previous_day_raw_pfe.get(self.rows[run_start_i]["london_date"])
        if raw is None:
            return None
        return raw if side == "Buy" else -raw

    def _pre_run_asia_pfe(self, side: str, run_start_i: int) -> float | None:
        day = self.rows[run_start_i]["london_date"]
        selected = [row for index, row in self.asia_rows_by_day.get(day, []) if index < run_start_i]
        return signed_pfe(selected, 1 if side == "Buy" else -1)

    def _cluster_context(self, run: dict[str, Any], side: str) -> dict[str, Any]:
        start_i = int(run["start_i"])
        run_open = float(self.rows[start_i]["mid_open"])
        required_direction = "Bearish" if side == "Buy" else "Bullish"
        relevant = [
            cluster
            for cluster in self.clusters
            if cluster.move_direction == required_direction
            and cluster.move_confirm_i <= start_i
            and (cluster.cancel_i is None or cluster.cancel_i >= start_i)
            and self._cluster_ahead(cluster, side, run_open)
        ]
        representatives = self._collapse_cluster_areas(relevant, side, run_open)
        cleared: list[PriceCluster] = []
        terminal = None
        interaction = "no active directional cluster ahead"
        for cluster in representatives:
            if self._cluster_clean_break(cluster, side, float(run["close"])):
                cleared.append(cluster)
                continue
            terminal = cluster
            interaction = self._cluster_interaction(cluster, side, run)
            break
        if representatives and terminal is None:
            interaction = "run cleanly cleared every active cluster ahead"
        source_move = self.moves_by_id.get(terminal.move_id) if terminal else None
        return {
            "active_cluster_present_ahead": bool(representatives),
            "active_cluster_count_ahead": len(representatives),
            "active_terminal_cluster_id": terminal.cluster_id if terminal else "",
            "active_terminal_cluster_low": terminal.body_low if terminal else None,
            "active_terminal_cluster_high": terminal.body_high if terminal else None,
            "active_terminal_cluster_source_move_id": terminal.move_id if terminal else "",
            "active_terminal_cluster_source_move_start_time": (
                self.rows[source_move.start_i]["time"] if source_move else None
            ),
            "active_terminal_cluster_source_move_end_time": (
                self.rows[source_move.end_i]["time"] if source_move else None
            ),
            "active_cluster_interaction": interaction,
            "run_stopped_at_active_cluster": interaction in STOPPED_CLUSTER_INTERACTIONS,
            "run_cleared_active_cluster_count": len(cleared),
        }

    def _cluster_ahead(self, cluster: PriceCluster, side: str, run_open: float) -> bool:
        return run_open <= cluster.body_high if side == "Buy" else run_open >= cluster.body_low

    def _cluster_distance(self, cluster: PriceCluster, side: str, run_open: float) -> float:
        if cluster.body_low <= run_open <= cluster.body_high:
            return 0.0
        if side == "Buy":
            return max(0.0, (cluster.body_low - run_open) / self.pip)
        return max(0.0, (run_open - cluster.body_high) / self.pip)

    def _collapse_cluster_areas(
        self,
        clusters: list[PriceCluster],
        side: str,
        run_open: float,
    ) -> list[PriceCluster]:
        ordered = sorted(clusters, key=lambda item: (item.body_low, item.body_high))
        groups: list[list[PriceCluster]] = []
        current: list[PriceCluster] = []
        current_high = -math.inf
        tolerance = float(self.params.context_structural_tolerance_pips) * self.pip
        for cluster in ordered:
            if current and cluster.body_low > current_high + tolerance + 1e-12:
                groups.append(current)
                current = []
                current_high = -math.inf
            current.append(cluster)
            current_high = max(current_high, cluster.body_high)
        if current:
            groups.append(current)
        representatives = [
            max(
                group,
                key=lambda item: (item.move_confirm_i, item.move_abs_net_pips, item.move_pfe),
            )
            for group in groups
        ]
        return sorted(
            representatives,
            key=lambda item: self._cluster_distance(item, side, run_open),
        )

    def _cluster_clean_break(self, cluster: PriceCluster, side: str, close: float) -> bool:
        return close > cluster.body_high if side == "Buy" else close < cluster.body_low

    def _cluster_interaction(
        self,
        cluster: PriceCluster,
        side: str,
        run: dict[str, Any],
    ) -> str:
        close = float(run["close"])
        if side == "Buy":
            wick_touched = float(run["wick_high"]) >= cluster.body_low
            body_entered = float(run["high"]) >= cluster.body_low
            closed_before = close < cluster.body_low
            closed_inside = cluster.body_low <= close <= cluster.body_high
            wick_broke_far = float(run["wick_high"]) > cluster.body_high
        else:
            wick_touched = float(run["wick_low"]) <= cluster.body_high
            body_entered = float(run["low"]) <= cluster.body_high
            closed_before = close > cluster.body_high
            closed_inside = cluster.body_low <= close <= cluster.body_high
            wick_broke_far = float(run["wick_low"]) < cluster.body_low
        if not wick_touched:
            return "run stopped before cluster"
        if not body_entered:
            return "wick touched cluster"
        if closed_before:
            return "body entered then closed back before cluster"
        if closed_inside:
            return "signal closed inside cluster"
        if wick_broke_far:
            return "wick broke far edge without clean close"
        return "body entered cluster without terminal close classification"

    def _order_block_context(self, run: dict[str, Any], side: str) -> dict[str, Any]:
        start_i = int(run["start_i"])
        run_open = float(self.rows[start_i]["mid_open"])
        required_type = "resistance_order_block" if side == "Buy" else "support_order_block"
        eligible = [
            block
            for block in self.order_blocks
            if block.order_block_type == required_type
            and block.source_move_confirm_i <= start_i
            and (block.consumed_i is None or block.consumed_i >= start_i)
            and self._block_ahead(block, side, run_open)
        ]
        eligible = self._collapse_order_blocks(eligible, side, run_open)
        cleared: list[OrderBlock] = []
        terminal = None
        flags = None
        broad = "no active order block ahead"
        for block in eligible:
            current = self._order_block_flags(block, side, run)
            if current["clean_break"]:
                cleared.append(block)
                continue
            terminal = block
            flags = current
            break
        if terminal is not None and flags is not None:
            extreme_inside = (
                terminal.zone_low <= float(run["wick_high"]) <= terminal.zone_high
                if side == "Buy"
                else terminal.zone_low <= float(run["wick_low"]) <= terminal.zone_high
            )
            if extreme_inside:
                broad = "run stopped at order block"
            elif flags["wick_broke_far_edge"] and not flags["clean_break"]:
                broad = "run wick crossed beyond order block without clean close"
            elif not flags["wick_touched"]:
                broad = "run stopped before order block"
        elif eligible:
            broad = "run cleared all active order blocks"
        source_move = (
            self.moves_by_id.get(terminal.source_move_id) if terminal else None
        )
        return {
            "active_order_block_count_ahead": len(eligible),
            "terminal_order_block_id": terminal.order_block_id if terminal else "",
            "terminal_order_block_low": terminal.zone_low if terminal else None,
            "terminal_order_block_high": terminal.zone_high if terminal else None,
            "terminal_order_block_source_move_id": (
                terminal.source_move_id if terminal else ""
            ),
            "terminal_order_block_source_move_start_time": (
                self.rows[source_move.start_i]["time"] if source_move else None
            ),
            "terminal_order_block_source_move_end_time": (
                self.rows[source_move.end_i]["time"] if source_move else None
            ),
            "order_block_broad_interaction": broad,
            "order_block_reached_without_clean_close": broad in {
                "run stopped at order block",
                "run wick crossed beyond order block without clean close",
            },
            "run_cleared_order_block_count": len(cleared),
        }

    def _block_ahead(self, block: OrderBlock, side: str, run_open: float) -> bool:
        return run_open <= block.zone_high if side == "Buy" else run_open >= block.zone_low

    def _block_distance(self, block: OrderBlock, side: str, run_open: float) -> float:
        if block.zone_low <= run_open <= block.zone_high:
            return 0.0
        if side == "Buy":
            return max(0.0, (block.zone_low - run_open) / self.pip)
        return max(0.0, (run_open - block.zone_high) / self.pip)

    def _collapse_order_blocks(
        self,
        blocks: list[OrderBlock],
        side: str,
        run_open: float,
    ) -> list[OrderBlock]:
        remaining = sorted(
            blocks,
            key=lambda item: (
                self._block_distance(item, side, run_open),
                -item.source_move_confirm_i,
            ),
        )
        representatives: list[OrderBlock] = []
        tolerance = float(self.params.context_structural_tolerance_pips) * self.pip
        while remaining:
            anchor = remaining.pop(0)
            same_area = [anchor]
            later: list[OrderBlock] = []
            for block in remaining:
                separated = (
                    block.zone_low > anchor.zone_high + tolerance
                    or anchor.zone_low > block.zone_high + tolerance
                )
                (later if separated else same_area).append(block)
            representatives.append(
                max(
                    same_area,
                    key=lambda item: (
                        item.source_move_confirm_i,
                        -self._block_distance(item, side, run_open),
                    ),
                )
            )
            remaining = later
        return sorted(
            representatives,
            key=lambda item: (
                self._block_distance(item, side, run_open),
                -item.source_move_confirm_i,
            ),
        )

    def _order_block_flags(
        self,
        block: OrderBlock,
        side: str,
        run: dict[str, Any],
    ) -> dict[str, bool]:
        close = float(run["close"])
        if side == "Buy":
            return {
                "wick_touched": float(run["wick_high"]) >= block.zone_low,
                "wick_broke_far_edge": float(run["wick_high"]) > block.zone_high,
                "clean_break": close > block.zone_high,
            }
        return {
            "wick_touched": float(run["wick_low"]) <= block.zone_high,
            "wick_broke_far_edge": float(run["wick_low"]) < block.zone_low,
            "clean_break": close < block.zone_low,
        }

    def evaluate_run(
        self,
        run: dict[str, Any],
        side: str,
        index_offset: int = 0,
    ) -> dict[str, Any]:
        context_run = (
            run
            if index_offset == 0
            else run
            | {
                "start_i": int(run["start_i"]) + index_offset,
                "end_i": int(run["end_i"]) + index_offset,
            }
        )
        start_i = int(context_run["start_i"])
        structure_direction = self.structure[start_i - 1] if start_i > 0 else 0
        previous_day_pfe = self._previous_day_pfe(side, start_i)
        asia_pfe = self._pre_run_asia_pfe(side, start_i)
        trade_direction = 1 if side == "Buy" else -1
        asia_reversal_sell = bool(
            side == "Sell"
            and structure_direction == -trade_direction
            and previous_day_pfe is not None
            and previous_day_pfe < 0
            and asia_pfe is not None
            and asia_pfe > 0
        )
        cluster = self._cluster_context(context_run, side)
        order_block = self._order_block_context(context_run, side)
        adverse_order_block = bool(
            previous_day_pfe is not None
            and previous_day_pfe < 0
            and order_block["order_block_reached_without_clean_close"]
        )
        reasons: list[str] = []
        if self.params.use_adverse_asia_reversal_sell_filter and asia_reversal_sell:
            reasons.append("Adverse Asia-reversal sell context")
        if self.params.use_active_price_cluster_stop_filter and cluster[
            "run_stopped_at_active_cluster"
        ]:
            reasons.append("Imbalance run stopped at active price cluster")
        if self.params.use_adverse_order_block_stop_filter and adverse_order_block:
            reasons.append("Adverse run reached order block without clean close through")
        return {
            "context_filter_blocked": bool(reasons),
            "context_filter_reason": "; ".join(reasons),
            "pre_run_structure_direction": structure_direction,
            "previous_day_signed_pfe_trade_direction": previous_day_pfe,
            "pre_run_asia_signed_pfe_trade_direction": asia_pfe,
            "adverse_asia_reversal_sell": asia_reversal_sell,
            "adverse_asia_reversal_sell_filter_triggered": bool(
                self.params.use_adverse_asia_reversal_sell_filter
                and asia_reversal_sell
            ),
            "active_price_cluster_stop_filter_triggered": bool(
                self.params.use_active_price_cluster_stop_filter
                and cluster["run_stopped_at_active_cluster"]
            ),
            "adverse_order_block_stop_filter_triggered": bool(
                self.params.use_adverse_order_block_stop_filter
                and adverse_order_block
            ),
            **cluster,
            **order_block,
            "adverse_order_block_stop": adverse_order_block,
        }
