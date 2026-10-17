"""Causal obstacle eligibility on the unchanged Mark 2 candidate-line stream."""
from calendar import monthrange
from copy import deepcopy
from datetime import timedelta
from itertools import combinations
import math

from pivot_logic import pivot_confirmations


def expires_at(known, months):
    if not months:
        return None
    total = known.year * 12 + known.month - 1 + months
    year, month = divmod(total, 12)
    month += 1
    return known.replace(year=year, month=month, day=min(known.day, monthrange(year, month)[1]))


def cluster_windows(rows, candles=6, reference=96, cutoff=50.0):
    """Earlier reference excludes all candidate candles; gaps are not movement."""
    highs, lows, closes = ([float(r['mid_' + key]) for r in rows]
                          for key in ('high', 'low', 'close'))
    tr_sum, move_sum, move_count = [0.0], [0.0], [0]
    continuous = []
    for i, row in enumerate(rows):
        op, close, high, low = (float(row['mid_' + k]) for k in ('open', 'close', 'high', 'low'))
        if not all(math.isfinite(x) for x in (op, close, high, low)) or high < max(op, close) or low > min(op, close):
            raise ValueError('Invalid cluster OHLC')
        if i and row['time'] <= rows[i - 1]['time']:
            raise ValueError('Cluster history must be sorted and unique')
        step = bool(i and row['time'] - rows[i - 1]['time'] == timedelta(minutes=15))
        continuous.append(step)
        tr = max(high-low, abs(high-closes[i-1]), abs(low-closes[i-1])) if step else high-low
        tr_sum.append(tr_sum[-1] + tr)
        move_sum.append(move_sum[-1] + (abs(close-closes[i-1]) if step else 0.0))
        move_count.append(move_count[-1] + int(step))
    result = {}
    pairs = list(combinations(range(candles), 2))
    for end in range(candles - 1 + reference, len(rows)):
        start = end - candles + 1
        if not all(continuous[start+1:end+1]):
            continue
        atr = (tr_sum[start] - tr_sum[start-reference]) / reference
        count = move_count[start] - move_count[start-reference]
        normal_step = (move_sum[start] - move_sum[start-reference]) / count if count else 0.0
        if atr <= 0 or normal_step <= 0:
            continue
        h, l, c = highs[start:end+1], lows[start:end+1], closes[start:end+1]
        overlap = 0.0
        for a, b in pairs:
            union = max(h[a], h[b]) - min(l[a], l[b])
            overlap += max(0.0, min(h[a], h[b])-max(l[a], l[b])) / union if union else 1.0
        overlap /= len(pairs)
        width = max(h) - min(l)
        path = sum(abs(b-a) for a, b in zip(c, c[1:]))
        speed = path / ((candles-1) * .25)
        normal_speed = normal_step / .25
        back_and_forth = max(0.0, min(1.0, 1-abs(c[-1]-c[0])/path)) if path else 1.0
        compactness = atr / (atr+width)
        slowness = normal_speed / (normal_speed+speed)
        score = 25 * (overlap + compactness + slowness + back_and_forth)
        if score <= cutoff:
            continue
        candidate = rows[start:end+1]
        result[end] = dict(id=f'PC{candles}_{end:06d}', kind='cluster', created=end,
            start=start, known_at=rows[end]['time']+timedelta(minutes=15),
            low=min(min(r['mid_open'], r['mid_close']) for r in candidate),
            high=max(max(r['mid_open'], r['mid_close']) for r in candidate),
            score=score, overlap=overlap, compactness=compactness,
            slowness=slowness, back_and_forth=back_and_forth,
            scoring_low=min(l), scoring_high=max(h))
    return result


def pivot_zone(rows, confirm_i, scale, side):
    pivot_i = confirm_i - scale
    if pivot_i <= 0:
        return None
    key = 'buy_body_high' if side == 'Buy' else 'sell_body_low'
    level = rows[pivot_i][key]
    left = pivot_i - 1
    while left >= 0 and rows[left][key] == level:
        left -= 1
    left += 1
    right = left + 1
    if right > confirm_i:
        return None
    prices = [rows[j]['mid_' + k] for j in (left, right) for k in ('open', 'close')]
    ranked = sorted(prices, reverse=side == 'Buy')
    low, high = sorted((ranked[0], ranked[2]))
    return dict(id=f'{"res" if side == "Buy" else "sup"}_{rows[pivot_i]["time"]:%Y%m%d_%H%M}',
        kind='pivot', created=confirm_i, low=low, high=high,
        known_at=rows[confirm_i]['time']+timedelta(minutes=15),
        pivot_time=rows[pivot_i]['time'], pair_first=rows[left]['time'], pair_second=rows[right]['time'])


def rejects_22_only(anchors):
    if any(a['source'].startswith('Asia') for a in anchors):
        return False
    pivots = [a for a in anchors if a['source'] in ('Current_day_pivot', 'IBOS_required_current_day_pivot')]
    return bool(pivots) and all(set(a['scales']) == {2} for a in pivots)


def apply_context_filters(rows, signals, params):
    """All decisions precede execution; outcomes and manual matches are unavailable."""
    if not (params.use_pivot_obstacles or params.use_active_price_cluster_stop_filter or params.reject_22_only_setups):
        return signals
    index = {r['time']: i for i, r in enumerate(rows)}
    confirmations = pivot_confirmations(rows, (params.pivot_obstacle_scale,)) if params.use_pivot_obstacles else {}
    clusters = cluster_windows(rows, params.price_cluster_candles, params.price_cluster_reference_bars,
                               params.price_cluster_min_score) if params.use_active_price_cluster_stop_filter else {}
    queries = {}
    for sn, signal in enumerate(signals):
        for en, event in enumerate(signal.get('entry_line_events', [])):
            i = index[event['line_time']]
            if event['available_from'] != rows[i]['time'] + timedelta(minutes=15):
                raise ValueError('Context filters require closed M15 candles')
            queries.setdefault(i, []).append((sn, en, signal, event))
    active = {'Buy': [], 'Sell': []}
    decisions = {}
    for i, row in enumerate(rows):
        for side, zones in active.items():
            keep = []
            for z in zones:
                limit = expires_at(z['known_at'], params.pivot_obstacle_expiry_months if z['kind']=='pivot' else params.price_cluster_expiry_months)
                if limit is not None and row['time']+timedelta(minutes=15) >= limit:
                    continue
                value = row['buy_body_high'] if side=='Buy' else row['sell_body_low']
                if z['kind']=='cluster':
                    value = row['mid_close']
                cancelled = value > z['high'] if side=='Buy' else value < z['low']
                if not cancelled:
                    keep.append(z)
            active[side] = keep
        for pivot in confirmations.get(i, []):
            side = pivot['side']
            z = pivot_zone(rows, i, params.pivot_obstacle_scale, side)
            if z and not any(p['kind']=='pivot' and abs(p['low']-z['low'])<1e-12 and abs(p['high']-z['high'])<1e-12 for p in active[side]):
                active[side].append(z)
        for sn, en, signal, event in queries.get(i, []):
            side = event.get('signal_direction', signal['direction'])
            body = event['run_high'] if side=='Buy' else event['run_low']
            start = index[signal['run_start_time']]
            hits = [z for z in active[side] if z['created'] < (i if z['kind']=='pivot' else start)
                    and z['low'] <= body <= z['high']]
            rejected = params.reject_22_only_setups and rejects_22_only(event.get('setup_anchors', []))
            reasons = sorted({z['kind'] for z in hits}) + (['2/2-only setup'] if rejected else [])
            decisions[sn, en] = dict(blocked=bool(reasons), reasons=reasons, body_extreme=body,
                evaluated_at=event['available_from'], hits=[dict(z) for z in hits], setup_22_rejected=bool(rejected))
        # Newly confirmed clusters cannot block a run already under way.
        if i in clusters:
            for side in active:
                active[side].append(dict(clusters[i]))
    result = []
    for sn, signal in enumerate(signals):
        candidate_events = signal.get('entry_line_events', [])
        audits = [dict(line_version=e['line_version'], **decisions[sn, en]) for en, e in enumerate(candidate_events)]
        allowed = [deepcopy(e) | {'context_filter_decision': decisions[sn, en]}
                   for en, e in enumerate(candidate_events) if not decisions[sn, en]['blocked']]
        updated = dict(signal, entry_line_events=allowed, context_filter_audit=audits,
            context_filter_removed_lines=len(candidate_events)-len(allowed),
            context_filter_original_lines=len(candidate_events),
            obstacle_hit=any(a['hits'] for a in audits))
        if candidate_events and not allowed:
            updated['status'] = 'Invalid'
            updated['reason'] = 'Context filters: ' + ', '.join(sorted({r for a in audits for r in a['reasons']}))
        elif allowed:
            updated['execution_start_time'] = allowed[0]['available_from']
            updated.update({key: allowed[-1][key] for key in ('entry', 'stop_loss', 'take_profit', 'setup_type', 'signal_text')})
            updated['entry_deadline'] = allowed[-1]['active_until']
        result.append(updated)
    return result
