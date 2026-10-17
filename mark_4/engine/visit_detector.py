"""Causal departure-and-return tracking around a confirmed body-pivot seed."""
from dataclasses import dataclass
from datetime import timedelta
from statistics import linear_regression, stdev


EPSILON = 1e-12


@dataclass(frozen=True)
class VisitConfig:
    side: str = 'Sell'
    pip_size: float = 0.0001
    membership_tolerance_pips: float = 4.0
    departure_pips: float = 5.0
    break_buffer_pips: float = 0.0
    minimum_visits: int = 3
    maximum_sd_pips: float | None = None
    bar_minutes: int = 15

    def __post_init__(self):
        if self.side not in ('Buy', 'Sell') or self.pip_size <= 0:
            raise ValueError('Invalid side or pip size.')
        if min(self.membership_tolerance_pips, self.departure_pips,
               self.break_buffer_pips) < 0 or self.minimum_visits < 2:
            raise ValueError('Distances must be nonnegative; at least two visits required.')
        if self.maximum_sd_pips is not None and self.maximum_sd_pips < 0:
            raise ValueError('Invalid SD ceiling.')


def describe_visits(visits, config):
    """SD and regression use one extreme per completed, confirmed visit."""
    selected = visits[-10:]
    count = len(selected)
    prices = [v['price'] for v in selected]
    sd = stdev(prices)/config.pip_size if count >= 2 else None
    slope = None
    if count >= 2:
        first_time = selected[0]['representative_time']
        x = [(v['representative_time']-first_time).total_seconds()/3600 for v in selected]
        y = [(p-prices[0])/config.pip_size for p in prices]
        if len(set(x)) > 1:
            slope = linear_regression(x, y).slope
    earlier = recent = ratio = None
    if count == 10:
        earlier = stdev(prices[:5])/config.pip_size
        recent = stdev(prices[5:])/config.pip_size
        ratio = recent/earlier if earlier > EPSILON else None
    repeated = len(visits) >= config.minimum_visits
    return dict(
        completed_visits=len(visits), statistical_sample_visits=count,
        sd_pips=sd, slope_pips_per_hour=slope,
        earlier_five_sd_pips=earlier, recent_five_sd_pips=recent,
        recent_earlier_sd_ratio=ratio,
        observed_low=min(prices) if prices else None,
        observed_high=max(prices) if prices else None,
        repeated_level_detected=repeated,
        sd_ceiling_passed=None if config.maximum_sd_pips is None or sd is None
        else sd <= config.maximum_sd_pips,
        tightening_status='insufficient_visits' if count < 10 else
        'undefined_flat_reference' if ratio is None else
        'tightening' if ratio < 1 else 'not_tightening',
        obstacle_exception_applied=False,
    )


def track_visits(rows, confirmations, seed, config, cutoff):
    """No marked example timestamps or trade outcomes enter this detector."""
    if seed['side'] != config.side:
        raise ValueError('Seed side must match detector side.')
    if seed['known_at'] > cutoff:
        return dict(state='seed_not_confirmed', visits=[], break_event=None,
                    measurements=describe_visits([], config))
    half_width = config.membership_tolerance_pips*config.pip_size
    low, high = seed['level']-half_width, seed['level']+half_width
    key = 'sell_body_low' if config.side == 'Sell' else 'buy_body_high'
    direction = 1 if config.side == 'Sell' else -1
    departure_price = (high if direction == 1 else low) + direction*config.departure_pips*config.pip_size
    events = sorted((e for e in confirmations if e['side'] == config.side),
                    key=lambda e:(e['known_at'], e['time'], e['scale']))
    position = 0
    known = {}
    closed = []
    active = dict(start=seed['time'], contacts=[], departed_at=None)
    armed = False
    broken = None
    visits = []

    for row in rows:
        close_time = row['time']+timedelta(minutes=config.bar_minutes)
        if row['time'] < seed['time']:
            continue
        if close_time > cutoff:
            break
        while position < len(events) and events[position]['known_at'] <= close_time:
            event = events[position]
            record = known.setdefault(event['id'], dict(
                id=event['id'], time=event['time'], level=event['level'],
                known_at=event['known_at'], scales=set()))
            record['scales'].add(event['scale'])
            position += 1

        observed_floor = min([seed['level']]+[v['price'] for v in visits])
        observed_ceiling = max([seed['level']]+[v['price'] for v in visits])
        break_price = (observed_floor-config.break_buffer_pips*config.pip_size
                       if config.side == 'Sell' else
                       observed_ceiling+config.break_buffer_pips*config.pip_size)
        is_broken = row['mid_close'] < break_price-EPSILON if config.side == 'Sell' else row['mid_close'] > break_price+EPSILON
        if is_broken and close_time >= seed['known_at']:
            broken = dict(candle_time=row['time'], known_at=close_time,
                          close=row['mid_close'], price=break_price,
                          clearance_pips=abs(row['mid_close']-break_price)/config.pip_size)
            break

        touch = low-EPSILON <= row[key] <= high+EPSILON
        if active is None and armed and touch:
            active = dict(start=row['time'], contacts=[], departed_at=None)
            armed = False
        if active is not None and touch:
            active['contacts'].append(dict(time=row['time'], body_price=row[key],
                                           spread_pips=row.get('spread_close', 0)/config.pip_size))
        departed = row['mid_close'] >= departure_price-EPSILON if config.side == 'Sell' else row['mid_close'] <= departure_price+EPSILON
        if active is not None and departed and active['contacts']:
            active['departed_at'] = close_time
            closed.append(active)
            active = None
            armed = True

        # An episode can finish before its pivot confirms. It becomes countable
        # only when the corresponding confirmation actually arrives.
        visits = []
        for episode in closed:
            contact_times = {c['time'] for c in episode['contacts']}
            pivots = [p for p in known.values() if p['time'] in contact_times
                      and low-EPSILON <= p['level'] <= high+EPSILON]
            if not pivots:
                continue
            extreme = min(p['level'] for p in pivots) if config.side == 'Sell' else max(p['level'] for p in pivots)
            # Equal adjacent pivots remain one visit; the last equally extreme
            # candle supplies the representative time once it is confirmed.
            representative = max((p for p in pivots if abs(p['level']-extreme) <= EPSILON),
                                 key=lambda p:p['time'])
            known_at = max(seed['known_at'], episode['departed_at'], representative['known_at'])
            first_counted_at = max(seed['known_at'], episode['departed_at'],
                                   min(p['known_at'] for p in pivots))
            visits.append(dict(
                start=episode['start'], last_contact=episode['contacts'][-1]['time'],
                departed_at=episode['departed_at'], known_at=known_at,
                first_counted_at=first_counted_at,
                representative_time=representative['time'], price=extreme,
                representative_scales=sorted(representative['scales']),
                pivot_ids=sorted(p['id'] for p in pivots),
                contacts=episode['contacts'],
                maximum_spread_pips=max(c['spread_pips'] for c in episode['contacts']),
            ))

    return dict(
        seed=seed, config=config.__dict__, cutoff=cutoff,
        membership_low=low, membership_high=high,
        departure_close_price=departure_price,
        state='broken' if broken else 'in_visit' if active else 'awaiting_return',
        visits=visits, unfinished_visit=active, break_event=broken,
        measurements=describe_visits(visits, config),
    )
