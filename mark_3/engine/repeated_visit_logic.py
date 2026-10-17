"""Outcome-blind setup membership and first-break obstacle exception."""
from bisect import bisect_left, bisect_right
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from visit_detector import VisitConfig, track_visits

LONDON = ZoneInfo('Europe/London')
SOURCES = {'Current_day_pivot', 'IBOS_required_current_day_pivot'}
BAR = timedelta(minutes=15)
EPSILON = 1e-12


def london_day(t):
    return t.replace(tzinfo=timezone.utc).astimezone(LONDON).date()


def confirmation_records(rows, scales):
    from pivot_logic import pivot_confirmations
    return sorted([dict(id=p['id'], side=p['side'], time=p['formed_time'],
                        level=p['level'], scale=p['scale'],
                        known_at=rows[i]['time']+BAR)
                   for i, values in pivot_confirmations(rows, scales).items()
                   for p in values], key=lambda p: (p['known_at'], p['time'], p['scale']))


class VisitIndex:
    """Query the unchanged prototype, pruning only provably broken seeds."""
    def __init__(self, rows, events, config=None):
        self.rows, self.events = rows, events
        self.config = config or VisitConfig()
        self.close_times = [r['time']+BAR for r in rows]
        self.row_index = {r['time']: i for i, r in enumerate(rows)}
        self.closes = [r['mid_close'] for r in rows]
        self.records, self.grouped, self.seeds, self.side_events = {}, {}, {}, {}
        self.snapshots, self.anchor_queries = {}, {}
        self.tracker_calls = 0
        for event in events:
            p = self.records.setdefault(event['id'], dict(
                id=event['id'], side=event['side'], time=event['time'], level=event['level'],
                known_at=event['known_at'], known={}))
            p['known'][event['scale']] = event['known_at']
        for side in ('Buy', 'Sell'):
            seeds = sorted((p for p in self.records.values() if p['side'] == side),
                           key=lambda p: (p['known_at'], p['time']))
            self.seeds[side] = (seeds, [p['known_at'] for p in seeds])
            ee = [e for e in events if e['side'] == side]
            self.side_events[side] = (ee, [e['known_at'] for e in ee])
        for p in self.records.values():
            self.grouped.setdefault((london_day(p['time']), p['side']), []).append(p)

    def snapshot(self, seed, cutoff):
        key = seed['id'], cutoff
        if key not in self.snapshots:
            rows = self.rows[self.row_index[seed['time']]:bisect_right(self.close_times, cutoff)]
            events, times = self.side_events[seed['side']]
            selected = events[bisect_left(times, seed['time']):bisect_right(times, cutoff)]
            config = VisitConfig(**(self.config.__dict__ | {'side': seed['side']}))
            self.snapshots[key] = track_visits(rows, selected,
                {k: v for k, v in seed.items() if k != 'known'}, config, cutoff)
            self.tracker_calls += 1
        return self.snapshots[key]

    def possible_seeds(self, side, level, cutoff):
        stop = bisect_right(self.close_times, cutoff)
        tolerance = self.config.membership_tolerance_pips*self.config.pip_size
        distance = 2*tolerance+self.config.break_buffer_pips*self.config.pip_size
        # A seed must be within one tolerance of the setup price. Its support
        # floor/resistance ceiling is within another tolerance of that seed.
        # A farther prior close therefore guarantees consumption for ANY such
        # seed already confirmed then. This is not an age/expiry rule.
        last_consuming_close = next((self.close_times[i] for i in range(stop-1, -1, -1)
            if (self.closes[i] < level-distance-EPSILON if side == 'Sell'
                else self.closes[i] > level+distance+EPSILON)), None)
        seeds, times = self.seeds[side]
        start = bisect_right(times, last_consuming_close) if last_consuming_close else 0
        end = bisect_right(times, cutoff)
        return [s for s in seeds[start:end]
                if abs(s['level']-level) <= tolerance+EPSILON]

    def before_break(self, side, anchor):
        when = anchor['break_time']
        key = side, anchor['level'], when, anchor.get('formed_time')
        if key in self.anchor_queries:
            return self.anchor_queries[key]
        sources = [p for p in self.grouped.get((london_day(when), side), [])
                   if p['known_at'] <= when and abs(p['level']-anchor['level']) < 1e-9
                   and (not anchor.get('formed_time') or p['time'] == anchor['formed_time'])]
        if not sources:
            raise ValueError('Actual setup pivot cannot be resolved from confirmed current-day data.')
        possible = self.possible_seeds(side, anchor['level'], when)
        valid = []
        for seed in possible:
            before = self.snapshot(seed, when)
            if (before['break_event'] or len(before['visits']) < self.config.minimum_visits
                    or before['measurements']['sd_ceiling_passed'] is False):
                continue
            members = {pid for v in before['visits'] for pid in v['pivot_ids']}
            included = [p for p in sources if p['id'] in members]
            if included:
                valid.append((seed, before, included, sources))
        self.anchor_queries[key] = valid
        return valid

    def qualify(self, signal, event):
        side = event.get('signal_direction', signal['direction'])
        witnesses, seen = [], set()
        for anchor in event.get('setup_anchors', []):
            if anchor['source'] not in SOURCES:
                continue
            if anchor['known_at'] > anchor['break_time']:
                raise ValueError('Setup source was not known before the break candle.')
            for seed, before, included, sources in self.before_break(side, anchor):
                after = self.snapshot(seed, event['available_from'])
                broken = after['break_event']
                if not broken or not (signal['run_start_time'] <= broken['candle_time']
                                      <= event['line_time']) or broken['known_at'] > event['available_from']:
                    continue
                for pivot in included:
                    identity = seed['id'], pivot['id'], anchor['break_time']
                    if identity in seen:
                        continue
                    seen.add(identity)
                    visits = before['visits']
                    stats = before['measurements']
                    witnesses.append(dict(
                        anchor_source=anchor['source'], side=side,
                        setup_pivot_id=pivot['id'], setup_pivot_utc=pivot['time'],
                        setup_pivot_level=pivot['level'], setup_break_utc=anchor['break_time'],
                        setup_pivot_scales=sorted(s for s, t in pivot['known'].items()
                                                  if t <= anchor['break_time']),
                        setup_pivot_known_utc=pivot['known_at'],
                        source_same_price_candidates=[p['id'] for p in sources],
                        seed_id=seed['id'], seed_utc=seed['time'], seed_level=seed['level'],
                        seed_known_utc=seed['known_at'],
                        formation_age_hours=(anchor['break_time']-seed['time']).total_seconds()/3600,
                        membership_low=before['membership_low'], membership_high=before['membership_high'],
                        departure_close_price=before['departure_close_price'],
                        completed_visits=len(visits), visit_sd_pips=stats['sd_pips'],
                        visit_slope_pips_per_hour=stats['slope_pips_per_hour'],
                        observed_low=stats['observed_low'], observed_high=stats['observed_high'],
                        observed_span_pips=(stats['observed_high']-stats['observed_low'])/self.config.pip_size,
                        visit_pivot_ids=[p for v in visits for p in v['pivot_ids']],
                        visit_prices=[v['price'] for v in visits],
                        visit_representative_times=[v['representative_time'] for v in visits],
                        maximum_visit_spread_pips=max(v['maximum_spread_pips'] for v in visits),
                        pattern_first_break_utc=broken['candle_time'],
                        pattern_break_known_utc=broken['known_at'], break_close=broken['close'],
                        broken_floor_or_ceiling=broken['price'], clearance_pips=broken['clearance_pips'],
                        pre_break_cutoff=anchor['break_time'],
                    ))
        return sorted(witnesses, key=lambda w: (w['seed_utc'], w['setup_pivot_utc']))
