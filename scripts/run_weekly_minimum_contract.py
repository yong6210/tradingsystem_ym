"""E046 weekly LONG with the previously fixed minimum-contract policy; no risk grid."""
import argparse
from datetime import datetime,timezone
from decimal import Decimal as D,ROUND_CEILING,ROUND_FLOOR
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.weekly_momentum import sessions,decisions,verify_signals
from app.research.diagnostics.minimum_contract_engine import simulate
from app.research.diagnostics.operating_audit import verify_run,near
from app.research.diagnostics.review_metrics import calendar_risk
from app.research.diagnostics.concentration import concentration
from scripts.run_direction_controls import save,load,digest,lines,verify_daily
from scripts.run_time_exit_policy import START,END,check_hashes
from scripts.run_intrabar_risk_paths import verify_stops
from scripts.run_btcusdc_comparison import annual


def verify_minimum_fills(result,commands,minutes,cost,risk):
    tick,step,fee,slip=(D(str(x)) for x in (cost.tick,risk.step,cost.fee_bps/10000,cost.slippage_bps/10000))
    checked=[]
    for t in result['trades']:
        i=t['entry_minute'];side,close,atr=commands[i]
        reference=D(str(minutes.o.iloc[i]));side=D(side)
        entry=(reference*(1+side*slip)/tick).to_integral_value(rounding=ROUND_CEILING if side==1 else ROUND_FLOOR)*tick
        minimum=(max(D(str(risk.minimum_qty)),D(str(risk.minimum_notional))/entry)/step).to_integral_value(rounding=ROUND_CEILING)*step
        stop=((D(str(close))-side*D(str(risk.stop_atr))*D(str(atr)))/tick).to_integral_value(rounding=ROUND_FLOOR if side==1 else ROUND_CEILING)*tick
        stop_fill=(stop*(1-side*slip)/tick).to_integral_value(rounding=ROUND_FLOOR if side==1 else ROUND_CEILING)*tick
        loss=minimum*(side*(entry-stop_fill)+(entry+stop_fill)*fee)
        if D(str(t['quantity']))!=minimum:raise ValueError('not smallest legal order')
        if abs(D(str(t['entry_price']))-entry)>D('.0000001') or abs(D(str(t['planned_loss']))-loss)>D('.0000001'):
            raise ValueError('independent minimum loss/fill mismatch')
        if loss>D(str(t['budget']))+D('.0000001'):raise ValueError('risk budget exceeded')
        checked.append(dict(time=t['entry_time'],quantity=str(minimum),planned_loss=str(loss),budget=t['budget']))
    return dict(status='PASS_DECIMAL_SMALLEST_ORDER_AND_PLANNED_LOSS',checked=checked)


def main(out):
    prior=ROOT/'reports/validation/e039_weekly_long_operations_20260919'
    old=load(prior/'registration.json');latest=load(ROOT/'reports/validation/e045_prefomc_20260919/registration.json');sources=dict(latest['source_hashes'])
    for name in ['app/research/diagnostics/minimum_contract.py','app/research/diagnostics/minimum_contract_engine.py',
                 'scripts/run_weekly_minimum_contract.py','tests/test_minimum_contract.py',
                 'docs/research/experiments/E046_WEEKLY_MINIMUM_CONTRACT.md']:
        sources[name]=digest(ROOT/name)
    check_hashes(sources)
    for name,h in load(prior/'verification.json')['artifacts'].items():
        if digest(prior/name)!=h:raise ValueError('changed E039 artifact '+name)
    original=(ROOT/'app/research/diagnostics/operating_engine.py').read_text()
    expected=original.replace('from ..baseline.risk import Risk, size_order','from ..baseline.risk import Risk\nfrom .minimum_contract import size_order')
    if expected!=(ROOT/'app/research/diagnostics/minimum_contract_engine.py').read_text():raise ValueError('engine change beyond sizing import')
    preflight=ROOT/'reports/validation/e044_contract_preflight_20260919'
    public=load(preflight/'exchange_info.json');receipt=load(preflight/'receipt.json')
    if digest(preflight/'exchange_info.json')!=receipt['response_sha256']:raise ValueError('public response changed')
    symbol=next(s for s in public['symbols'] if s['symbol']=='BTCUSDC');f={x['filterType']:x for x in symbol['filters']}
    if symbol['status']!='TRADING' or symbol['marginAsset']!='USDC':raise ValueError('ineligible contract')
    for name in ('LOT_SIZE','MARKET_LOT_SIZE'):
        if D(f[name]['minQty'])!=D('.001') or D(f[name]['stepSize'])!=D('.001'):raise ValueError('changed quantity filter')
    if D(f['MIN_NOTIONAL']['notional'])!=50 or D(f['PRICE_FILTER']['tickSize'])!=D('.1'):raise ValueError('changed notional/tick')
    input_hashes={str(p.relative_to(ROOT)):digest(p) for p in preflight.iterdir() if p.is_file()}
    risk=Risk(**{**old['settings']['risk'],'cycle_fraction':old['settings']['risk']['aggregate_fraction']})
    settings={**old['settings'],'risk':vars(risk),'sizing':'MINIMUM_LEGAL_QUANTITY_ONLY','runs':8,
        'classification':'POST_HOC_FEASIBILITY_DIAGNOSTIC_NOT_INDEPENDENT_VALIDATION','new_public_contract_requests':0, 'policy_source':'E044', 'model':'WEEKLY_LONG'}
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,source_hashes=sources,
        input_hashes=input_hashes,prior_verification_sha256=digest(prior/'verification.json'),actual_orders=0))
    for name in sources:
        p=out/'source_snapshot'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
    with (out/'tests.log').open('x') as stream:
        tested=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(
            ['tests.test_minimum_contract','tests.test_operating_engine','tests.test_weekly_momentum','tests.test_intrabar_risk_paths']))
    if not tested.wasSuccessful() or tested.skipped:raise ValueError('focused tests failed')
    print('Loading frozen prices and E038 weekly signals after registration.',flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917');bundle.require_complete_window(START,END)
    months=pd.date_range(START,END,freq='MS',inclusive='left');indices=bundle.trade.index.get_indexer(months)
    if len(months)!=24 or min(indices)<0:raise ValueError('charge calendar')
    funding={e['fundingTime']:e for e in bundle.funding};runs={};checks={};paired={}
    signals=sessions(bundle.trade,START,END)
    signal_source=ROOT/'reports/validation/e038_weekly_momentum_20260919_v2/signals.json'
    if signals!=load(signal_source) or len(signals)!=104:raise ValueError('weekly signals changed')
    save(out/'signal_verification.json',verify_signals(bundle.trade,signals))
    save(out/'signals.json',signals)
    for model in ('WEEKLY_LONG',):
        commands=decisions(signals,'LONG');save(out/'decisions.json',commands)
        entries=sorted(i for i,v in commands.items() if v[0]);exits=sorted(i for i,v in commands.items() if not v[0])
        if len(entries)!=len(exits) or any(i>=j for i,j in zip(entries,exits)):raise ValueError('invalid saved event commands')
        allowed=dict(zip(entries,exits))
        for amount in (0,2):
            for scenario,params in settings['costs'].items():
                cost=Costs(**params)
                for path in ('OHLC','OLHC'):
                    key=f'{scenario}_op{amount}_{path}';print(key,flush=True)
                    result=simulate(bundle.trade,commands,pd.Timestamp(START),pd.Timestamp(END),cost,risk,
                        funding=bundle.funding,path=path,operating_debits={int(i):amount for i in indices})
                    m=result['metrics'];m['annual']=annual(result['daily'],1000);folder=out/key;folder.mkdir()
                    for name in ('events','trades','daily','rejections','path_stops'):
                        with (folder/(name+'.jsonl')).open('x') as stream:
                            for row in result[name]:stream.write(json.dumps(row,allow_nan=False)+'\n')
                    save(folder/'metrics.json',m)
                    audit=verify_run(folder,m,funding);audit['daily']=verify_daily(result,bundle.trade)
                    audit['stops']=verify_stops(result,bundle.trade,path,cost,risk)
                    audit['minimum_fills']=verify_minimum_fills(result,commands,bundle.trade,cost,risk)
                    operating=[dict(time=e['time'],amount=e['amount']) for e in result['events'] if e['kind']=='operating']
                    expected=[dict(time=t.isoformat(),amount=amount) for t in months] if amount else []
                    if operating!=expected:raise ValueError('charge calendar mismatch')
                    near(m['operating_cost'],amount*24)
                    for t in result['trades']:
                        if t['entry_minute'] not in allowed or t['exit_minute']>allowed[t['entry_minute']]:raise ValueError('unregistered entry/exit')
                    if len({t['entry_minute'] for t in result['trades']})!=len(result['trades']):raise ValueError('unexpected reentry')
                    monthly={};previous=1000.
                    for day in result['daily']:
                        month=day['day'][:7];monthly[month]=monthly.get(month,0)+day['equity']-previous;previous=day['equity']
                    net=m['final_equity']-1000;near(sum(monthly.values()),net)
                    detail=dict(net_usdc=net,calendar_risk=calendar_risk(result['daily']),monthly_net_after_operations=monthly,
                        concentration=concentration([dict(id=i,net=t['net_pnl']) for i,t in enumerate(result['trades'])],(1,5)) if result['trades'] else None,
                        necessary_conditions_pass=net>0 and m['max_drawdown_pct']<=5)
                    save(folder/'diagnostics.json',detail);save(folder/'verification.json',audit)
                    old_trades={t['entry_time']:t for t in lines(prior/key/'trades.jsonl')};new_trades={t['entry_time']:t for t in result['trades']}
                    added=[t for stamp,t in new_trades.items() if stamp not in old_trades]
                    lost=[t for stamp,t in old_trades.items() if stamp not in new_trades]
                    shared=[stamp for stamp in new_trades if stamp in old_trades]
                    old_net=load(prior/key/'metrics.json')['final_equity']-1000
                    pairing=dict(old_net=old_net,new_net=net,difference=net-old_net,common_entries=len(shared),added_entries=len(added),lost_entries=len(lost),
                        added_realized_net=sum(t['net_pnl'] for t in added),lost_old_realized_net=sum(t['net_pnl'] for t in lost),
                        common_realized_difference=sum(new_trades[k]['net_pnl']-old_trades[k]['net_pnl'] for k in shared),
                        added_times=[t['entry_time'] for t in added],lost_times=[t['entry_time'] for t in lost])
                    near(pairing['added_realized_net']-pairing['lost_old_realized_net']+pairing['common_realized_difference'],pairing['difference'])
                    runs[key]=dict(metrics=m,diagnostics=detail);checks[key]=audit;paired[key]=pairing
                    print(json.dumps(dict(run=key,net=net,dd=m['max_drawdown_pct'],cycles=m['cycles'],added=len(added))),flush=True)
    screening={str(op):{model:all(runs[f'{c}_op{op}_{p}']['diagnostics']['necessary_conditions_pass']
        for c in settings['costs'] for p in ('OHLC','OLHC')) for model in ('WEEKLY_LONG',)} for op in (0,2)}
    save(out/'summary.json',dict(settings=settings,runs=runs,paired=paired,screening=screening,
        source_data_reused=True,post_hoc_diagnostic=True,risk_parameters_confirmed_by_user=False,
        future_profit_verified=False,strategy_adopted=False,actual_orders=0))
    check_hashes(sources);check_hashes(input_hashes)
    save(out/'verification.json',dict(status='PASS_SCOPED_SIZING_DIAGNOSTIC_WITH_SELECTION_LIMITATIONS',focused_tests=tested.testsRun,
        engine_body_identical_except_sizing_import=True,checks=checks,source_hashes_unchanged=len(sources),
        artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    try:main(a.output)
    except Exception as e:save(a.output/'failure.json',dict(type=type(e).__name__,reason=str(e)));raise
