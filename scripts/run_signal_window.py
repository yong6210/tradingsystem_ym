"""Register first, then execute one fixed new-bar window at its real UTC time."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.observation.signal_window import window,admission,require_preclose_arm,audit_rows
from app.research.observation.public_paper import initial_state
from app.research.observation.public_paper_store import PublicPaperStore
from app.research.observation.public_transport import PublicRest,LIMITS,ingest,receive_cycle,funding_query
from app.research.observation.t0_signal import T0Signal
from scripts.run_public_paper import local_clock,verify_database
from scripts.run_direction_controls import save,load,digest,test_ids


def check_hashes(mapping):
    for name,expected in mapping.items():
        if digest(ROOT/name)!=expected:raise ValueError('registered file changed: '+name)


def prepare(output,target_ms):
    plan = window(target_ms)
    if time.time_ns()//1000000>=plan['launch_ms']:
        raise ValueError('register before the observation window')
    previous = ROOT/'reports/validation/e021_public_paper_20260919'
    prior = load(previous/'registration.json')
    sources = dict(prior['source_hashes']);old = dict(prior['prior_artifact_hashes'])
    check_hashes(sources|old)
    for name,h in load(previous/'verification.json')['artifact_hashes'].items():
        if digest(previous/name)!=h:raise ValueError('E021 evidence changed')
    for path in previous.rglob('*'):
        if path.is_file():old[str(path.relative_to(ROOT))] = digest(path)
    for name in ('app/research/observation/signal_window.py','scripts/run_signal_window.py',
                 'tests/test_signal_window.py','docs/research/experiments/E022_SIGNAL_BOUNDARY.md'):
        sources[name] = digest(ROOT/name)
    seed_path = previous/'final_state.json'
    seed = load(seed_path)['account']['signal']
    policy = initial_state(T0Signal.restore(seed),'one',time.time_ns()//1000000)['account']
    binding = dict(source_hashes=sources,costs=policy['costs'],risk=policy['risk'],
                   seed_sha256=digest(seed_path),scope='SINGLE_TARGET_SIGNAL_TECHNICAL_WINDOW',plan=plan)
    suite = unittest.defaultTestLoader.loadTestsFromNames(('tests.test_signal_window',
        'tests.test_public_paper','tests.test_public_transport','tests.test_quote_paper_account',
        'tests.test_causal_intents','tests.test_bar_observation','tests.test_baseline_account'))
    ids = list(test_ids(suite))
    save(output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        source_hashes=sources,prior_artifact_hashes=old,binding=binding,plan=plan,
        seed_path=str(seed_path.relative_to(ROOT)),test_ids=ids,automatic_retries=0,
        transport_limits={k:v for k,v in LIMITS.items() if k not in ('observe_seconds','poll_seconds')},
        performance_evaluation=False))
    for name in sources:
        path = output/'source_snapshot'/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes((ROOT/name).read_bytes())
    with (output/'tests.log').open('x') as stream:
        result = unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(output/'tests.json',dict(registered=len(ids),executed=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped)))
    if not result.wasSuccessful() or result.skipped or result.testsRun!=len(ids):
        raise ValueError('registered tests failed')
    check_hashes(sources|old)
    save(output/'prepared_verification.json',dict(status='PREPARED_NOT_PUBLICLY_EXECUTED',
        registration_sha256=digest(output/'registration.json'),tests=result.testsRun,
        artifact_hashes={str(p.relative_to(output)):digest(p) for p in output.rglob('*') if p.is_file()},
        sources_unchanged=len(sources),prior_artifacts_unchanged=len(old),public_requests=0))
    print(json.dumps(dict(status='PREPARED_NOT_PUBLICLY_EXECUTED',tests=result.testsRun,
                         plan=plan,prepared_sha256=digest(output/'prepared_verification.json')),indent=2))


def wait_for_launch(plan):
    wall_start,mono_start = time.time_ns(),time.monotonic_ns()
    last_notice = -30000
    while True:
        wall,mono = time.time_ns(),time.monotonic_ns()
        if abs((wall-wall_start)-(mono-mono_start))>1000000000:
            raise ValueError('clock changed during pre-window wait')
        now = wall//1000000
        choice = admission(plan,now)
        if choice!='WAIT_WITHOUT_NETWORK':return choice
        elapsed = (mono-mono_start)//1000000
        if elapsed-last_notice>=30000:
            print(f'Waiting without network; {(plan["launch_ms"]-now)/1000:.1f}s to launch.',flush=True)
            last_notice = elapsed
        time.sleep(min(1,(plan['launch_ms']-now)/1000))


def execute(output,prepared_sha256):
    if digest(output/'prepared_verification.json')!=prepared_sha256:
        raise ValueError('prepared verification hash differs')
    prepared = load(output/'prepared_verification.json')
    if prepared['status']!='PREPARED_NOT_PUBLICLY_EXECUTED':raise ValueError('not prepared')
    for name,h in prepared['artifact_hashes'].items():
        if digest(output/name)!=h:raise ValueError('preparation artifact changed: '+name)
    reg = load(output/'registration.json');plan = reg['plan'];binding = reg['binding']
    check_hashes(reg['source_hashes']|reg['prior_artifact_hashes'])
    choice = admission(plan,time.time_ns()//1000000)
    if choice=='TOO_EARLY':
        print(json.dumps(dict(status=choice,network_requests=0)));return
    attempt = output/'public';attempt.mkdir(exist_ok=False)
    store = None;rest = None
    try:
        choice = wait_for_launch(plan)
        if choice!='START':
            save(attempt/'summary.json',dict(status=choice,network_requests=0,live_orders=0,
                                            actual_ms=time.time_ns()//1000000,target_ms=plan['target_close_ms']))
            print(choice,flush=True);return
        save(attempt/'started.json',dict(started_at=datetime.now(timezone.utc).isoformat(),
            registration_sha256=digest(output/'registration.json'),prepared_sha256=prepared_sha256))
        # Recheck after the wait: no changed strategy is silently executed.
        check_hashes(reg['source_hashes'])
        if admission(plan,time.time_ns()//1000000)!='START':raise ValueError('start window elapsed during checks')
        signal = T0Signal.restore(load(ROOT/reg['seed_path'])['account']['signal'])
        state = initial_state(signal,'one',time.time_ns()//1000000)
        rest = PublicRest(attempt);store = PublicPaperStore(attempt/'paper.sqlite',binding,state)
        ingest(rest,store,'/fapi/v1/time')
        warmup = 0
        for _ in range(LIMITS['warmup_pages']):
            if time.time_ns()//1000000>plan['latest_arm_ms']:raise ValueError('target passed during warmup')
            next_ms = store.state()['account']['signal']['state']['last_open_ms']+60000
            emitted = ingest(rest,store,'/fapi/v1/klines',dict(symbol='BTCUSDC',interval='1m',startTime=next_ms,limit=1000))
            count = next((x['count'] for x in emitted if x['kind']=='BARS_APPLIED'),None)
            if count is None:raise ValueError('warmup rejected')
            warmup += count
            last = store.state()['account']['signal']['state']['last_open_ms']
            if time.time_ns()//1000000-(last+60000)<=120000:break
        else:raise ValueError('warmup page bound')
        ingest(rest,store,'/fapi/v1/premiumIndex',dict(symbol='BTCUSDC'))
        ingest(rest,store,'/fapi/v1/fundingRate',funding_query(store.state()))
        c = local_clock();require_preclose_arm(plan,c['received_utc_ns']//1000000)
        store.commit('ARM','ARM','{}',c,'one')
        if store.state()['account']['phase']!='OBSERVE':raise ValueError('ARM rejected')
        armed = store.state()['account']['armed_ms'];cycles = 0
        print('Armed BEFORE registered bar close. Waiting for the actual new signal.',flush=True)
        deadline = min(rest.deadline-10,time.monotonic()+max(0,(plan['stop_ms']-time.time_ns()//1000000)/1000))
        while deadline-time.monotonic()>=25:
            now = time.time_ns()//1000000
            if now-store.state()['server_received_ms']>=plan['server_refresh_ms']:
                ingest(rest,store,'/fapi/v1/time')
            receive_cycle(rest,store);cycles += 1
            account = store.state()['account']
            print(f'Cycle {cycles}: signals={account["observed_signals"]}, entries={account["entries"]}, quantity={account["quantity"]}',flush=True)
            time.sleep(min(plan['poll_seconds'],max(0,deadline-time.monotonic())))
        store.commit('END','END','{}',local_clock(),'one')
        if store.state()['account']['quantity'] and rest.deadline-time.monotonic()>=5:
            ingest(rest,store,'/fapi/v1/ticker/bookTicker',dict(symbol='BTCUSDC'))
        if rest.deadline-time.monotonic()>=5:ingest(rest,store,'/fapi/v1/time')
        final = store.state();save(attempt/'final_state.json',final)
        initial = json.loads(store.db.execute("SELECT value FROM meta WHERE key='initial'").fetchone()[0])
        rows = store.db.execute('SELECT id,kind,raw,clock,state,outputs FROM receipts ORDER BY seq').fetchall()
        audit = audit_rows(initial,rows,plan['target_close_ms'])
        save(attempt/'independent_audit.json',audit)
        store.close();store = None
        replay = verify_database(attempt,binding)
        if replay['public_raw_matches']!=rest.count:raise ValueError('unmatched public receipt')
        summary = dict(status='COMPLETE_REGISTERED_TARGET_ATTEMPT',target_result=audit['status'],
            armed_ms=armed,last_received_utc_ns=final['account']['last_received_utc_ns'],
            target_close_ms=plan['target_close_ms'],public_requests=rest.count,raw_bytes=rest.bytes,
            cycles=cycles,warmup_minutes=warmup,observed_signals=final['account']['observed_signals'],
            entries=final['account']['entries'],exits=final['account']['exits'],
            observation_end_exits=audit['observation_end_exits'],other_exits=audit['other_exits'],
            residual_quantity=final['account']['quantity'],cash=final['account']['cash'],
            faults=final['faults'],review_reasons=final['review_reasons'],
            performance_evaluation=False,live_orders=0,strategy_adoptions=0)
        save(attempt/'summary.json',summary)
        check_hashes(reg['source_hashes']|reg['prior_artifact_hashes'])
        save(attempt/'verification.json',dict(status='PASS_REPLAY_AND_INDEPENDENT_LEDGER_LINEAGE',
            replay=replay,target_result=audit['status'],
            artifact_hashes={str(p.relative_to(attempt)):digest(p) for p in attempt.rglob('*') if p.is_file()}))
        print(json.dumps(summary,indent=2),flush=True)
    except Exception as exc:
        if store is not None:
            # Preserve the real last state. Do not invent a close after failure.
            save(attempt/'failed_state.json',store.state())
        save(attempt/'failure.json',dict(type=type(exc).__name__,reason=str(exc),
            public_requests=rest.count if rest else 0,live_orders=0,automatic_retry=False))
        raise
    finally:
        if store is not None:store.close()


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode',required=True)
    p = sub.add_parser('prepare');p.add_argument('--output',type=Path,required=True);p.add_argument('--target',required=True)
    p = sub.add_parser('execute');p.add_argument('--output',type=Path,required=True);p.add_argument('--prepared-sha256',required=True)
    args = parser.parse_args()
    if args.mode=='prepare':
        target = datetime.fromisoformat(args.target.replace('Z','+00:00'))
        if target.tzinfo is None:raise ValueError('explicit timezone required')
        args.output.mkdir(parents=True,exist_ok=False)
        try:prepare(args.output,int(target.timestamp()*1000))
        except Exception as exc:
            save(args.output/'failure.json',dict(type=type(exc).__name__,reason=str(exc)))
            raise
    else:execute(args.output,args.prepared_sha256)
