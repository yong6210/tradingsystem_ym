"""Descriptive attribution of frozen runs. No strategy edits or threshold search."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal as D, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_recovery_market import rows


def read_lines(path):
    with path.open() as stream:
        return [json.loads(line) for line in stream]


def utc(t):
    return datetime.fromtimestamp(t/1000,timezone.utc).strftime('%m-%d %H:%M:%S')


def quote_exit(raw, side, spread, tick):
    """Reproduce runner rounding, with an explicit spread assumption."""
    value=raw*(1-side*spread)
    rounded=(value/tick).to_integral_value(rounding=ROUND_FLOOR)*tick
    return rounded if side==1 else rounded+tick


def slippage_only_stop(side, stop, raw_open, previous_extreme, halfspread, slippage, tick):
    return (side*(quote_exit(raw_open,side,halfspread+slippage,tick)-stop)<=0
            and side*(quote_exit(raw_open,side,halfspread,tick)-stop)>0
            and side*(previous_extreme-stop)>0)


def review(directory, market):
    trace=read_lines(directory/'decisions.jsonl')
    ledger=read_lines(directory/'ledger.jsonl')
    config=json.loads((directory/'config.json').read_text())
    assessments={r['candidate_plan_id']:r for r in trace if r['action']=='entry_assessment'}
    accepted=[r['plan_id'] for r in trace if r['action']=='plan_accepted']
    orders={r['order']['id']:r for r in trace if r['action']=='order_intent'}
    grouped=defaultdict(list)
    active=None
    for event in ledger:
        if event['type']=='fill':
            active=orders[event['order_id']]['plan_id']
        if active is None:raise ValueError('unattributed funding')
        grouped[active].append(event)
    result=[]
    fee=D(config['controller']['costs']['fee'])
    halfspread=D(config['simulation']['half_spread_bps'])/10000
    slippage=D(config['controller']['costs']['slippage']);tick=D(config['controller']['costs']['tick'])
    for pid in accepted:
        a=assessments[pid];p=a['plan'];s=a['submission'];side=p['side']
        t=p['created_ms']; boundary=t//60000*60000
        entries=grouped[pid]
        fills=[r for r in entries if r['type']=='fill']
        first=fills[0];end=fills[-1]['time_ms']
        assert first['time_ms']==t and D(first['qty'])==D(p['initial_qty'])
        assert D(first['price'])==D(a['quote']['ask' if side==1 else 'bid'])
        for role in ('support','target'):
            assert all(x['evidence']['recorded_ms']<=t for x in s[role]['history']['events'])
        entry=D(first['price']);stop=D(p['stop']);target=D(s['contract']['first_response_price'])
        threes=[]
        # Use UTC-aligned completed 3m bars, exactly the information then available.
        for x in range(boundary-48*60000,boundary,60000):
            if (x+60000)%180000==0:
                block=[market[y] for y in range(x-120000,x+1,60000)]
                threes.append(dict(h=max(D(b['high']) for b in block),l=min(D(b['low']) for b in block),c=D(block[-1]['close'])))
        threes=threes[-15:]
        atr=sum(max(b['h']-b['l'],abs(b['h']-prev['c']),abs(b['l']-prev['c'])) for prev,b in zip(threes,threes[1:]))/14
        prior_close=D(market[boundary-60000]['close'])
        changes={str(m): (prior_close-D(market[boundary-(m+1)*60000]['close']))/D(market[boundary-(m+1)*60000]['close'])*10000 for m in (60,240)}
        history=s['support']['history']['events']
        excursions=[D(x) for x in s['reach']['excursions']]
        threshold=side*(target-prior_close)/prior_close
        reached=sum(x>=threshold for x in excursions)
        gross=sum(D(r['gross']) for r in fills)
        fees=sum(D(r['fee']) for r in fills)
        funding=sum(D(r['amount']) for r in entries if r['type']=='funding')
        reductions=[o for o in orders.values() if o['plan_id']==pid and o['order']['kind']=='reduce']
        triggers=[]
        for order in reductions:
            ot=order['time_ms'];minute=ot//60000*60000;kind='bar' if ot%60000==0 else 'quote'
            raw=D(market[minute]['open']) if kind=='quote' else D(market[minute-60000]['low' if side==1 else 'high'])
            # A diagnostic removing only the artificial slippage from the quoted
            # trigger. It is not an alternative strategy return or observed BBO.
            previous_extreme=D(market[minute-60000]['low' if side==1 else 'high'])
            triggers.append(dict(time_ms=ot,utc=utc(ot),reason=order['reason'],input_kind=kind,
                raw_price=raw,stop=stop,
                raw_common_boundary_breached=side*(raw-stop)<=0,
                previous_bar_common_boundary_breached=side*(previous_extreme-stop)<=0,
                common_stop_depends_on_slippage_quote=(order['reason']=='common_stop' and kind=='quote'
                    and slippage_only_stop(side,stop,raw,previous_extreme,halfspread,slippage,tick))))
        # Outcome-only candles: exclude the final fill's still-open minute.
        held=[market[x] for x in range(boundary,end//60000*60000,60000)]
        mfe=max([D(0)]+[side*(D(b['high' if side==1 else 'low'])-entry) for b in held])
        mae=max([D(0)]+[-side*(D(b['low' if side==1 else 'high'])-entry) for b in held])
        qty=D(first['qty'])
        result.append(dict(plan_id=pid,entry_utc=utc(t),side=side,
            entry_evidence=dict(decision_ms=t,entry_price=entry,last_completed_close=prior_close,stop=stop,target=target,
                stop_distance=side*(entry-stop),stop_to_prior_3m_atr=side*(entry-stop)/atr,prior_3m_atr=atr,
                zone_buffer=D(s['support']['buffer']),buffer_to_atr=D(s['support']['buffer'])/atr,
                support_age_minutes=D(t-p['support']['available_ms'])/60000,
                target_age_minutes=D(t-p['target']['available_ms'])/60000,
                prior_support_breaks=sum(x['kind']=='broken' for x in history),
                prior_support_reclaims=sum(x['kind']=='reclaimed' for x in history),
                last_event=history[-1]['kind'],context_change_bps=changes,
                historical_target_reach_samples=reached,total_samples=len(excursions),
                geometric_rr=side*(target-entry)/(side*(entry-stop)),
                planned_loss=D(a['assessment']['planned_loss']),initial_quantity=qty,
                flat_price_roundtrip_fee=2*entry*qty*fee),
            outcome=dict(exit_utc=utc(end),holding_minutes=D(end-t)/60000,gross=gross,fees=fees,funding=funding,net=gross-fees-funding,
                completed_bar_mfe=mfe,completed_bar_mae=mae,
                # No claim that OHLC favorable extremes were executable.
                target_touched_in_completed_holding_bars=any(side*(D(b['high' if side==1 else 'low'])-target)>=0 for b in held),
                adds=sum(r['kind']=='add' for r in fills),fills=len(fills),triggers=triggers)))
    total=sum(r['outcome']['net'] for r in result)
    summary=json.loads((directory/'summary.json').read_text())
    assert total==D(summary['cash_change'])
    assert len(result)==summary['campaigns']
    aggregate=dict(campaigns=len(result),wins=sum(r['outcome']['net']>0 for r in result),
        losses=sum(r['outcome']['net']<0 for r in result),
        long=sum(r['side']==1 for r in result),short=sum(r['side']==-1 for r in result),
        net=total,gross=sum(r['outcome']['gross'] for r in result),fees=sum(r['outcome']['fees'] for r in result),funding=sum(r['outcome']['funding'] for r in result),
        median_holding_minutes=statistics.median(r['outcome']['holding_minutes'] for r in result),
        median_stop_to_atr=statistics.median(r['entry_evidence']['stop_to_prior_3m_atr'] for r in result),
        previously_broken_supports=sum(r['entry_evidence']['prior_support_breaks']>0 for r in result),
        raw_target_touches=sum(r['outcome']['target_touched_in_completed_holding_bars'] for r in result),
        slippage_dependent_common_stops=sum(any(t['common_stop_depends_on_slippage_quote'] for t in r['outcome']['triggers']) for r in result),
        exit_reasons=Counter(t['reason'] for r in result for t in r['outcome']['triggers']))
    return result,aggregate


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args()
    freeze=ROOT/'reports/validation/recovery_market_v01_freeze_20260919/registration.json'
    registered=json.loads(freeze.read_text())
    assert all(hashlib.sha256((ROOT/k).read_bytes()).hexdigest()==v for k,v in registered['files'].items())
    data=rows(sorted((ROOT/'data/historical/recovery_holdout_20260919').glob('*.zip')))
    market={int(r['open_time']):r for r in data}
    assert len(market)==len(data)
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    report=dict(scope='POST_HOC_DESCRIPTIVE_NO_PARAMETER_SELECTION',strategy_unchanged=True,runs={})
    for label in ('base','stress'):
        directory=ROOT/f'reports/validation/recovery_market_v01_holdout_{label}_20260919'
        cases,aggregate=review(directory,market)
        report['runs'][label]=dict(aggregate=aggregate,cases=cases)
    base={r['plan_id']:r for r in report['runs']['base']['cases']}
    stress={r['plan_id']:r for r in report['runs']['stress']['cases']}
    report['matched_plan_ids']=sorted(base.keys()&stress.keys())
    report['input_hashes']={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
        for label in ('base','stress') for f in (ROOT/f'reports/validation/recovery_market_v01_holdout_{label}_20260919').glob('*.json*')}
    report['script_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (out/'review.json').write_text(json.dumps(report,default=str,ensure_ascii=False,indent=2)+'\n')
    lines=['# 동결 전략의 거래별 사후 검토','', 'UTC 시각. 근거는 진입 당시 자료, 손익·종료는 사후 관측이다. 수치를 최적화하지 않았다.','',
           '|조건|진입 UTC|방향|순손익 USDC|보유 분|진입 전 구간 붕괴 횟수|손절 거리/직전 ATR|종료 사유|슬리피지 호가 의존 공통 종료|',
           '|---|---|---|---:|---:|---:|---:|---|---|']
    for label in ('base','stress'):
        for r in report['runs'][label]['cases']:
            e,o=r['entry_evidence'],r['outcome']
            lines.append(f"|{label}|{r['entry_utc']}|{'롱' if r['side']==1 else '숏'}|{o['net']:.4f}|{o['holding_minutes']:.2f}|{e['prior_support_breaks']}|{e['stop_to_prior_3m_atr']:.2f}|{', '.join(t['reason'] for t in o['triggers'])}|{any(t['common_stop_depends_on_slippage_quote'] for t in o['triggers'])}|")
    (out/'cases.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v['aggregate'] for k,v in report['runs'].items()},default=str,indent=2))


if __name__=='__main__':main()
