"""Carry the selected-entry account through the unchanged three exit alternatives."""
import hashlib,json
from decimal import Decimal
from pathlib import Path
from review_market_transition_inventory import ROOT,MINUTE,stamp,utc,load_rows,market_trace,simulate,PositionExample,jsonable

CONFIG=ROOT/'configs/research/selected_entry_exit_trial.json'
OUT=ROOT/'reports/validation/selected_entry_exit_20260920'


def main():
    cfg=json.loads(CONFIG.read_text());source=ROOT/cfg['source'];old=json.loads(source.read_text())
    scan_path=ROOT/cfg['market_source'];scan=json.loads(scan_path.read_text())
    for prior in (old,scan):
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in prior['source_sha256'].items())
    start,end=stamp(cfg['start_utc']),stamp(cfg['end_utc'])
    case=next(c for c in scan['cases'] if c['label']==old['candidate']['label'])
    seed=case['points'][-1]['state'];assert seed['last_ms']==start
    structure_path=ROOT/'configs/research/market_judgment_regime_review.json';structure=json.loads(structure_path.read_text())
    rows,sources=load_rows();funding_path=ROOT/'data/historical/btcusdc_public_20260917/funding_history.json';funding=json.loads(funding_path.read_text())
    market=market_trace(rows,cfg,seed,structure)
    assert market['failure_ms'] is not None and market['opposition_ms'] is not None
    paths={};cancelled={}
    for label,path in old['paths'].items():
        if path['continuation'] is None:
            assert path['entry']['fill'] is None
            cancelled[label]=dict(status='no_trade',original_reason=path['entry']['reason'],entry=path['entry'],
                                  inventory_created=False,exit_simulated=False,actual_orders=0)
            continue
        previous=path['continuation'];f=previous['summary']['final']
        assert f['time_ms']==start and previous['pending'] is None and not previous['obligations']['waiting']
        assert not previous['summary']['halted'] and previous['active_obligation'] is None
        initial=PositionExample(**f['position']);assert initial.quantity>0
        assert initial.starting_equity+initial.pnl(f['mark'])==Decimal(f['equity'])
        args=dict(start=start,end=end,initial=initial,initial_peak=f['peak_equity'],
                  prior_max_dd=previous['summary']['cumulative_max_close_drawdown'],
                  failure_ms=market['failure_ms'],opposition_ms=market['opposition_ms'],half_fraction=cfg['half_loss_fraction'])
        paths[label]={}
        for policy in cfg['policies']:
            result=simulate(rows,funding,account=path['account'],policy=policy,**args)
            for t in sorted({market['failure_ms'],market['opposition_ms'],end}|
                            {e['time_ms']+MINUTE for e in result['ledger'] if e['kind']=='fill'}):
                prefix=simulate([b for b in rows if b['end_ms']<=t],[f for f in funding if f['fundingTime']<=t],
                                account=path['account'],policy=policy,**dict(args,end=t,
                                failure_ms=market['failure_ms'] if market['failure_ms']<=t else None,
                                opposition_ms=market['opposition_ms'] if market['opposition_ms']<=t else None))
                assert prefix['states']==[s for s in result['states'] if s['time_ms']<=t]
                assert prefix['decisions']==[d for d in result['decisions'] if d['time_ms']<=t]
            paths[label][policy]=dict(initial=initial,initial_state=f,continuation=result,
                full_states=previous['states']+jsonable(result['states']),
                full_ledger=previous['ledger']+jsonable(result['ledger']),
                full_exposure_btc_hours=Decimal(previous['summary']['exposure_btc_hours'])+result['summary']['exposure_btc_hours'])
    sources += [CONFIG,source,scan_path,structure_path,funding_path,Path(__file__),ROOT/'scripts/review_market_transition_inventory.py']
    for prior in (old,scan):sources += [ROOT/p for p in prior['source_sha256'] if ROOT/p not in sources]
    report=dict(config=cfg,market=market,paths=paths,cancelled_entries=cancelled,
                checks=dict(source_integrity='PASS',carry_no_reset='PASS',market_prefix=market['prefix_rebuild'],account_prefix='PASS'),
                actual_orders=0,new_exposure_allowed=False,
                source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'review.json').write_text(json.dumps(jsonable(report),ensure_ascii=False,indent=2)+'\n')
    lines=['# 선정 후보 잔량의 종료 비교','','| 비용·체결 가정 | 종료 정책 | 최종 순손익 | 누적 최대 종가 DD | 최종 BTC |','| --- | --- | ---: | ---: | ---: |']
    for label,group in paths.items():
        for policy,p in group.items():
            s=p['continuation']['summary'];f=s['final'];lines.append(f"| {label} | {policy} | {f['total_net']:.6f} | {s['cumulative_max_close_drawdown']:.6f} | {f['position'].quantity} |")
    lines+=['','거래 없음: '+', '.join(cancelled),'','이전 진입·축소·비용을 모두 포함한다. 종료 정책은 시험 대안이며 채택하지 않는다.','']
    (OUT/'review.md').write_text('\n'.join(lines));print('\n'.join(lines))


if __name__=='__main__':main()
