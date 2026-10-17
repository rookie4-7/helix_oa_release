"""Confirmed body pivots and one-time historical breaks, evaluated causally."""
from dataclasses import dataclass, field
from datetime import timedelta


def shared_pivot_turn(previous, current, side):
    key = 'buy_body_high' if side == 'Buy' else 'sell_body_low'
    level = previous[key]
    return (current['time'] - previous['time'] == timedelta(minutes=15)
            and abs(current[key] - level) < 1e-12
            and abs(previous['mid_close'] - level) < 1e-12
            and abs(current['mid_open'] - level) < 1e-12)


def pivot_turn_origins(rows, side):
    origins = list(range(len(rows)))
    for i in range(1, len(rows)):
        if shared_pivot_turn(rows[i-1], rows[i], side):
            origins[i] = origins[i-1]
    return origins


def pivot_confirmations(rows, scales):
    events = {}
    origins = {side: pivot_turn_origins(rows, side) for side in ('Buy', 'Sell')}
    seen = set()
    for scale in scales:
        for i in range(scale, len(rows) - scale):
            window = rows[i - scale:i + scale + 1]
            for side, key, extremum in (
                ("Buy", "buy_body_high", max), ("Sell", "sell_body_low", min)):
                if rows[i][key] == extremum(r[key] for r in window):
                    first = origins[side][i]
                    identity = side, first, scale
                    if identity in seen:
                        continue
                    seen.add(identity)
                    # Keep the real qualifying window's confirmation time. A
                    # later half of a turn must not confirm a larger scale early.
                    events.setdefault(i + scale, []).append({
                        "id": f"{side}_{rows[first]['time'].isoformat()}",
                        "side": side, "level": rows[first][key], "formed_i": first,
                        "formed_time": rows[first]["time"], "day": rows[first]["london_date"],
                        "confirmed_i": i + scale, "scale": scale,
                        "confirmation_center_i": i,
                    })
    return events


@dataclass
class PivotBook:
    lookback: int
    records: dict = field(default_factory=dict)

    def confirm(self, events, index):
        self.records = {k: p for k, p in self.records.items() if index - p["formed_i"] <= self.lookback}
        fresh = []
        for event in events:
            key = event["id"]
            if key in self.records:
                record = self.records[key]
                scale = event['scale']
                record['scales'].add(scale)
                confirmed_i = event.get('confirmed_i', index)
                record['scale_confirmed_i'][scale] = min(
                    record['scale_confirmed_i'].get(scale, confirmed_i), confirmed_i)
                continue
            pivot = event | {"scales": {event["scale"]}, "consumed": False,
                             "scale_confirmed_i": {event['scale']: event.get('confirmed_i', index)}}
            self.records[key] = pivot
            fresh.append(pivot)
        return fresh

    def cross(self, row, prev, buffer, index):
        """Consume a first confirmed body crossing even outside the setup window."""
        crossed = []
        for p in self.records.values():
            if p["consumed"] or index - p["formed_i"] > self.lookback:
                continue
            high = p["side"] == "Buy"
            key = "buy_body_high" if high else "sell_body_low"
            # Pivot confirmation happens at this candle's close. Do not give the
            # level credit for a break that occurred before confirmation.
            beyond = row["mid_close"] > p["level"] + buffer if high else row["mid_close"] < p["level"] - buffer
            prior = prev is not None and (prev[key] <= p["level"] if high else prev[key] >= p["level"])
            if beyond:
                p["consumed"] = True
                if prior and row["direction"] == (1 if high else -1):
                    crossed.append(p)
        return crossed


def historical_breaks(crossed, row, current_day_break, run, same_run=True):
    side = "Buy" if row["direction"] == 1 else "Sell"
    gate = current_day_break or bool(
        same_run and run and run["direction"] == row["direction"]
        and run.get("mark2_current_day_pivot_break")
    )
    historical = [p for p in crossed if p["day"] < row["london_date"] and p["side"] == side]
    return historical if gate else [], historical if not gate else []


def pivot_audit(pivot):
    audit = {key: value for key, value in pivot.items() if key != "consumed"} | {
        "scales": sorted(pivot["scales"])
    }
    if 'scale_confirmed_i' in audit:
        audit['scale_confirmed_i'] = dict(audit['scale_confirmed_i'])
    return audit


def apply_ibos_pivot_requirement(run, row, index, absolute_index, crossed,
                                 in_london_setup, candidate, body_valid, body_pips):
    """Activate IBOS only after both conditions exist in this exact run."""
    side = "Buy" if row["direction"] == 1 else "Sell"
    anchors = run.setdefault("ibos_current_day_pivot_breaks", [])
    if in_london_setup:
        anchors.extend(
            pivot_audit(p) | {"break_time": row["time"]}
            for p in crossed
            if p["day"] == row["london_date"] and p["side"] == side
            and p["confirmed_i"] < absolute_index
        )
    if candidate:
        run["ibos_candidate"] = True
        run["ibos_candidate_valid"] = run.get("ibos_candidate_valid", False) or body_valid
        run["ibos_candidate_largest_body_pips"] = max(
            run.get("ibos_candidate_largest_body_pips", 0.0), body_pips)

    if not in_london_setup or not anchors or not run.get("ibos_candidate"):
        return
    run["internal"] = True
    run["has_setup"] = True
    run["internal_valid"] = run.get("ibos_candidate_valid", False)
    run["valid_imbalance"] = run["valid_imbalance"] or run["internal_valid"]
    run["largest_body_pips"] = max(
        run["largest_body_pips"], run["ibos_candidate_largest_body_pips"])
    # Activation is now, never backdated to an earlier candidate candle.
    if run["first_setup_i"] is None:
        run["first_setup_i"] = index
    if run["internal_valid"] and run["first_valid_i"] is None:
        run["first_valid_i"] = index
