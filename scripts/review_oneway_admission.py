"""Check the preselected adverse day without manufacturing an approved entry."""
import csv,hashlib,io,json
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from zipfile import ZipFile

from review_market_judgment_regimes import (
    ROOT,CONFIG,MINUTE,DAY,load_rows,select_cases,prepare,snapshot,stable_context,
    target_at,action_review,utc,stamp,PositionExample,ExampleCosts,dec,jsonable,
)
from review_market_basis_revision import revise_basis,current_support,with_bounds
from review_market_direction_continuity import advance,anchor_bars
from review_first_candidate_account import contacts

AUDIT=ROOT/'configs/research/oneway_admission_audit.json'
BASIS=ROOT/'reports/validation/market_basis_revision_20260919/review.json'
GENERAL=ROOT/'reports/validation/market_judgment_regimes_20260919/review.json'
OUT=ROOT/'reports/validation/oneway_admission_20260919'


def reactions_for(rows,end):
    shorts=contacts(rows,end)
    reflected=[dict(b,open=200000-b['open'],high=200000-b['low'],low=200000-b['high'],close=200000-b['close']) for b in rows]
    longs=contacts(reflected,end)
    for group in longs.values():
        for p in group:p['price']=200000-p['price']
    return {-1:shorts,1:longs}


def main():
    audit=json.loads(AUDIT.read_text());cfg=json.loads(CONFIG.read_text());rows,sources=load_rows()
    selected,_=select_cases(rows,cfg);case=next(c['case'] for c in selected if c['label']==audit['case_label'])
    start,end=stamp(audit['start_utc']),stamp(audit['end_utc']);assert (start,end)==(case['start_ms'],case['end_ms'])
    basis=json.loads(BASIS.read_text());old=next(c for c in basis['cases'] if c['label']==audit['case_label'])
    original=next(c for c in json.loads(GENERAL.read_text())['cases'] if c['label']==audit['case_label'])
    seed=old['points'][0]['updated_only'];assert seed['last_ms']==start
    account_path=ROOT/cfg['account_config'];account=json.loads(account_path.read_text())
    costs=ExampleCosts(*(account[k] for k in ('fee','half_spread','slippage','tick','step','leverage')))
    funding_path=ROOT/'data/historical/btcusdc_public_20260917/funding_history.json';funding=json.loads(funding_path.read_text())
    bytime={b['end_ms']:b for b in rows};initial_mark=bytime[start]['close']
    def run(cutoff):
        known=[b for b in rows if b['end_ms']<=cutoff]
        prepared=[prepare(known,start-days*DAY,cutoff,cfg) for days in cfg['history_days']]
        reactions=reactions_for(prepared[-1]['rows'],cutoff)
        times=sorted(set(range(start,cutoff+1,15*MINUTE))|
                     {t for g in reactions.values() for t in g if start<=t<=cutoff}|
                     {p['time_ms'] for p in old['points'] if p['time_ms']<=cutoff})
        state=deepcopy(seed);points=[];events=[]
        target=target_at(prepared[-1],start,-1,initial_mark)
        hit=next((b['end_ms'] for b in known if start<b['end_ms']<=cutoff and target and b['low']<=target['price']),None)
        for t in times:
            views=[snapshot(p,t) for p in prepared];context=stable_context(views)
            if t>start:
                state,e=advance(state,t=t,context=context,bars=anchor_bars(prepared[-1],state,t))
                if e:events.append(e)
                state,e=revise_basis(state,views,t)
                if e:events.append(e)
            support=current_support(state,with_bounds(views,prepared,state,t),t)
            gate=dict(side=support['side'],root=state['root']);mark=bytime[t]['close']
            flat=PositionExample(1,0,None,0,0,0,account['starting_equity'])
            price=costs.execution(initial_mark,-1);quantity=dec('.006')
            paid=quantity*price*costs.fee+sum((-quantity*dec(f['markPrice'])*dec(f['fundingRate']) for f in funding if start<f['fundingTime']<=t),dec(0))
            short=PositionExample(-1,quantity,price,0,paid,paid,account['starting_equity'])
            review={}
            for name,p in [('flat',flat),('fixed_short_diagnostic',short)]:
                side=support['side'] or p.side;candidates=reactions[side].get(t,[])
                fresh=[c for c in candidates if min(c['pivot_bar_end_ms'],c['available_ms'])>start]
                reaction=(fresh or candidates or [None])[0]
                result=action_review(context=gate,position=p,costs=costs,mark=mark,t=t,account=account,reaction=reaction,
                    target=target if p.quantity else target_at(prepared[-1],t,side,mark),last_growth=start,
                    original_root=None,prior_invalidated_ms=None,
                    target_hit=bool(p.quantity and hit is not None and hit<=t),reduction_used=bool(p.quantity and hit is not None and hit<t))
                review[name]=dict(reaction=reaction,result=result)
            points.append(dict(time_ms=t,utc=utc(t),mark=mark,state=deepcopy(state),support=support,
                               reactions={str(side):g.get(t,[]) for side,g in reactions.items()},reviews=review))
        return points,events
    points,events=run(end)
    for p in old['points']:
        q=next(x for x in points if x['time_ms']==p['time_ms'])
        assert q['state']==p['updated_only'] and q['support']==p['guarded']
    first_long=next((p for p in points if p['support']['side']==1),None)
    candidates=[p for p in points if p['reviews']['flat']['result']['action']=='entry_candidate']
    short_adds=[p for p in points if p['reviews']['fixed_short_diagnostic']['result']['action']=='add_candidate']
    checkpoints={start,end,stamp('2026-08-19T13:00:00Z')}
    if first_long:checkpoints.add(first_long['time_ms'])
    checkpoints.update(p['time_ms'] for p in candidates)
    for t in sorted(checkpoints):
        prefix,pe=run(t)
        assert prefix==[p for p in points if p['time_ms']<=t]
        assert pe==[e for e in events if e['time_ms']<=t]
    # Independent raw Decimal shape check: the label is net efficiency, not monotonicity.
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as f:
        raw={int(b['open_time'])+MINUTE:{k:D(b[k]) for k in ('high','low','close')} for b in csv.DictReader(io.TextIOWrapper(f))}
    hourly=[]
    for t in range(start+60*MINUTE,end+1,60*MINUTE):
        bs=[raw[k] for k in range(t-59*MINUTE,t+1,MINUTE)]
        hourly.append(dict(t=t,high=max(b['high'] for b in bs),low=min(b['low'] for b in bs),close=bs[-1]['close']))
    net=raw[end]['close']-raw[start]['close'];travel=sum(abs(b['close']-(hourly[i-1]['close'] if i else raw[start]['close'])) for i,b in enumerate(hourly))
    pullback=max((a['high']-b['low'],a['t'],b['t']) for i,a in enumerate(hourly) for b in hourly[i+1:])
    assert abs(net-D(str(case['metrics']['net'])))<D('1e-8')
    assert abs(net/travel-D(str(case['metrics']['efficiency'])))<D('1e-8')
    shape=dict(start_close=raw[start]['close'],end_close=raw[end]['close'],net=net,efficiency=net/travel,
               chronological_hour_pullback=pullback[0],pullback_from_ms=pullback[1],pullback_to_ms=pullback[2],
               label_known_at_ms=end)
    sources += [AUDIT,CONFIG,BASIS,GENERAL,account_path,funding_path,Path(__file__),ROOT/'scripts/review_market_judgment_regimes.py',
                ROOT/'scripts/review_market_basis_revision.py',ROOT/'scripts/review_market_direction_continuity.py',ROOT/'scripts/review_first_candidate_account.py']
    sources += [ROOT/'app/research/recovery'/x for x in ('protected_structure.py','structure_review.py','position_alternatives.py','recovery_capacity_review.py','round_trip_review.py','campaign_recovery_review.py','models.py')]
    result=dict(config=audit,case=case,shape=shape,points=points,events=events,
        summary=dict(first_long_support_ms=first_long['time_ms'] if first_long else None,
                     short_supported_times=[p['time_ms'] for p in points if p['support']['side']==-1],
                     entry_candidate_times=[p['time_ms'] for p in candidates],short_add_candidate_times=[p['time_ms'] for p in short_adds],
                     short_reaction_times=[p['time_ms'] for p in points if p['reactions']['-1']],
                     long_reaction_times=[p['time_ms'] for p in points if p['reactions']['1']]),
        checks=dict(prior_checkpoints='PASS',truncated_rebuild='PASS',raw_shape='PASS'),
        account_simulated=False,orders_generated=0,new_exposure_allowed=False,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'review.json').write_text(json.dumps(jsonable(result),ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(jsonable(dict(shape=shape,summary=result['summary'],checks=result['checks'])),ensure_ascii=False,indent=2))
    lines=['# 8월 19일 방향·추가 근거 심사','','고정 숏은 독립 시점 진단용 가정이다. 실제 승인 진입·연속 계좌가 아니다.','',
           '| UTC | 종가 | 방향 후보 | 새 숏/롱 반응 수 | 무포지션 행동 / 이유 | 숏 가정 행동 / 이유 |',
           '| --- | ---: | --- | --- | --- | --- |']
    keep={p['time_ms'] for p in old['points']}|checkpoints
    for p in points:
        if p['time_ms'] not in keep:continue
        f=p['reviews']['flat']['result'];s=p['reviews']['fixed_short_diagnostic']['result']
        lines.append(f"| {p['utc']} | {p['mark']} | {p['support']['side']} | {len(p['reactions']['-1'])}/{len(p['reactions']['1'])} | {f['action']} / {f['reason']} | {s['action']} / {s['reason']} |")
    (OUT/'review.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':main()
