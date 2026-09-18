"""E031: profile fixed archived public captures, with no network or PnL model."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = ROOT / 'reports/validation'


def load(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def check(hashes, root=ROOT):
    for name, expected in hashes.items():
        if sha(root / name) != expected:
            raise ValueError('changed evidence: ' + name)


def horizon_bounds(start, end):
    span = max(0, end - start)
    return {str(seconds): span // (seconds * 10**9) for seconds in (3, 60, 300)}


def trade_profile(events):
    seen, duplicate, conflict, backwards, gaps = {}, 0, 0, 0, 0
    previous = None
    for row in events:
        event = row['data']; identity = event['a']
        if identity in seen:
            duplicate += 1
            conflict += int(seen[identity] != event)
            continue
        if previous is not None:
            backwards += int(identity < previous)
            gaps += int(identity > previous + 1)
        seen[identity] = event; previous = identity
    return dict(rows=len(events), unique_ids=len(seen), duplicates=duplicate,
                conflicts=conflict, backwards=backwards, gap_transitions=gaps)


def temporal_join_audit(trades, quotes):
    matched, future, examples = 0, 0, []
    for trade in trades:
        possible = [q for q in quotes if q['T'] <= trade['data']['T']]
        if not possible:
            continue
        chosen = max(possible, key=lambda q: (q['T'], q['u']))
        matched += 1
        if chosen['available_ns'] > trade['available_ns']:
            future += 1
            if len(examples) < 5:
                examples.append(dict(trade_id=trade['data']['a'], depth_u=chosen['u'],
                    depth_T=chosen['T'], trade_T=trade['data']['T'],
                    unavailable_for_ms=(chosen['available_ns']-trade['available_ns'])/1e6))
    return dict(event_time_matches=matched, later_available_quote_matches=future, examples=examples,
                interpretation='Counterfactual whole-file T-asof join; not a finding in an existing strategy')


def profile(name, events, quotes, extra):
    counts = Counter(row['data']['e'] for row in events)
    trades = [r for r in events if r['data']['e'] == 'aggTrade']
    if not trades or not quotes:
        raise ValueError('expected both streams: ' + name)
    start = max(min(q['available_ns'] for q in quotes), min(t['available_ns'] for t in trades))
    end = min(max(q['available_ns'] for q in quotes), max(t['available_ns'] for t in trades))
    return dict(name=name, event_counts=dict(counts), trade_profile=trade_profile(trades),
        first_receive_utc=min(e['utc'] for e in events), last_receive_utc=max(e['utc'] for e in events),
        common_observed_span_seconds=max(0, end-start)/1e9,
        optimistic_nonoverlapping_window_upper_bound=horizon_bounds(start,end),
        published_distinct_depth_updates=len(quotes),
        temporal_join=temporal_join_audit(trades,quotes),
        continuous_coverage_certified=False, maker_fills_observed=0, **extra)


def original():
    folder = BASE / 'execution_data_fitness_20260917'
    rows = lines(folder / 'public_events.jsonl')
    events = [dict(data=r['message']['data'], available_ns=r['received_monotonic_ns'],
                   utc=r['received_utc']) for r in rows]
    depth = {r['data']['u']:r['data'] for r in events if r['data']['e']=='depthUpdate'}
    published = lines(BASE / 'public_depth_replay_20260917/rechecked_replay/quotes.jsonl')
    quotes = [dict(u=q['u'], T=depth[q['u']]['T'], available_ns=q['available_ns']) for q in published]
    return profile(folder.name,events,quotes,dict(availability='Legacy receive clock + conservative snapshot boundary; no native REST monotonic or durable-publication clock', closing_frames=0))


def durable(name):
    folder = BASE/name; journal = folder/'journal'
    cp = load(journal/'checkpoint.json'); records = []; previous = '0'*64
    for entry in cp['segments']:
        path = journal/entry['name']
        if path.stat().st_size != entry['bytes'] or sha(path) != entry['sha256']:
            raise ValueError('journal segment mismatch')
        for r in lines(path)[1:]:
            body = {k:v for k,v in r.items() if k!='sha256'}
            digest = hashlib.sha256((json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()).hexdigest()
            if r['sequence'] != len(records)+1 or r['previous_record_sha256'] != previous or digest != r['sha256']:
                raise ValueError('journal chain mismatch')
            records.append(r); previous = digest
    if len(records)!=cp['last_sequence'] or previous!=cp['last_record_sha256']:
        raise ValueError('journal checkpoint mismatch')
    batches = lines(folder/'batches.jsonl'); availability = {}; quotes_by_u = {}; expected = 1
    for batch in batches:
        if batch['first_sequence'] != expected or records[batch['last_sequence']-1]['sha256'] != batch['record_sha256']:
            raise ValueError('batch sequence/hash mismatch')
        obs = batch['observation']; published = obs['published_ns']
        for seq in range(batch['first_sequence'],batch['last_sequence']+1):
            if not records[seq-1]['payload']['received_ns'] <= batch['committed_ns'] <= published:
                raise ValueError('receipt/commit/publication order')
            availability[seq] = published
        expected = batch['last_sequence']+1
        if obs['eligible'] and obs['quote']:
            q = obs['quote']; quotes_by_u.setdefault(q['u'],published)
    if expected != len(records)+1:
        raise ValueError('batch coverage')
    deadline = load(folder/'probe_result.json')['planned_end_ns']
    events, closing, late = [], 0, 0
    for r in records:
        p = r['payload']
        if p['kind']=='CLOSING_WS': closing += 1
        if p['kind']!='WS': continue
        if availability[r['sequence']] >= deadline:
            late += 1
            continue
        events.append(dict(data=json.loads(p['wire_text'])['data'], available_ns=availability[r['sequence']],
            utc=datetime.fromtimestamp(p['received_utc_ns']/1e9,timezone.utc).isoformat()))
    depth = {r['data']['u']:r['data'] for r in events if r['data']['e']=='depthUpdate'}
    quotes = [dict(u=u,T=depth[u]['T'],available_ns=t) for u,t in quotes_by_u.items()]
    return profile(name,events,quotes,dict(availability='Recorded durable batch publication; eligible point observations only',
        journal_rows_verified=len(records), batches_verified=len(batches), closing_frames=closing,
        WS_published_at_or_after_deadline_excluded=late))


def main():
    out = BASE/'e031_microstructure_fitness_20260919'; out.mkdir(exist_ok=False)
    inputs = {}
    def include(path): inputs[str(path.relative_to(ROOT))] = sha(path)
    specs = [('execution_data_fitness_20260917','data_fitness.json','artifact_hashes'),
             ('public_depth_reconnect_v2_20260917','verification.json','artifact_hashes'),
             ('durable_market_feed_v2_20260917','verification.json','artifact_hashes')]
    for directory,manifest,key in specs:
        folder=BASE/directory; proof=load(folder/manifest); check(proof[key],folder); include(folder/manifest)
        for name in proof[key]: include(folder/name)
        first_key = 'first_probe_artifact_hashes' if 'durable' in directory else 'first_attempt_artifact_hashes'
        first_dir = proof.get('preserved_first_probe') or proof.get('preserved_first_attempt')
        if first_dir:
            check(proof[first_key], ROOT/first_dir)
            for name in proof[first_key]: include(ROOT/first_dir/name)
    for name in ['public_depth_replay_20260917/rechecked_replay/quotes.jsonl',
                 'public_depth_replay_20260917/rechecked_replay/replay_report.json',
                 'e021_public_paper_20260919/summary.json', 'selected_capture_20260918/scenario_result.json',
                 'capture_resources_20260918/verification.json',
                 'tool_data_fit_20260919/incremental_book_L2_probe.json','tool_data_fit_20260919/trades_probe.json']:
        include(BASE/name)
    old=load(BASE/'e030_pair_account_20260919/registration.json')
    protected=old['protected_hashes'] | old['source_hashes']; check(protected)
    sources = {n:sha(ROOT/n) for n in ['scripts/audit_microstructure_fitness.py','tests/test_microstructure_fitness.py','docs/research/experiments/E031_MICROSTRUCTURE_FITNESS.md']}
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),classification='SCOPED_POSTHOC_DATA_FITNESS_NO_STRATEGY_RUN',input_hashes=inputs,source_hashes=sources,protected_hashes=protected,
        raw_joint_capture_count=3,window_seconds=[3,60,300],network_market_requests=0,actual_orders=0))
    suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_microstructure_fitness')
    with (out/'tests.log').open('w') as f: result=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped: raise ValueError('boundary tests failed')
    results=[original(),durable('durable_market_feed_20260917'),durable('durable_market_feed_v2_20260917')]
    save(out/'profiles.json',results)
    reconnect=[]
    for name in ['public_depth_reconnect_20260917','public_depth_reconnect_v2_20260917']:
        rows=lines(BASE/name/'capture.jsonl'); types=Counter()
        for r in rows:
            if r.get('kind')=='WS_MESSAGE':
                types[json.loads(r['wire_text'])['data']['e']]+=1
        if types.get('aggTrade',0): raise ValueError('unexpected reconnect trade stream')
        reconnect.append(dict(name=name,raw_rows=len(rows),event_counts=dict(types),session_summary=load(BASE/name/'session_summary.json'),note='Depth/bookTicker only; no aggTrade subscription'))
    save(out/'reconnect_scope.json',reconnect)
    now=datetime.now(timezone.utc); public=BASE/'e022_signal_boundary_20260919/public'
    save(out/'scheduled_observation.json',dict(checked_at=now.isoformat(),summary_present=(public/'summary.json').exists(),failure_present=(public/'failure.json').exists(),target_in_future=now<datetime.fromisoformat('2026-09-18T20:00:00+00:00'),modified=False))
    summary=dict(status='INSUFFICIENT_FOR_S06_S11_ECONOMICS',raw_joint_runs=3,
        same_UTC_date='2026-09-17',aggregate_trade_rows=sum(r['trade_profile']['rows'] for r in results),
        observed_span_sum_seconds=sum(r['common_observed_span_seconds'] for r in results),
        window_upper_bounds={str(s):sum(r['optimistic_nonoverlapping_window_upper_bound'][str(s)] for r in results) for s in (3,60,300)},
        naive_event_time_future_quotes=sum(r['temporal_join']['later_available_quote_matches'] for r in results),
        assumptions='Spans are not certified continuous intervals; window bounds are not independent samples',
        maker_fill_calibration=False,strategies_run=0,combination_run=False,actual_orders=0)
    save(out/'summary.json',summary)
    check(inputs);check(sources);check(protected)
    save(out/'verification.json',dict(status='PASS_SCOPED_SOURCE_AND_CLOCK_AUDIT',tests=result.testsRun,
        input_bindings=len(inputs),source_bindings=len(sources),protected_bindings=len(protected),
        artifacts={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()}))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
