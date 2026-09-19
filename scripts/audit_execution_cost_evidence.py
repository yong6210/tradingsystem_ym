"""Independent rational-arithmetic audit; no diagnostic helper import."""
from fractions import Fraction as F


def audit(grid, rows):
    assert len(rows) == 2 * len(grid)
    checked = 0

    def equal(actual, expected):
        assert abs(F(actual) - expected) < F(1, 10**18), (actual, expected)

    def price(point, side):
        if not point['valid']:
            return None
        levels = point['asks' if side == 1 else 'bids']
        # Cumulative interval overlap, independent of the producer's remaining loop.
        filled, cash, cap = F(0), F(0), F(1, 1000)
        for p, q in levels:
            after = filled + F(q)
            cash += F(p) * max(F(0), min(cap, after) - min(cap, filled))
            filled = after
        return cash / cap if filled >= cap else None

    for i, p in enumerate(grid):
        for offset, side in enumerate((1, -1)):
            row = rows[2 * i + offset]
            assert (row['time_ns'], row['side']) == (p['time_ns'], side)
            immediate = row['immediate']
            v = price(p, side)
            if not p['valid']:
                assert immediate['status'] == 'INVALID_GRID'
            elif v is None:
                assert immediate['status'] == 'INSUFFICIENT_VISIBLE_DEPTH'
            else:
                assert immediate['status'] == 'COMPLETE_DISPLAYED_PROXY'
                mid = F(p['mid'])
                best = F(p['asks' if side == 1 else 'bids'][0][0])
                for k, expected in dict(vwap=v, quote=v / 1000,
                        half_spread_bps=side * (best / mid - 1) * 10000,
                        depth_bps=side * (v - best) * 10000 / mid,
                        total_bps=side * (v / mid - 1) * 10000).items():
                    equal(immediate[k], expected)
                assert immediate['below_50_usdc'] == (v / 1000 < 50)
                checked += 1
            delayed = row['delayed']
            if i + 3 >= len(grid):
                expected_status = 'END_OF_INTERVAL'
            elif any(not grid[j]['valid'] for j in range(i, i + 4)):
                expected_status = 'INVALID_PATH'
            elif v is None:
                expected_status = 'INITIAL_DEPTH_INSUFFICIENT'
            elif price(grid[i + 3], side) is None:
                expected_status = 'DELAYED_DEPTH_INSUFFICIENT'
            else:
                expected_status = 'COMPLETE_DISPLAYED_PROXY'
                target = grid[i + 3]
                final_v = price(target, side)
                mid, final_mid = F(p['mid']), F(target['mid'])
                best = F(target['asks' if side == 1 else 'bids'][0][0])
                for k, expected in dict(vwap=final_v, quote=final_v / 1000,
                        move_bps=side * (final_mid - mid) * 10000 / mid,
                        half_spread_bps=side * (best - final_mid) * 10000 / mid,
                        depth_bps=side * (final_v - best) * 10000 / mid,
                        total_bps=side * (final_v / mid - 1) * 10000,
                        change_from_immediate_bps=side * (final_v - v) * 10000 / mid).items():
                    equal(delayed[k], expected)
                assert delayed['below_50_usdc'] == (final_v / 1000 < 50)
                checked += 1
            assert delayed['status'] == expected_status
    return dict(rows=len(rows), complete_leg_calculations=checked)


def audit_summary(rows, summary):
    def verify_stat(raw, actual):
        values = sorted(F(x) for x in raw)
        n = len(values)
        assert actual['n'] == n
        if not n:
            assert all(actual[k] is None for k in ('mean', 'minimum', 'median', 'p95', 'maximum'))
            return
        expected = dict(mean=sum(values) / n, minimum=values[0],
                        median=values[(n + 1) // 2 - 1],
                        p95=values[(95 * n + 99) // 100 - 1], maximum=values[-1])
        for k, v in expected.items():
            assert abs(F(actual[k]) - v) < F(1, 10**18)

    for side, name in ((1, 'buy'), (-1, 'sell')):
        for phase in ('immediate', 'delayed'):
            entries = [r[phase] for r in rows if r['side'] == side]
            s = summary[name][phase]
            assert s['statuses'] == {k: sum(e['status'] == k for e in entries)
                                     for k in {e['status'] for e in entries}}
            good = [e for e in entries if e['status'] == 'COMPLETE_DISPLAYED_PROXY']
            assert s['below_50_usdc'] == sum(e['below_50_usdc'] for e in good)
            keys = {'half_spread_bps', 'depth_bps', 'total_bps'}
            if phase == 'delayed':
                keys |= {'move_bps', 'change_from_immediate_bps'}
            assert set(s['metrics']) == keys
            for k, v in s['metrics'].items():
                verify_stat([e[k] for e in good], v)
    verify_stat([abs(F(r['delayed']['move_bps'])) for r in rows
                 if r['side'] == 1 and r['delayed']['status'] == 'COMPLETE_DISPLAYED_PROXY'],
                summary['absolute_mid_move_3s_bps'])
