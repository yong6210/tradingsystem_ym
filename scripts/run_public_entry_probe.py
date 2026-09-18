"""Bounded public BTCUSDC signal/quote entry probes, never account trading."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.observation.t0_signal import T0Signal
from app.research.observation.checkpoint import unseal
from app.research.observation.causal_intents import ProbeStore,initial_state,encode,transition
from scripts.run_direction_controls import save,load,digest,test_ids


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('public probe redirects disabled')


class PublicRest:
    def __init__(self,output):
        self.output=output;self.count=0;self.bytes=0
        self.deadline=time.monotonic()+180
        self.opener=urllib.request.build_opener(NoRedirect())
        (output/'raw').mkdir()

    def get(self,path,params=None):
        if path not in ('/fapi/v1/time','/fapi/v1/klines','/fapi/v1/ticker/bookTicker'):
            raise ValueError('not an allowed public market-data path')
        if self.count>=70 or time.monotonic()>=self.deadline:
            raise ValueError('fixed request/time budget reached')
        self.count+=1;request_id=f'{self.count:04d}'
        url='https://fapi.binance.com'+path
        if params:url+='?'+urllib.parse.urlencode(params)
        clock=dict(request_started_ns=time.monotonic_ns(),request_started_utc_ns=time.time_ns())
        raw=b'';status=None;error=None
        try:
            with self.opener.open(url,timeout=min(5,self.deadline-time.monotonic())) as response:
                status=response.status;raw=response.read(512*1024+1)
                if len(raw)>512*1024:raise ValueError('response byte limit')
        except urllib.error.HTTPError as exc:
            status=exc.code;raw=exc.read(512*1024+1);error='HTTP_'+str(status)
        except Exception as exc:error=type(exc).__name__+': '+str(exc)
        clock.update(received_ns=time.monotonic_ns(),received_utc_ns=time.time_ns())
        self.bytes+=len(raw)
        raw_path=self.output/'raw'/(request_id+'.body')
        raw_path.write_bytes(raw)
        receipt=dict(request_id=request_id,url=url,status=status,error=error,clock=clock,
                     raw_file=str(raw_path.relative_to(self.output)),sha256=hashlib.sha256(raw).hexdigest())
        save(self.output/'raw'/(request_id+'.receipt.json'),receipt)
        if error or status!=200:raise ValueError('public request failed: '+str(error or status))
        if time.monotonic()>self.deadline or self.bytes>16*1024*1024:
            raise ValueError('fixed total resource budget exceeded')
        if clock['received_ns']-clock['request_started_ns']>5_000_000_000:
            raise ValueError('request time bound exceeded')
        return request_id,raw.decode('utf-8'),clock


def check_time(raw,clock):
    value=json.loads(raw)['serverTime']
    if type(value) is not int or not clock['request_started_utc_ns']//1000000-1000<=value<=clock['received_utc_ns']//1000000+1000:
        raise ValueError('server/local clock bracket failed')
    return value


def verify_database(path,binding):
    store=ProbeStore(path,binding)
    try:
        assert store.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        state=json.loads(store.db.execute("SELECT value FROM meta WHERE key='initial'").fetchone()[0])
        counts={};rows=store.db.execute('SELECT id,kind,raw,raw_sha256,clock,state,outputs FROM receipts ORDER BY seq').fetchall()
        for request_id,kind,raw,h,clock,stored_state,stored_outputs in rows:
            assert hashlib.sha256(raw.encode()).hexdigest()==h
            state,outputs=transition(state,kind,json.loads(raw),json.loads(clock))
            assert encode(state)==stored_state and encode(outputs)==stored_outputs
            for item in outputs:counts[item['kind']]=counts.get(item['kind'],0)+1
        assert state==store.state()
        return dict(status='PASS_RAW_HASH_STATE_OUTPUT_REPLAY',receipts=len(rows),outputs=counts,
                    replay_uses_same_transition_implementation=True)
    finally:store.close()


def main(output):
    prior=ROOT/'reports/validation/e018_incremental_bars_20260919'
    prior_reg=load(prior/'registration.json');prior_v=load(prior/'verification.json')
    old=dict(prior_reg['prior_artifact_hashes'])
    for name,h in prior_v['artifact_hashes'].items():
        if digest(prior/name)!=h:raise ValueError('E018 artifact changed')
    for p in prior.rglob('*'):
        if p.is_file():old[str(p.relative_to(ROOT))]=digest(p)
    sources=dict(prior_reg['source_hashes'])
    for name in ('app/research/observation/causal_intents.py','scripts/run_public_entry_probe.py',
                 'tests/test_causal_intents.py','docs/research/experiments/E019_PUBLIC_ENTRY_PROBE.md'):
        sources[name]=digest(ROOT/name)
    for name,h in (old|sources).items():
        if digest(ROOT/name)!=h:raise ValueError('source/evidence changed: '+name)
    seed_path=max((prior/'checkpoints').glob('*.json'),key=lambda p:int(p.stem))
    seed=unseal(load(seed_path),prior_reg['binding'])['signal']
    state=initial_state(T0Signal.restore(seed))
    binding=dict(version=1,symbol='BTCUSDC',source_hashes=sources,seed_sha256=digest(seed_path),
        costs=asdict(Costs()),risk=asdict(Risk()),scope='ENTRY_PROBE_NOT_TRADING_ACCOUNT',
        signal_lateness_ms=60000,quote_age_ms=5000,clock_uncertainty_ms=1000)
    suite=unittest.defaultTestLoader.loadTestsFromNames(('tests.test_causal_intents','tests.test_bar_observation','tests.test_baseline_account'))
    ids=list(test_ids(suite))
    save(output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='BOUNDED_PUBLIC_ARRIVAL_ENTRY_PROBE_NOT_STRATEGY_EVALUATION',binding=binding,
        source_hashes=sources,prior_artifact_hashes=old,test_ids=ids,seed_path=str(seed_path.relative_to(ROOT)),
        resource_limits=dict(total_seconds=180,observe_seconds=45,poll_seconds=5,requests=70,
                             warmup_pages=40,rows_per_page=1000,response_bytes=512*1024,total_raw_bytes=16*1024*1024),
        automatic_retries=0))
    for name in sources:
        p=output/'source_snapshot'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
    with (output/'tests.log').open('x') as stream:tested=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(output/'tests.json',dict(registered=len(ids),executed=tested.testsRun,
        failures=len(tested.failures),errors=len(tested.errors),skipped=len(tested.skipped)))
    if not tested.wasSuccessful() or tested.skipped or tested.testsRun!=len(ids):raise ValueError('tests failed')
    rest=PublicRest(output);store=ProbeStore(output/'probe.sqlite',binding,state)
    try:
        _,raw,c=rest.get('/fapi/v1/time');check_time(raw,c)
        warmup_bars=0
        for page in range(40):
            next_ms=store.state()['signal']['state']['last_open_ms']+60000
            rid,raw,c=rest.get('/fapi/v1/klines',dict(symbol='BTCUSDC',interval='1m',startTime=next_ms,limit=1000))
            outputs=store.commit(rid,'KLINES',raw,c)
            added=next(x['count'] for x in outputs if x['kind']=='BARS_APPLIED');warmup_bars+=added
            if page%10==0:print(f'Warmup: {warmup_bars:,} minutes; trading intents suppressed.',flush=True)
            latest=store.state()['signal']['state']['last_open_ms']
            if c['received_utc_ns']//1000000-(latest+60000)<=120000:break
        else:raise ValueError('warmup page limit without ready state')
        mono=time.monotonic_ns();wall=time.time_ns()
        armed=store.commit('ARM','ARM','{}',dict(request_started_ns=mono,received_ns=mono,
            request_started_utc_ns=wall,received_utc_ns=wall))
        deadline=time.monotonic()+45
        print('Armed 45-second public observation; a missing T0 decision will remain zero.',flush=True)
        polls=0
        while time.monotonic()<deadline:
            remaining=min(deadline,rest.deadline)-time.monotonic()
            if remaining<5:break
            next_ms=store.state()['signal']['state']['last_open_ms']+60000
            rid,raw,c=rest.get('/fapi/v1/klines',dict(symbol='BTCUSDC',interval='1m',startTime=next_ms,limit=3))
            store.commit(rid,'KLINES',raw,c)
            if min(deadline,rest.deadline)-time.monotonic()<5:break
            rid,raw,c=rest.get('/fapi/v1/ticker/bookTicker',dict(symbol='BTCUSDC'))
            store.commit(rid,'QUOTE',raw,c);polls+=1
            time.sleep(min(5,max(0,min(deadline,rest.deadline)-time.monotonic())))
        final_state=store.state()
        # Explicit incomplete intents remain pending/expired data, never terminal fills.
        save(output/'final_state.json',final_state)
    finally:store.close()
    _,raw,c=rest.get('/fapi/v1/time');check_time(raw,c)
    verified=verify_database(output/'probe.sqlite',binding)
    summaries=dict(status='COMPLETE_BOUNDED_PUBLIC_ENTRY_PROBE',warmup_bars=warmup_bars,
        quote_poll_pairs=polls,public_requests=rest.count,raw_bytes=rest.bytes,
        armed_ms=final_state['armed_ms'],last_received_utc_ns=final_state['last_received_utc_ns'],
        eligible_signal_count=final_state['signal_count'],entry_quote_estimates=final_state['probe_count'],
        outputs=verified['outputs'],actual_orders=0,account_pnl_computed=False,strategy_adopted=False,
        observation_scope='SHORT_REST_POLLING_NOT_CONTINUOUS_COVERAGE',
        desired_observe_seconds=45,os_crash_consistency_verified=False)
    save(output/'summary.json',summaries)
    for name,h in (old|sources).items():
        if digest(ROOT/name)!=h:raise ValueError('source/evidence changed: '+name)
    save(output/'verification.json',dict(status='PASS_SCOPED_UNIT_TESTS_PUBLIC_RECEIPTS_AND_REPLAY',
        database=verified,sources_unchanged=len(sources),prior_artifacts_unchanged=len(old),
        artifact_hashes={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*')) if p.is_file()}))
    print(json.dumps(summaries),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    try:main(args.output)
    except Exception as exc:
        save(args.output/'failure.json',dict(status='FAILED',exception=type(exc).__name__,reason=str(exc)))
        raise
