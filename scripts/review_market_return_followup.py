"""Fixed-window return review; reuse the prior market and inventory policies."""
import hashlib
import json
from pathlib import Path

from review_market_transition_inventory import (
    ROOT, DAY, MINUTE, stamp, utc, load_rows, market_trace, restore_position,
    simulate, jsonable, ACCOUNT, BASIS,
)

CONFIG = ROOT / 'configs/research/market_return_followup_trial.json'
DOC = ROOT / 'docs/research/MARKET_RETURN_FOLLOWUP_TRIAL.md'
OUT = ROOT / 'reports/validation/market_return_followup_20260919'
PRIOR = ROOT / 'reports/validation/market_transition_inventory_20260919/review.json'


def first_return(market, side):
    failure = market['failure_ms']
    if failure is None:
        return None
    return next((p for p in market['points'] if p['time_ms'] > failure
                 and p['support']['side'] == side and p['state']['root'] is not None
                 and p['state']['root']['candidate']['formed_ms'] > failure), None)


def main():
    cfg = json.loads(CONFIG.read_text())
    old = json.loads(ACCOUNT.read_text())
    prior = json.loads(PRIOR.read_text())
    basis = json.loads(BASIS.read_text())
    seed = next(c for c in basis['cases'] if c['label'] == 'original_nine')['points'][-1]['updated_only']
    start, end = stamp(cfg['start_utc']), stamp(cfg['end_utc'])
    failure = stamp(cfg['known_failure_utc'])
    assert end - failure == cfg['followup_days_after_failure'] * DAY
    assert cfg['original_side'] == -1  # Prior inventory simulator is explicitly short-only.
    rows, sources = load_rows()
    structure_path = ROOT / 'configs/research/market_judgment_regime_review.json'
    structure = json.loads(structure_path.read_text())
    market = market_trace(rows, cfg, seed, structure)
    assert market['failure_ms'] == failure
    prior_end = stamp(prior['config']['end_utc'])
    assert [p for p in market['points'] if p['time_ms'] <= prior_end] == prior['market']['points']
    assert [e for e in market['events'] if e['time_ms'] <= prior_end] == prior['market']['events']
    returned = first_return(market, cfg['original_side'])
    # Persist the market classification before running any account comparison.
    OUT.mkdir(parents=True, exist_ok=True)
    selection = dict(config_sha256=hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
                     failure_ms=failure, opposition_ms=market['opposition_ms'],
                     return_ms=returned['time_ms'] if returned else None,
                     outcome='return_candidate_found' if returned else 'no_return_candidate_in_fixed_window',
                     no_profit_selection=True)
    (OUT / 'selection.json').write_text(json.dumps(selection, indent=2) + '\n')
    if returned:
        cutoff = returned['time_ms']
        prefix = market_trace([b for b in rows if b['end_ms'] <= cutoff],
                              dict(cfg, end_utc=utc(cutoff)), seed, structure)
        assert prefix['points'] == [p for p in market['points'] if p['time_ms'] <= cutoff]
        assert first_return(prefix, cfg['original_side']) == returned
    account_path = ROOT / cfg['account_config']
    account = json.loads(account_path.read_text())
    funding_path = ROOT / 'data/historical/btcusdc_public_20260917/funding_history.json'
    funding = json.loads(funding_path.read_text())
    initial = restore_position(old)
    args = dict(start=start, end=end, initial=initial,
                initial_peak=old['summary']['final']['peak_equity'],
                prior_max_dd=old['summary']['maximum_close_drawdown'],
                half_fraction=cfg['half_loss_fraction'], failure_ms=failure,
                opposition_ms=market['opposition_ms'])
    policies = {p: simulate(rows, funding, account=account, policy=p, **args) for p in cfg['policies']}
    for name, result in policies.items():
        serialized = jsonable(result)
        previous = prior['policies'][name]
        for key in ('ledger', 'decisions', 'states'):
            assert [x for x in serialized[key] if x['time_ms'] <= prior_end] == previous[key], (name, key)
        # No re-entry: all policies already flat in the prior 24-hour review.
        assert result['summary']['final']['position'].quantity == 0
        assert serialized['ledger'] == previous['ledger']
        assert serialized['summary']['final']['total_net'] == previous['summary']['final']['total_net']
        if returned:
            t = returned['time_ms']
            prefix = simulate([b for b in rows if b['end_ms'] <= t],
                              [f for f in funding if f['fundingTime'] <= t],
                              account=account, policy=name, **dict(args, end=t,
                              opposition_ms=market['opposition_ms'] if market['opposition_ms'] <= t else None))
            assert prefix['states'] == [s for s in result['states'] if s['time_ms'] <= t]
    sources += [CONFIG, DOC, ACCOUNT, BASIS, PRIOR, structure_path, account_path, funding_path, Path(__file__)]
    sources += [ROOT / p for p in prior['source_sha256'] if p not in {str(s.relative_to(ROOT)) for s in sources}]
    report = dict(config=cfg, selection=selection, market=market, policies=policies,
                  initial_position=initial, sensitivities={},
                  checks=dict(previous_market_prefix='PASS', previous_account_prefix='PASS',
                              return_market_prefix='PASS' if returned else 'NOT_APPLICABLE',
                              return_account_prefix='PASS' if returned else 'NOT_APPLICABLE',
                              no_reentry='PASS'), actual_orders=0, new_exposure_allowed=False,
                  source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (OUT / 'review.json').write_text(json.dumps(jsonable(report), ensure_ascii=False, indent=2) + '\n')
    prices = {b['end_ms']: b['close'] for b in rows}
    event_times = {e['time_ms']: e['kind'] for e in market['events']}
    lines = ['# 고정 7일 복귀 검토', '',
             '기존 사례의 무효화 이후 7일을 사전 지정했다. 개발 자료이며 신규 진입은 없다.', '',
             '결과: ' + selection['outcome'], '',
             '| UTC | 종가 | 사건 | 보유 기준 가격 | 현재 지지 방향 | 미판정/판정 이유 |',
             '| --- | ---: | --- | ---: | --- | --- |']
    for p in market['points']:
        t = p['time_ms']
        if t not in event_times and t != end:
            continue
        root = p['state']['root']
        price = root['candidate']['protected']['price'] if root else '없음'
        side = {1: '롱 후보', -1: '숏 후보', None: '불확실'}[p['support']['side']]
        lines.append(f"| {utc(t)} | {prices[t]} | {event_times.get(t, '관찰 종료')} | {price} | {side} | {p['support']['reason']} |")
    lines += ['', '기준 가격은 구조 가격이며 매물대 구간·평단·본절 가격이 아니다. 기준 갱신만으로 현재 지지나 새 진입을 승인하지 않는다.', '',
              '| 종료 정책 | 최종 잔량 BTC | 누적 순손익 USDC | 여력 대용치 USDC |',
              '| --- | ---: | ---: | ---: |']
    for name, a in policies.items():
        s = a['summary']['final']
        lines.append(f"| {name} | {s['position'].quantity} | {s['total_net']:.6f} | {s['free_margin_proxy']:.6f} |")
    lines += ['', '기본 체결 가정에서 모두 8월 17일에 종료되어 이후 비용·손익은 같다. 같은 거래의 관찰 연장이지 새 독립 표본이나 종료 정책의 추가 우위 증거가 아니다.', '',
              '재진입·추가·반대 주문 없음. 복귀 후보가 없으므로 재진입 비용과 성급한 종료의 비교는 미완료다. 4단계 계속, 5·6단계 보류.', '']
    (OUT / 'review.md').write_text('\n'.join(lines))
    print(json.dumps(dict(selection=selection, checks=report['checks'],
                         events=[dict(kind=e['kind'], utc=utc(e['time_ms'])) for e in market['events']],
                         returned=returned), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
