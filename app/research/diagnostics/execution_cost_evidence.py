"""Q001: displayed book decomposition, not a fill or strategy performance model."""
from decimal import Decimal as D
from math import ceil

NS = 10**9
QTY = D('.001')
BPS = D(10000)


def validate_grid(grid):
    if not grid:
        raise ValueError('empty grid')
    for i, point in enumerate(grid):
        if i and point['time_ns'] != grid[i - 1]['time_ns'] + NS:
            raise ValueError('non-contiguous grid')
        if not point['valid']:
            continue
        bids, asks = point['bids'], point['asks']
        if len(bids) != 5 or len(asks) != 5:
            raise ValueError('not five levels')
        for side, levels in ((-1, bids), (1, asks)):
            if any(D(p) <= 0 or D(q) <= 0 for p, q in levels):
                raise ValueError('nonpositive level')
            if any(side * (D(b[0]) - D(a[0])) <= 0
                   for a, b in zip(levels, levels[1:])):
                raise ValueError('unsorted levels')
        if D(bids[0][0]) >= D(asks[0][0]):
            raise ValueError('crossed/locked book')
        if D(point['mid']) != (D(bids[0][0]) + D(asks[0][0])) / 2:
            raise ValueError('mid mismatch')
        t = point['time_ns']
        if not 0 <= t - point['last_depth_ns'] <= NS:
            raise ValueError('depth freshness')
        if not 0 <= t - point['last_mark_ns'] <= 3 * NS:
            raise ValueError('mark freshness')
        if t - point['quality_reset_ns'] < 60 * NS:
            raise ValueError('warmup')


def displayed_leg(point, side, qty=QTY):
    if side not in (-1, 1) or qty <= 0:
        raise ValueError('invalid direction/quantity')
    if not point['valid']:
        return {'status': 'INVALID_GRID'}
    levels = point['asks'] if side == 1 else point['bids']
    remaining, quote = qty, D(0)
    for price, size in levels:
        take = min(remaining, D(size))
        quote += D(price) * take
        remaining -= take
        if remaining == 0:
            break
    if remaining:
        return {'status': 'INSUFFICIENT_VISIBLE_DEPTH', 'unfilled_qty': str(remaining)}
    mid, best, vwap = D(point['mid']), D(levels[0][0]), quote / qty
    half = side * (best - mid) / mid * BPS
    depth = side * (vwap - best) / mid * BPS
    total = side * (vwap - mid) / mid * BPS
    assert abs(half + depth - total) < D('1e-20')
    return dict(status='COMPLETE_DISPLAYED_PROXY', vwap=str(vwap),
                quote=str(quote), below_50_usdc=quote < D(50),
                half_spread_bps=str(half), depth_bps=str(depth), total_bps=str(total))


def diagnose(grid):
    validate_grid(grid)
    output = []
    for i, point in enumerate(grid):
        t = point['time_ns']
        for side in (1, -1):
            current = displayed_leg(point, side)
            row = dict(time_ns=t, side=side, immediate=current)
            window = grid[i:i + 4]
            if len(window) < 4:
                delayed = dict(status='END_OF_INTERVAL')
            elif not all(p['valid'] for p in window):
                delayed = dict(status='INVALID_PATH')
            elif current['status'] != 'COMPLETE_DISPLAYED_PROXY':
                delayed = dict(status='INITIAL_DEPTH_INSUFFICIENT')
            else:
                future = window[-1]
                target = displayed_leg(future, side)
                if target['status'] != 'COMPLETE_DISPLAYED_PROXY':
                    delayed = dict(status='DELAYED_DEPTH_INSUFFICIENT')
                else:
                    initial_mid, final_mid = D(point['mid']), D(future['mid'])
                    best = D(future['asks' if side == 1 else 'bids'][0][0])
                    vwap = D(target['vwap'])
                    move = side * (final_mid - initial_mid) / initial_mid * BPS
                    half = side * (best - final_mid) / initial_mid * BPS
                    depth = side * (vwap - best) / initial_mid * BPS
                    total = side * (vwap - initial_mid) / initial_mid * BPS
                    assert abs(move + half + depth - total) < D('1e-20')
                    delayed = dict(status='COMPLETE_DISPLAYED_PROXY',
                                   vwap=str(vwap), quote=target['quote'],
                                   below_50_usdc=target['below_50_usdc'],
                                   move_bps=str(move), half_spread_bps=str(half),
                                   depth_bps=str(depth), total_bps=str(total),
                                   change_from_immediate_bps=str(total - D(current['total_bps'])))
            row['delayed'] = delayed
            output.append(row)
    return output


def stats(values):
    ordered = sorted(D(v) for v in values)
    if not ordered:
        return dict(n=0, mean=None, minimum=None, median=None, p95=None, maximum=None)
    n = len(ordered)
    return dict(n=n, mean=str(sum(ordered) / n), minimum=str(ordered[0]),
                median=str(ordered[ceil(D('.5') * n) - 1]),
                p95=str(ordered[ceil(D('.95') * n) - 1]), maximum=str(ordered[-1]))


def summarize(rows):
    result = {}
    for side, name in ((1, 'buy'), (-1, 'sell')):
        result[name] = {}
        for phase in ('immediate', 'delayed'):
            entries = [r[phase] for r in rows if r['side'] == side]
            statuses = {s: sum(r['status'] == s for r in entries)
                        for s in sorted({r['status'] for r in entries})}
            good = [r for r in entries if r['status'] == 'COMPLETE_DISPLAYED_PROXY']
            keys = ['half_spread_bps', 'depth_bps', 'total_bps']
            if phase == 'delayed':
                keys += ['move_bps', 'change_from_immediate_bps']
            result[name][phase] = dict(statuses=statuses,
                below_50_usdc=sum(r['below_50_usdc'] for r in good),
                metrics={k: stats(r[k] for r in good) for k in keys})
    # One observation per timestamp, NOT the duplicated buy/sell directions.
    result['absolute_mid_move_3s_bps'] = stats(
        abs(D(r['delayed']['move_bps'])) for r in rows
        if r['side'] == 1 and r['delayed']['status'] == 'COMPLETE_DISPLAYED_PROXY')
    return result
