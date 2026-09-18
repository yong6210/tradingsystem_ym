"""E021 registered finite public connection check; never sends exchange orders."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.observation.public_paper import initial_state,transition
from app.research.observation.public_paper_store import PublicPaperStore
from app.research.observation.public_transport import PublicRest,LIMITS,ingest,receive_cycle,funding_query
from app.research.observation.t0_signal import T0Signal
from scripts.run_direction_controls import save,load,digest,test_ids


def local_clock():
    mono,wall = time.monotonic_ns(),time.time_ns()
    return dict(request_started_ns=mono,received_ns=mono,request_started_utc_ns=wall,received_utc_ns=wall)


def verify_database(output,binding):
    store = PublicPaperStore(output/'paper.sqlite',binding)
    try:
        if store.db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('SQLite integrity check failed')
        state = json.loads(store.db.execute("SELECT value FROM meta WHERE key='initial'").fetchone()[0])
        counts = {};rows = 0;public_rows = 0
        for rid,session,kind,raw,h,c,query,stored,emitted in store.db.execute(
                'SELECT id,session,kind,raw,sha256,clock,query,state,outputs FROM receipts ORDER BY seq'):
            if hashlib.sha256(raw.encode()).hexdigest()!=h:raise ValueError('raw hash mismatch')
            clock = json.loads(c);params = json.loads(query)
            try:body = json.loads(raw)
            except json.JSONDecodeError:body = None
            state,outputs = transition(state,kind,body,clock,session,params)
            if state!=json.loads(stored) or outputs!=json.loads(emitted):raise ValueError('replay mismatch')
            if rid.isdigit():
                receipt = load(output/'raw'/f'{rid}.receipt.json')
                raw_path = output/receipt['raw_file']
                if digest(raw_path)!=receipt['sha256'] or receipt['clock']!=clock or receipt['query']!=params:
                    raise ValueError('transport receipt mismatch')
                if kind!='FEED_ERROR' and raw_path.read_text()!=raw:raise ValueError('response/DB differs')
                public_rows += 1
            for item in outputs:counts[item['kind']] = counts.get(item['kind'],0)+1
            rows += 1
        if state!=store.state():raise ValueError('final state differs')
        account = state['account']
        expected = account['risk']['initial']+account['realized']-account['fees']-account['funding']
        if abs(expected-account['cash'])>1e-7:raise ValueError('cash identity')
        return dict(receipts=rows,public_raw_matches=public_rows,outputs=counts,
                    method='RAW_HASH_AND_SAME_ENGINE_REPLAY_NOT_INDEPENDENT_STRATEGY')
    finally:store.close()


def main(output):
    previous = ROOT/'reports/validation/e020_continuous_paper_20260919'
    reg = load(previous/'registration.json')
    sources = dict(reg['source_hashes']);old = dict(reg['prior_artifact_hashes'])
    for name,h in sources.items():
        if digest(ROOT/name)!=h:raise ValueError('previous source changed: '+name)
    for name,h in load(previous/'verification.json')['artifact_hashes'].items():
        if digest(previous/name)!=h:raise ValueError('E020 artifact changed: '+name)
    for path in previous.rglob('*'):
        if path.is_file():old[str(path.relative_to(ROOT))] = digest(path)
    for name in ('app/research/observation/public_paper.py','app/research/observation/public_paper_store.py',
                 'app/research/observation/public_transport.py','tests/test_public_paper.py',
                 'tests/test_public_transport.py','scripts/run_public_paper.py',
                 'docs/research/experiments/E021_PUBLIC_PAPER_ADAPTER.md'):
        sources[name] = digest(ROOT/name)
    for name,h in old.items():
        if digest(ROOT/name)!=h:raise ValueError('previous evidence changed: '+name)
    seed_path = ROOT/'reports/validation/e019_public_entry_probe_20260919/final_state.json'
    seed = load(seed_path)['signal']
    initial = initial_state(T0Signal.restore(seed),'one',time.time_ns()//1000000)
    binding = dict(source_hashes=sources,costs=initial['account']['costs'],risk=initial['account']['risk'],
                   seed_sha256=digest(seed_path),scope='BOUNDED_PUBLIC_PAPER_NOT_PERFORMANCE')
    suite = unittest.defaultTestLoader.loadTestsFromNames(('tests.test_public_paper','tests.test_public_transport',
        'tests.test_quote_paper_account','tests.test_causal_intents','tests.test_bar_observation','tests.test_baseline_account'))
    ids = list(test_ids(suite))
    save(output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        source_hashes=sources,prior_artifact_hashes=old,binding=binding,test_ids=ids,
        resource_limits=LIMITS,seed_path=str(seed_path.relative_to(ROOT)),automatic_retries=0,
        scope='PUBLIC_CONNECTION_CHECK_NOT_NEW_SIGNAL_OR_PROFITABILITY_PROOF'))
    for name in sources:
        path = output/'source_snapshot'/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes((ROOT/name).read_bytes())
    with (output/'tests.log').open('x') as stream:
        tested = unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(output/'tests.json',dict(registered=len(ids),executed=tested.testsRun,
        failures=len(tested.failures),errors=len(tested.errors),skipped=len(tested.skipped)))
    if not tested.wasSuccessful() or tested.skipped or tested.testsRun!=len(ids):
        raise ValueError('registered tests failed')
    rest = PublicRest(output);store = PublicPaperStore(output/'paper.sqlite',binding,initial)
    polls = 0;warmup = 0;armed_ms = None
    try:
        ingest(rest,store,'/fapi/v1/time')
        for _ in range(LIMITS['warmup_pages']):
            next_ms = store.state()['account']['signal']['state']['last_open_ms']+60000
            outputs = ingest(rest,store,'/fapi/v1/klines',dict(symbol='BTCUSDC',interval='1m',startTime=next_ms,limit=1000))
            applied = next((x['count'] for x in outputs if x['kind']=='BARS_APPLIED'),None)
            if applied is None:raise ValueError('warmup response rejected')
            warmup += applied
            last = store.state()['account']['signal']['state']['last_open_ms']
            if time.time_ns()//1000000-(last+60000)<=120000:break
        else:raise ValueError('warmup page bound')
        ingest(rest,store,'/fapi/v1/premiumIndex',dict(symbol='BTCUSDC'))
        ingest(rest,store,'/fapi/v1/fundingRate',funding_query(store.state()))
        store.commit('ARM','ARM','{}',local_clock(),'one')
        if store.state()['account']['phase']!='OBSERVE':raise ValueError('public readiness did not allow ARM')
        armed_ms = store.state()['account']['armed_ms']
        print(f'Public account armed; warmup {warmup} minutes; finite 45-second connection check.',flush=True)
        deadline = time.monotonic()+LIMITS['observe_seconds']
        while min(deadline,rest.deadline)-time.monotonic()>=20:
            receive_cycle(rest,store);polls += 1
            time.sleep(min(LIMITS['poll_seconds'],max(0,deadline-time.monotonic())))
        store.commit('END','END','{}',local_clock(),'one')
        # Explicit end intent, then a NEW quote if held. No invented terminal fill.
        if store.state()['account']['quantity'] and rest.deadline-time.monotonic()>=5:
            ingest(rest,store,'/fapi/v1/ticker/bookTicker',dict(symbol='BTCUSDC'))
        ingest(rest,store,'/fapi/v1/time')
        final = store.state()
        save(output/'final_state.json',final)
    finally:
        store.close()
    verified = verify_database(output,binding)
    if verified['public_raw_matches']!=rest.count:raise ValueError('unmatched public response')
    account = final['account']
    summary = dict(status='COMPLETE_BOUNDED_PUBLIC_CONNECTION_CHECK',tests=tested.testsRun,
        public_requests=rest.count,raw_bytes=rest.bytes,warmup_minutes=warmup,cycles=polls,
        armed_ms=armed_ms,last_received_utc_ns=account['last_received_utc_ns'],
        observed_signals=account['observed_signals'],eligible_intents=account['eligible_intents'],
        entries=account['entries'],exits=account['exits'],residual_quantity=account['quantity'],
        cash=account['cash'],funding_cashflow=account['funding'],
        final_guard=final['guard'],review_reasons=final['review_reasons'],faults=final['faults'],
        live_orders=0,strategy_adoptions=0,performance_evaluation=False,
        scope='FINITE_REST_RECEIPTS_NOT_CONTINUOUS_COVERAGE')
    save(output/'summary.json',summary)
    for name,h in (sources|old).items():
        if digest(ROOT/name)!=h:raise ValueError('source/evidence changed: '+name)
    save(output/'verification.json',dict(status='PASS_SCOPED_TESTS_AND_PUBLIC_RECEIPT_REPLAY',
        database=verified,sources_unchanged=len(sources),prior_artifacts_unchanged=len(old),
        artifact_hashes={str(p.relative_to(output)):digest(p) for p in output.rglob('*') if p.is_file()}))
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    try:main(args.output)
    except Exception as exc:
        save(args.output/'failure.json',dict(type=type(exc).__name__,reason=str(exc)))
        raise
