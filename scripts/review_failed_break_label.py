"""Audit descriptive breakout labels separately from the adopted market basis."""
import csv
import hashlib
import io
import json
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from zipfile import ZipFile

from review_market_judgment_regimes import (
    ROOT, CONFIG, MINUTE, DAY, load_rows, select_cases, prepare, snapshot,
    stable_context, utc, stamp,
)
from review_market_direction_continuity import advance, anchor_bars
from review_market_basis_revision import revise_basis, current_support, with_bounds

OUT = ROOT / 'reports/validation/failed_break_label_20260919'
BASIS = ROOT / 'reports/validation/market_basis_revision_20260919/review.json'
ACCOUNT = ROOT / 'reports/validation/first_candidate_account_20260919/review.json'


def raw_witness(archive, start, end):
    """Independent Decimal hourly aggregation, no selection helper arithmetic."""
    bars = {}
    with ZipFile(archive) as z, z.open(z.namelist()[0]) as f:
        for r in csv.DictReader(io.TextIOWrapper(f)):
            t = int(r['open_time']) + MINUTE
            if not start - 49 * 60 * MINUTE < t <= end:
                continue
            hour = ((t - 1) // (60 * MINUTE) + 1) * 60 * MINUTE
            bars.setdefault(hour, []).append((t, *(D(r[k]) for k in ('high', 'low', 'close'))))
    hours = []
    for t, b in sorted(bars.items()):
        assert len(b) == 60 and [x[0] for x in b] == list(range(t - 59 * MINUTE, t + 1, MINUTE))
        hours.append(dict(time_ms=t, high=max(x[1] for x in b), low=min(x[2] for x in b), close=b[-1][3]))
    prior = [b for b in hours if b['time_ms'] <= start]
    block = [b for b in hours if b['time_ms'] > start]
    unit = sum(b['high'] - b['low'] for b in prior[-24:]) / 24
    move = prior[-1]['close'] - prior[-49]['close']
    assert move <= -2 * unit and block[-1]['close'] < prior[-1]['close']
    level = max(b['high'] for b in prior[-24:])
    for i, b in enumerate(block):
        if b['high'] > level:
            returned = next((x for x in block[i + 1:] if x['close'] < level), None)
            if returned:
                return dict(level=level, breach=b, returned=returned,
                            prior_move=move, daily_net=block[-1]['close']-prior[-1]['close'],
                            daily_high=max(x['high'] for x in block), label_available_ms=end)
    raise AssertionError('frozen selected label has no raw witness')


def account_at(report, t):
    """Replay fills and funding independently up to the close-time snapshot."""
    q = D(0); avg = None; gross = D(0); paid = D(0)
    for e in report['ledger']:
        et = e['time_ms']
        if e['kind'] == 'funding' and et <= t:
            assert D(e['quantity']) == q
            paid += D(e['payment'])
        elif e['kind'] == 'fill' and et < t:
            amount, price = D(e['quantity']), D(e['price'])
            if e['action'] == 'increase':
                avg = ((q * avg if q else D(0)) + amount * price) / (q + amount)
                q += amount
            else:
                assert amount <= q
                if e['action'] == 'retracement_reduce':
                    assert amount >= q / 2
                gross += amount * (avg - price)
                q -= amount
                if not q:
                    avg = None
            paid += D(e['fee'])
    s = next(x for x in report['states'] if x['time_ms'] == t)
    assert q == D(s['quantity']) and (avg == D(s['average']) if avg is not None else s['average'] is None)
    assert abs(gross - D(s['realized_gross'])) < D('1e-12')
    assert abs(paid - D(s['paid_costs'])) < D('1e-12')
    return s


def main():
    rows, sources = load_rows(); cfg = json.loads(CONFIG.read_text())
    selected, _ = select_cases(rows, cfg)
    chosen = next(x['case'] for x in selected if x['label'] == 'failed_break_return')
    old = next(c for c in json.loads(BASIS.read_text())['cases'] if c['label'] == 'failed_break_return')
    assert (chosen['start_ms'], chosen['end_ms']) == (old['start_ms'], old['end_ms'])
    start, end = old['start_ms'], old['end_ms']
    archive = ROOT / 'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    witness = raw_witness(archive, start, end)
    assert witness['level'] == D(str(chosen['metrics']['prior_high']))
    seed = old['points'][0]['updated_only']
    assert seed['last_ms'] == start and seed['root']['candidate']['side'] == -1
    times = sorted(set(range(start + 15 * MINUTE, end + 1, 15 * MINUTE)) |
                   {p['time_ms'] for p in old['points'] if p['time_ms'] > start} |
                   {stamp('2026-08-16T21:43:00Z')})
    def run(cutoff):
        known = [b for b in rows if b['end_ms'] <= cutoff]
        prepared = [prepare(known, start - d * DAY, cutoff, cfg) for d in cfg['history_days']]
        state = deepcopy(seed); points = {}; events = []
        for t in times:
            if t > cutoff:
                break
            views = [snapshot(p, t) for p in prepared]
            state, e = advance(state, t=t, context=stable_context(views), bars=anchor_bars(prepared[-1], state, t))
            if e: events.append(e)
            state, e = revise_basis(state, views, t)
            if e: events.append(e)
            points[t] = dict(time_ms=t, utc=utc(t), state=deepcopy(state), views=views,
                             support=current_support(state, with_bounds(views, prepared, state, t), t))
        return points, events
    points, events = run(end)
    for key in ('breach', 'returned'):
        t = witness[key]['time_ms']; prefix, pe = run(t)
        assert prefix == {k:v for k,v in points.items() if k <= t}
        assert pe == [e for e in events if e['time_ms'] <= t]
    for p in old['points'][1:]:
        assert points[p['time_ms']]['state'] == p['updated_only']
        assert points[p['time_ms']]['support'] == p['guarded']
    failures = [e for e in events if e['kind'] == 'basis_invalidated']
    assert not failures
    original_level = seed['root']['candidate']['protected']['price']
    assert witness['daily_high'] < D(str(original_level))
    account = json.loads(ACCOUNT.read_text())
    account_config = ROOT/'configs/research/first_candidate_case_trial.json'
    assumptions = json.loads(account_config.read_text())
    capital, leverage = D(assumptions['starting_equity']), D(assumptions['leverage'])
    checkpoints = sorted({stamp('2026-08-16T16:09:00Z'), stamp('2026-08-16T16:12:00Z'), witness['breach']['time_ms'],
                          witness['returned']['time_ms'], stamp('2026-08-16T21:41:00Z'),
                          stamp('2026-08-16T21:43:00Z'), end})
    table = []
    prices = {b['end_ms']:b['close'] for b in rows}
    for t in checkpoints:
        s = account_at(account, t)
        expected_net = D(s['realized_gross'])-D(s['paid_costs'])+D(s['quantity'])*(D(s['average'])-D(str(prices[t])))
        assert abs(expected_net-D(s['total_net'])) < D('1e-9')
        assert abs(D(s['equity'])-(capital+expected_net)) < D('1e-9')
        assert abs(D(s['free_margin_proxy'])-(capital+expected_net-D(s['quantity'])*D(str(prices[t]))/leverage)) < D('1e-9')
        table.append(dict(utc=utc(t), price=prices[t], market=points[t], account=s))
    result = dict(status='development_label_role_audit', case=chosen, witness=witness,
                  interpretation='prior_day_high_excursion_and_later_return_without_adopted_basis_failure',
                  original_basis=seed['root'], points=list(points.values()), events=events, table=table,
                  checks=dict(raw_decimal_label_witness='PASS', causal_market_prefix='PASS',
                              previous_checkpoints='PASS', independent_inventory='PASS',
                              mark_equity_and_capacity='PASS', no_main_basis_failure='PASS'),
                  orders_generated=0, new_exposure_allowed=False)
    sources += [CONFIG, BASIS, ACCOUNT, account_config, Path(__file__), ROOT/'scripts/review_market_basis_revision.py',
                ROOT/'scripts/review_market_direction_continuity.py',ROOT/'scripts/review_market_judgment_regimes.py',
                ROOT/'app/research/recovery/protected_structure.py',ROOT/'app/research/recovery/structure_review.py']
    result['source_sha256'] = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'review.json').write_text(json.dumps(result, default=str, ensure_ascii=False, indent=2)+'\n')
    lines = ['# 전일 고점 돌파 실패와 주된 숏 기준의 역할 대조', '',
             '| UTC | 종가 | 현재 방향 후보 | 주된 기준 | BTC 잔량 | 평단 | 실현총손익 | 누적 비용 | 평가 순손익 | 여력 대용치 |',
             '| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for x in table:
        m=x['market'];s=x['account'];root=m['state']['root']
        lines.append(f"| {x['utc']} | {x['price']} | {m['support']['side']} | {root['candidate']['protected']['price'] if root else None} | {s['quantity']} | {s['average']} | {s['realized_gross']} | {s['paid_costs']} | {s['total_net']} | {s['free_margin_proxy']} |")
    lines += ['', '방향 -1은 시험 숏, None은 불확실이다. 기존 조건부 계좌이며 신규 주문·정책 변경은 없다.',
              '전일 고점 63,107.2는 구조 경계이며 매물대나 본절이 아니다. 라벨 확정에는 일 마감 정보가 필요하다.', '']
    (OUT/'review.md').write_text('\n'.join(lines))
    print(json.dumps(dict(witness=witness,checks=result['checks'],table=[dict(utc=x['utc'],side=x['market']['support']['side'],account=x['account']) for x in table]),default=str,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
