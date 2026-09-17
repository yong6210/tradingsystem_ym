"""Registered descriptive candidate comparison; no strategy selection or orders."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from app.research.data.minutes import load_verified_minutes
from app.research.foundation.validation import load_design
from app.research.foundation.contracts import MatchingDesign
from app.research.multistrategy_audit import feature_bank
from app.research.diagnostics.entry_information import build_decisions, HistoricalMatcher, moving_block_interval, descriptive, control_reuse
from app.research.diagnostics.candidate_screen import candidate_conditions, feasibility, independent_interval


def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def audit_e001(output):
    source=ROOT/'reports/validation/e001_entry_information_20260917'
    frame=pd.read_csv(source/'responses.csv')
    result=json.loads((source/'results.json').read_text())
    design=load_design(ROOT/'configs/research/e001_entry_information.json',ROOT)
    summary={}
    for window in design.windows:
        primary=frame[(frame.period.astype(str)==window.name)&(frame.horizon_minutes==60)]
        checks={}
        for direction,label in ((0,'all'),(1,'long'),(-1,'short')):
            selected=primary[primary.matched & ((primary.side==direction) if direction else True)]
            interval=independent_interval(selected.to_dict('records'),window.start,window.end,28,2000,design.matching.random_seed)
            expected=result['summaries'][window.name][label]['60']['interval']['interval_bps']
            if interval is None or expected is None:
                if interval!=expected:
                    raise ValueError('E001 empty interval mismatch')
            elif not np.allclose(interval,expected,rtol=0,atol=1e-9):
                raise ValueError('E001 independent interval mismatch')
            checks[label]=dict(independent_interval=interval,status='PASS')
        timestamps=pd.to_datetime(primary.decision_time,utc=True).sort_values()
        gaps=timestamps.diff().dt.total_seconds().dropna()/60
        strata={}
        for matched in (True,False):
            for side in (-1,1):
                group=primary[(primary.matched==matched)&(primary.side==side)]
                strata[f'matched_{matched}_side_{side}']=descriptive(group.gross_bps.tolist())
        summary[window.name]=dict(interval_checks=checks,matched_unmatched=strata,
                                 adjacent_signal_gap_under_60_fraction=float((gaps<60).mean()) if len(gaps) else None,
                                 control_reuse=result['control_reuse'][window.name])
    save(output/'e001_method_audit.json',summary)
    print('E001 independent intervals PASS (12 groups)',flush=True)


def execute(config,output,design):
    audit_e001(output)
    minutes=load_verified_minutes(ROOT/design.dataset.path)
    bank=feature_bank(minutes)
    opens=minutes.o.to_numpy()
    matching=MatchingDesign(config['lookback_days'],config['controls'],config['seed'],4,
                            tuple(config['matching_er_edges']),tuple(config['matching_volatility_edges']),True)
    all_rows=[]
    results={}
    embargo=config['delay_minutes']+max(config['horizons'])
    for model,spec in config['models'].items():
        frame=candidate_conditions(bank,model)
        signal={'decision':np.zeros(len(minutes),dtype=bool),'side':np.zeros(len(minutes),dtype=np.int8)}
        positions=minutes.index.get_indexer(frame.index)
        keep=(positions>=0)&frame.valid.to_numpy()
        signal['decision'][positions[keep]]=True
        signal['side'][positions[keep]]=frame.side.to_numpy()[keep]
        events={int(pos):(float(row.close),float(row.atr)) for pos,(_,row) in zip(positions,frame.iterrows()) if pos>=0 and row.valid and row.event}
        decisions=build_decisions(minutes,bank,signal,matching)
        matcher=HistoricalMatcher(decisions,matching,embargo)
        model_result={}
        with (output/f'{model}_matches.jsonl').open('w') as match_log:
            for window in design.windows:
                lower=minutes.index.searchsorted(window.start)
                upper=minutes.index.searchsorted(window.end)
                counts=Counter()
                rows=[]
                matches=[]
                for decision in decisions:
                    if decision.minute not in events or not lower<=decision.minute<upper:
                        continue
                    counts['events']+=1
                    if decision.minute+embargo>=upper:
                        counts['incomplete_outcome']+=1
                        match_log.write(json.dumps(dict(minute=decision.minute,period=window.name,excluded='incomplete_outcome'))+'\n')
                        continue
                    if decision.stratum is None:
                        counts['missing_stratum']+=1
                        continue
                    candidates,selected=matcher.select(decision)
                    counts['matched' if selected else 'unmatched']+=1
                    match=dict(period=window.name,minute=decision.minute,side=decision.side,stratum=decision.stratum,candidates=candidates,selected=selected)
                    match_log.write(json.dumps(match)+'\n')
                    matches.append(match)
                    entry=opens[decision.minute+config['delay_minutes']]
                    close,atr=events[decision.minute]
                    eligible=feasibility(float(entry),close,atr,decision.side,spec['stop_atr'],config)
                    counts[eligible['feasibility_reason']]+=1
                    counts['gross_eligible']+=int(eligible['gross_eligible'])
                    counts['cost_eligible']+=int(eligible['cost_eligible'])
                    for horizon in config['horizons']:
                        exit_price=opens[decision.minute+config['delay_minutes']+horizon]
                        gross=decision.side*(exit_price/entry-1)*10000
                        slip=config['slippage_bps_per_side']/10000
                        fee=config['taker_bps_per_side']/10000
                        efill=entry*(1+decision.side*slip)
                        xfill=exit_price*(1-decision.side*slip)
                        net=(decision.side*(xfill-efill)-(efill+xfill)*fee)/entry*10000
                        # Independent PnL identity, no call into response helper.
                        expected=(decision.side*(exit_price-entry)-(entry+exit_price)*slip
                                  -(entry+decision.side*entry*slip+exit_price-decision.side*exit_price*slip)*fee)/entry*10000
                        if not np.isclose(net,expected,rtol=0,atol=1e-8):
                            raise ValueError('cost PnL mismatch')
                        control=[]
                        for position in selected:
                            if position+embargo>decision.minute:
                                raise ValueError('future control label')
                            begin=opens[position+config['delay_minutes']]
                            end=opens[position+config['delay_minutes']+horizon]
                            control.append(float(decision.side*(end-begin)/begin*10000))
                        mean_control=float(np.mean(control)) if control else None
                        rows.append(dict(model=model,period=window.name,decision_time=minutes.index[decision.minute].isoformat(),minute=decision.minute,
                                         side=decision.side,horizon_minutes=horizon,matched=bool(selected),gross_bps=float(gross),market_net_bps=float(net),
                                         control_bps=mean_control,excess_bps=float(gross-mean_control) if selected else None,**eligible))
                all_rows.extend(rows)
                summaries={}
                for side,label in ((0,'all'),(1,'long'),(-1,'short')):
                    summaries[label]={}
                    for horizon in config['horizons']:
                        raw=[r for r in rows if r['horizon_minutes']==horizon and (not side or r['side']==side)]
                        paired=[r for r in raw if r['matched']]
                        data=dict(all_gross=descriptive([r['gross_bps'] for r in raw]),all_market_net=descriptive([r['market_net_bps'] for r in raw]),
                                  matched_gross=descriptive([r['gross_bps'] for r in paired]),excess=descriptive([r['excess_bps'] for r in paired]),
                                  eligible_gross=descriptive([r['gross_bps'] for r in raw if r['cost_eligible']]))
                        if horizon==spec['primary_minutes']:
                            interval=moving_block_interval(paired,window.start,window.end,config['bootstrap_days'],config['bootstrap_repetitions'],config['seed'])
                            independent=independent_interval(paired,window.start,window.end,config['bootstrap_days'],config['bootstrap_repetitions'],config['seed'])
                            if independent is not None and not np.allclose(independent,interval['interval_bps'],rtol=0,atol=1e-9):
                                raise ValueError('candidate independent interval mismatch')
                            data['interval']=interval
                        summaries[label][str(horizon)]=data
                model_result[window.name]=dict(counts=dict(counts),summaries=summaries,control_reuse=control_reuse(matches))
                print(model,window.name,json.dumps(dict(counts=dict(counts),primary=summaries['all'][str(spec['primary_minutes'])])),flush=True)
        results[model]=model_result
        save(output/'partial_results.json',results)
    data=pd.DataFrame(all_rows)
    data.to_csv(output/'responses.csv',index=False)
    primary=data[data.apply(lambda row: row.horizon_minutes==config['models'][row.model]['primary_minutes'],axis=1)].copy()
    primary['day']=pd.to_datetime(primary.decision_time,utc=True).dt.floor('D')
    correlations=primary.pivot_table(index='day',columns='model',values='gross_bps',aggfunc='mean').corr(min_periods=30)
    overlaps={}
    for a in config['models']:
        aset=set(primary.loc[primary.model==a,'day'])
        overlaps[a]={}
        for b in config['models']:
            bset=set(primary.loc[primary.model==b,'day'])
            union=aset|bset
            overlaps[a][b]=len(aset&bset)/len(union) if union else None
    save(output/'overlap.json',dict(event_day_jaccard=overlaps,daily_response_correlation=json.loads(correlations.to_json()),
                                  note='Pairwise available days, minimum 30, different horizons; not account PnL correlation.'))
    save(output/'results.json',dict(experiment_id=config['experiment_id'],classification='DESCRIPTIVE_ONLY_NO_WINNER',models=results))
    save(output/'verification.json',dict(input_rows=len(minutes),outcome_rows=len(data),archive_hashes='PASS',e001_independent_intervals=12,
                                       candidate_independent_intervals=72,cost_identity='PASS',control_embargo='PASS',
                                       limitations=['No executions, account path, funding, liquidation or BTCUSDC prices.',
                                                    'Prior inspected data; no selection adjustment; matching residual bias.',
                                                    'Current contract filters on historical proxy prices; not historical exchange replication.']))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    config_path=ROOT/'configs/research/e003_candidate_screen.json'
    config=json.loads(config_path.read_text())
    design=load_design(ROOT/'configs/research/e001_entry_information.json',ROOT)
    if set(config['models'])!={'S01','S02','S04','S05','S07','S08'}:
        raise ValueError('unsupported candidate set')
    if config['start']!=design.windows[0].start.isoformat().replace('+00:00','Z') or config['end']!=design.windows[-1].end.isoformat().replace('+00:00','Z'):
        raise ValueError('window mismatch')
    args.output.mkdir(parents=True,exist_ok=False)
    paths=[Path(__file__),config_path,ROOT/design.dataset.path,ROOT/'app/research/multistrategy_audit.py',
           ROOT/'app/research/data/minutes.py',ROOT/'docs/research/experiments/E003_CANDIDATE_SCREEN.md',
           ROOT/'docs/research/BINANCE_BTCUSDC_FILTER_SNAPSHOT.json',ROOT/'tests/test_candidate_screen.py']
    paths+=list((ROOT/'app/research/diagnostics').glob('*.py'))+list((ROOT/'app/research/foundation').glob('*.py'))
    paths+=[ROOT/'configs/research/e001_entry_information.json',ROOT/'reports/validation/e001_entry_information_20260917/results.json',
            ROOT/'reports/validation/e001_entry_information_20260917/responses.csv']
    save(args.output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),config=config,
                                            source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                                            runtime=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__)))
    save(args.output/'status.json',dict(status='RUNNING'))
    try:
        execute(config,args.output,design)
    except Exception as exc:
        save(args.output/'status.json',dict(status='FAILED',reason=str(exc)))
        raise
    save(args.output/'status.json',dict(status='COMPLETE'))


if __name__=='__main__':
    main()
