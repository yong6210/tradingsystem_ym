"""Recheck selected entry at a later open, then reuse the reduction ledger."""
import hashlib,json
from copy import deepcopy
from pathlib import Path

from review_local_failure_inventory import simulate
from review_six_case_entry_scan import scan_case
from review_market_judgment_regimes import (
    ROOT,CONFIG,MINUTE,DAY,load_rows,prepare,snapshot,stable_context,action_review,
    utc,stamp,PositionExample,ExampleCosts,dec,jsonable,
)
from review_market_basis_revision import revise_basis,current_support,with_bounds
from review_market_direction_continuity import advance,anchor_bars
from app.research.recovery.cycling_admission import Capacity
from app.research.recovery.recovery_capacity_review import review_capacity
from app.research.recovery.position_alternatives import alternative
from app.research.recovery.round_trip_review import round_trip

TRIAL=ROOT/'configs/research/selected_entry_account_trial.json'
OUT=ROOT/'reports/validation/selected_entry_account_20260920'
SCAN=ROOT/'reports/validation/six_case_entry_scan_20260920/review.json'


def opening_check(candidate,mark,opening,side,account,target):
    costs=ExampleCosts(*(account[k] for k in ('fee','half_spread','slippage','tick','step','leverage')))
    flat=PositionExample(-1,0,None,0,0,0,account['starting_equity'])
    cap=Capacity(opening,flat.starting_equity,account['reserve_margin'],dec(mark)/costs.leverage,
                 account['maximum_total_quantity'],account['initial_stress_budget'],account['stress_moves'])
    room=review_capacity(flat,costs,mark=mark,quote_ms=opening,capacity=cap,requested=candidate['result']['quantity'],
                         liquidity_qty=account['assumed_liquidity_quantity'],minimum_quantity=account['minimum_quantity'],
                         minimum_notional=account['minimum_notional'],now_ms=opening,max_age_ms=0)
    q=room['capacity_quantity'] or dec(0);net=round_trip(costs,side=-1,quantity=q,entry_mark=mark,exit_mark=target) if q else None
    reason=('opening_direction_not_short' if side!=-1 else 'opening_above_local_resistance' if dec(mark)>dec(candidate['reaction']['price'])
            else 'opening_no_capacity' if q<=0 else 'opening_no_positive_net_room' if net['net']<=0 else None)
    fill=alternative(flat,costs,mark=mark,action='increase',quantity=q,stress_moves=account['stress_moves']) if reason is None else None
    return dict(status='filled_hypothetically' if fill else 'entry_cancelled',reason=reason,capacity=room,round_trip=net,
                fill=fill,unfilled_cancelled=dec(candidate['result']['quantity'])-(q if fill else 0),actual_orders=0)


def main():
    trial=json.loads(TRIAL.read_text());scan=json.loads(SCAN.read_text());candidate=scan['selection']['first']
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in scan['source_sha256'].items())
    decision=stamp(trial['decision_utc']);end=stamp(trial['end_utc']);assert candidate['time_ms']==decision
    assert dec(trial['target_mark'])==dec(candidate['target']['price'])
    account_path=ROOT/trial['account_config'];account=json.loads(account_path.read_text());cfg=json.loads(CONFIG.read_text())
    basis_path=ROOT/scan['config']['case_source'];old=next(c for c in json.loads(basis_path.read_text())['cases'] if c['label']==candidate['label'])
    rows,sources=load_rows();bar=next(b for b in rows if b['end_ms']-MINUTE>decision)
    opening=bar['end_ms']-MINUTE;mark=bar['open'];assert opening==decision+MINUTE
    known=[b for b in rows if b['end_ms']<=opening]
    prepared=[prepare(known,old['start_ms']-d*DAY,opening,cfg) for d in cfg['history_days']]
    views=[snapshot(p,opening) for p in prepared]
    state,_=advance(candidate['state'],t=opening,context=stable_context(views),bars=anchor_bars(prepared[-1],candidate['state'],opening))
    state,_=revise_basis(state,views,opening)
    support=current_support(state,with_bounds(views,prepared,state,opening),opening)
    market=next(c for c in scan['cases'] if c['label']==candidate['label'])
    target_hit=next((b['end_ms'] for b in rows if opening<b['end_ms']<=end and dec(b['low'])<=dec(trial['target_mark'])),None)
    funding_path=ROOT/'data/historical/btcusdc_public_20260917/funding_history.json';funding=json.loads(funding_path.read_text())
    paths={};variants=dict(base={},fee_4bp=dict(fee='0.0004'),slippage_5bp=dict(slippage='0.0005'),liquidity_003=dict(assumed_liquidity_quantity='0.003'),no_liquidity=dict(assumed_liquidity_quantity='0'))
    for name,changes in variants.items():
        cost=dict(account,**changes);entry=opening_check(candidate,mark,opening,support['side'],cost,trial['target_mark'])
        path=dict(entry=entry,entry_time_ms=opening,entry_mark=mark,account=cost,continuation=None,addition_reviews=[])
        if entry['fill']:
            p=entry['fill']['after']
            args=dict(start=opening,end=end,initial=p,initial_peak=p.starting_equity,prior_dd=0,account=cost,
                      loss_ms=None,target_ms=target_hit,target_fraction=account['reduction_fraction'])
            result=simulate(rows,funding,**args);path['continuation']=result
            states={s['time_ms']:s for s in result['states']}
            costs=ExampleCosts(*(cost[k] for k in ('fee','half_spread','slippage','tick','step','leverage')))
            # Restricted reduction replay is valid only if every later add opportunity is rejected.
            for point in market['points']:
                t=point['time_ms']
                if not opening<t<=end or not point['reactions']['-1']:continue
                current=states[t]['position'];group=point['reactions']['-1']
                fresh=[x for x in group if min(x['pivot_bar_end_ms'],x['available_ms'])>decision]
                reaction=(fresh or group)[0]
                review=action_review(context=dict(side=point['support']['side'],root=point['state']['root']),position=current,
                    costs=costs,mark=point['mark'],t=t,account=cost,reaction=reaction,target=candidate['target'],last_growth=decision)
                path['addition_reviews'].append(dict(time_ms=t,utc=utc(t),reaction=reaction,result=review))
                if review['action']=='add_candidate':raise ValueError('new add candidate requires full growth replay; result not published')
            for t in sorted({end,opening+MINUTE}|({target_hit} if target_hit else set())|
                            {e['time_ms']+MINUTE for e in result['ledger'] if e['kind']=='fill'}):
                prefix=simulate([b for b in rows if b['end_ms']<=t],[f for f in funding if f['fundingTime']<=t],
                                **dict(args,end=t,target_ms=target_hit if target_hit is not None and target_hit<=t else None))
                assert prefix['states']==[s for s in result['states'] if s['time_ms']<=t]
                assert prefix['decisions']==[d for d in result['decisions'] if d['time_ms']<=t]
        paths[name]=path
    if target_hit:
        prefix=scan_case([b for b in rows if b['end_ms']<=target_hit],cfg,account,old,target_hit)
        assert jsonable(prefix['points'])==[p for p in market['points'] if p['time_ms']<=target_hit]
    sources += [TRIAL,SCAN,ROOT/trial['selection_source'],CONFIG,account_path,basis_path,funding_path,Path(__file__),
                ROOT/'scripts/review_local_failure_inventory.py',ROOT/'scripts/review_six_case_entry_scan.py']
    sources += [ROOT/p for p in scan['source_sha256'] if ROOT/p not in sources]
    result=dict(config=trial,candidate=candidate,opening=dict(time_ms=opening,mark=mark,state=state,support=support),
                target_hit_ms=target_hit,paths=paths,checks=dict(opening_known_data_only='PASS',no_unhandled_additions='PASS',
                account_prefix='PASS',target_market_prefix='PASS'),new_exposure_allowed=False,actual_orders=0,
                source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'review.json').write_text(json.dumps(jsonable(result),ensure_ascii=False,indent=2)+'\n')
    lines=['# 선정 후보의 이후 시가와 조건부 계좌','','| 가정 | 진입 결과 | 체결 BTC | 최종 잔량 | 평가 순손익 | 가상 청산 순손익 |','| --- | --- | ---: | ---: | ---: | ---: |']
    for name,p in paths.items():
        f=p['continuation']['summary']['final'] if p['continuation'] else None
        lines.append(f"| {name} | {p['entry']['reason'] or '조건부 체결'} | {p['entry']['fill']['after'].quantity if f else 0} | {f['position'].quantity if f else 0} | {f['total_net'] if f else '거래 없음'} | {f['net_if_closed'] if f else '거래 없음'} |")
    lines+=['','실제 주문·강제 종료 없음. 진입 견적과 실제 이후 시가의 조건부 체결을 구분한다.','']
    (OUT/'review.md').write_text('\n'.join(lines));print('\n'.join(lines));print('target',utc(target_hit) if target_hit else None)


if __name__=='__main__':main()
