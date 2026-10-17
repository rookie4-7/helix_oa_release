"""Causal original trendline obstacles qualified by Atlas pivot-local scores."""
from copy import deepcopy
from datetime import timedelta

import legacy_trendline_logic as legacy
from pivot_logic import pivot_confirmations

BAR = timedelta(minutes=15)
EPS = 1e-12


def line_snapshots(rows, query_times, params):
    from strategy_logic import find_pivots
    rows = [r if 'mid_body_high' in r and 'mid_body_low' in r else r | dict(
        mid_body_high=max(r['mid_open'], r['mid_close']),
        mid_body_low=min(r['mid_open'], r['mid_close'])) for r in rows]
    flags = {}
    for year in sorted({r['time'].year for r in rows}):
        local = [r for r in rows if r['time'].year == year]
        high = find_pivots([r['buy_body_high'] for r in local], params.left_bars, params.right_bars, 'high')
        low = find_pivots([r['sell_body_low'] for r in local], params.left_bars, params.right_bars, 'low')
        flags.update({r['time']: (h, l) for r, h, l in zip(local, high, low)})
    result, resistance, support, highs, lows = {}, [], [], [], []
    previous_year = None
    tolerance = params.trendline_validation_tolerance_pips * params.pip_size
    for i, row in enumerate(rows):
        year = row['time'].year
        if year != previous_year:
            resistance, support, highs, lows = [], [], [], []
            previous_year = year
        high, low = flags[row['time']]
        if high:
            legacy.add_resistance_trendlines(resistance, highs, rows, i, params.right_bars, tolerance)
        if low:
            legacy.add_support_trendlines(support, lows, rows, i, params.right_bars, tolerance)
        legacy.deactivate_trendline_obstacles(row, i, resistance, support, tolerance)
        resistance = [p for p in resistance if p['active']]
        support = [p for p in support if p['active']]
        if row['time'] in query_times:
            result[row['time']] = {side: [deepcopy(p) | dict(
                first_anchor_time=rows[p['x1']]['time'],
                second_anchor_time=rows[p['x2']]['time'],
                confirmed_time=rows[p['created']]['time']+BAR) for p in book]
                for side, book in (('Buy', resistance), ('Sell', support))}
    if set(result) != set(query_times):
        raise ValueError('Trendline evaluation candle is absent from the price history')
    return result


def score_qualifies(scores, params):
    thresholds = (
        ('trade_side_oldest_local', params.trendline_trade_side_oldest_local_min_score),
        ('trade_side_latest_local', params.trendline_trade_side_latest_local_min_score),
        ('opposite_side_latest_trailing', params.trendline_opposite_side_latest_trailing_min_score),
    )
    return [key for key, cutoff in thresholds
            if scores.get(key) is not None and scores[key] > cutoff]


class PivotScores:
    def __init__(self, rows, params):
        from context_filters import cluster_windows
        self.rows = rows
        self.pivots = []
        for i, events in pivot_confirmations(rows, (5,)).items():
            for p in events:
                self.pivots.append(dict(p) | {'known_at': rows[i]['time']+BAR})
        self.pivots.sort(key=lambda p: (p['formed_time'], p['side']))
        self.windows = cluster_windows(rows, params.price_cluster_candles,
                                       params.price_cluster_reference_bars, -1)
        self.candles = params.price_cluster_candles
        self.contexts, self.cache = {}, {}

    def box(self, window):
        if window is None:
            return None
        return {k: window[k] for k in ('id', 'score', 'low', 'high', 'known_at',
            'overlap', 'compactness', 'slowness', 'back_and_forth')} | dict(
                start_time=self.rows[window['start']]['time'],
                last_candle_time=self.rows[window['created']]['time'])

    def scores(self, pivot, cutoff):
        key = pivot['id'], cutoff
        if key in self.cache:
            return self.cache[key]
        limit = min(pivot['known_at'], cutoff)
        i, level = pivot['formed_i'], pivot['level']
        contains = lambda w: w['low']-EPS <= level <= w['high']+EPS
        local = [w for end in range(i, i+self.candles)
            if (w := self.windows.get(end)) is not None and w['start'] <= i
            and w['known_at'] <= limit and contains(w)]
        best = max(local, key=lambda w: (w['score'], -w['created']), default=None)
        trailing = self.windows.get(i)
        if trailing is not None and (trailing['known_at'] > limit or not contains(trailing)):
            trailing = None
        value = dict(local_score=best['score'] if best else None,
            trailing_score=trailing['score'] if trailing else None,
            local_box=self.box(best), trailing_box=self.box(trailing))
        self.cache[key] = value
        return value

    def context(self, cutoff, side):
        if cutoff not in self.contexts:
            self.contexts[cutoff] = {direction: [p for p in self.pivots
                if p['side'] == direction and p['formed_time'] < cutoff
                and p['known_at'] <= cutoff][-3:] for direction in ('Buy', 'Sell')}
        context = self.contexts[cutoff]
        scores = dict(trade_side_oldest_local=None, trade_side_latest_local=None,
                      opposite_side_latest_trailing=None)
        witnesses = []
        for group, direction in (('trade_side', side),
                                 ('opposite_side', 'Sell' if side == 'Buy' else 'Buy')):
            points = context[direction]
            for position, pivot in zip(('oldest', 'middle', 'latest')[-len(points):], points):
                values = self.scores(pivot, cutoff)
                for suffix, key in (('local', 'local_score'), ('trailing', 'trailing_score')):
                    name = f'{group}_{position}_{suffix}'
                    if name in scores:
                        scores[name] = values[key]
                witnesses.append(dict(group=group, position=position, pivot_id=pivot['id'],
                    pivot_time=pivot['formed_time'], pivot_price=pivot['level'],
                    pivot_confirmed_at=pivot['known_at'], evaluated_at=cutoff,
                    reference_pivot_count=len(points), **values))
        return scores, witnesses


def evaluate_line(event, side, end, snapshot, params, scores=None):
    body = event['run_high'] if side == 'Buy' else event['run_low']
    width = params.trendline_obstacle_pips * params.pip_size
    hits = []
    for line in snapshot[side]:
        if line['confirmed_time'] > event['available_from']:
            raise ValueError('Trendline was not confirmed before evaluation')
        if legacy.trendline_hits_price(line, end, body, width):
            price = legacy.trendline_price_at(line['x1'], line['y1'], line['x2'], line['y2'], end)
            hits.append(dict(line) | dict(kind='trendline', projected_price=price,
                low=price-width, high=price+width, known_at=line['confirmed_time']))
    scores = scores or dict(trade_side_oldest_local=None, trade_side_latest_local=None,
                           opposite_side_latest_trailing=None)
    conditions = score_qualifies(scores, params)
    return dict(blocked=bool(hits) and (not params.use_trendline_cluster_score_filter or bool(conditions)),
        trendline_hit=bool(hits), hits=hits, body_extreme=body,
        evaluated_at=event['available_from'], regression_gate_used=False,
        cluster_score_filter_enabled=params.use_trendline_cluster_score_filter,
        scores=scores, score_conditions_met=conditions)


def apply_trendline_filter(rows, signals, params):
    queries = {e['line_time'] for s in signals for e in s.get('entry_line_events', [])}
    if not queries:
        return signals
    index = {r['time']: i for i, r in enumerate(rows)}
    snapshots = line_snapshots(rows, queries, params)
    scorer = PivotScores(rows, params) if params.use_trendline_cluster_score_filter else None
    result = []
    for signal in signals:
        events = signal.get('entry_line_events', [])
        audits, allowed = [], []
        for event in events:
            side = event.get('signal_direction', signal['direction'])
            i = index[event['line_time']]
            if event['available_from'] != rows[i]['time']+BAR:
                raise ValueError('Trendline filters require a completed M15 candle')
            decision = evaluate_line(event, side, i, snapshots[event['line_time']], params)
            witnesses = []
            if decision['trendline_hit'] and scorer is not None:
                scores, witnesses = scorer.context(signal['run_start_time'], side)
                decision = evaluate_line(event, side, i, snapshots[event['line_time']], params, scores)
            decision['score_reference_pivots'] = witnesses
            audits.append(dict(line_version=event['line_version'], **decision))
            if not decision['blocked']:
                allowed.append(deepcopy(event) | {'mark4_trendline_decision': decision})
        updated = dict(signal, entry_line_events=allowed, mark4_trendline_filter_audit=audits,
            mark4_trendline_removed_lines=len(events)-len(allowed))
        # Enrich the existing obstacle audit without erasing earlier blocking reasons.
        by_version = {a['line_version']: a for a in audits}
        combined = []
        source_audits = signal.get('context_filter_audit', [dict(
            line_version=e['line_version'], blocked=False, reasons=[], hits=[]) for e in events])
        for original in source_audits:
            audit = deepcopy(original)
            extra = by_version.get(audit['line_version'])
            if extra is not None:
                audit['mark4_trendline_decision'] = extra
                if extra['blocked']:
                    audit['blocked'] = True
                    audit['reasons'] = sorted(set(audit['reasons']) | {'cluster-qualified trendline'
                        if params.use_trendline_cluster_score_filter else 'trendline'})
                    audit['hits'] += deepcopy(extra['hits'])
            combined.append(audit)
        if combined:
            updated['context_filter_audit'] = combined
        removed = signal.get('context_filter_removed_lines', 0) + len(events)-len(allowed)
        updated['context_filter_removed_lines'] = removed
        updated['context_filter_blocked'] = bool(signal.get('context_filter_original_lines', len(events)) and not allowed)
        updated['obstacle_hit'] = signal.get('obstacle_hit', False) or any(a['blocked'] for a in audits)
        reasons = sorted({r for a in combined for r in a['reasons']})
        updated['context_filter_reason'] = ', '.join(reasons)
        if events and not allowed:
            updated.update(status='Invalid', reason='Context filters: ' + ', '.join(reasons))
        elif allowed:
            updated['execution_start_time'] = allowed[0]['available_from']
            updated.update({k: allowed[-1][k] for k in ('entry', 'stop_loss', 'take_profit', 'setup_type', 'signal_text')})
            updated['entry_deadline'] = allowed[-1]['active_until']
        result.append(updated)
    return result
