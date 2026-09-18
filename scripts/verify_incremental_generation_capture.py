"""Predeclared 40s normal/18s burst scenarios and eight actual SIGKILL boundaries."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.data.incremental_generation_capture import run_synthetic_capture
from app.research.data.durable_capture_log import decoded,encoded,file_hash
from app.research.data.feed_coverage_audit import combine_epochs
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.read_archived_generation_capture import replay_capture
from scripts.verify_continuous_generation_capture import save
from tests.incremental_audit_fixture import COMPARABLE
from tests.test_archived_generation_capture import reference_replay
from tests.test_retained_feed_collector import inventory as raw_inventory

def inventory(root):
    # Stable representation for both fresh runs and saved-JSON verification.
    return decoded(encoded(raw_inventory(root)))


STAGES = ('after_parent_manifest_replace','retention:after_checkpoint_replace',
          'retire_intent:after_checkpoint_fsync','retire:after_unlink',
          'retire_done:after_checkpoint_fsync','retire_done:after_directory_fsync',
          'incremental_anchor:before_promote','incremental_anchor:after_promote')


async def fixed_case(output, *, seconds, per_tick, required, existing=False):
    root = output/'run'
    if existing:
        result = decoded((output/'result.json').read_bytes())
        baselines = decoded((output/'pre_archive_generation_hashes.json').read_bytes())
        producer = decoded((output/'producer.json').read_bytes())
    else:
        output.mkdir(); root = output/'run'; baselines = {}
        save(output/'plan.json',dict(duration_seconds=seconds,rotation_seconds=8,seal_seconds=.5,
            levels_per_side=1000,per_tick=per_tick,required_normal_completion=required,
            no_parameter_search=True,public_requests=0,actual_orders=0))
        def hook(stage):
            if stage == 'end:after_directory_fsync':
                name = f'generation-{len(baselines):04d}'
                baselines[name] = inventory(root/name)
        transport = QueuedTransport(per_tick=per_tick)
        result = await run_synthetic_capture(root,duration_ns=seconds*10**9,rotation_ns=8*10**9,
                                             transport=transport,hook=hook)
        save(output/'result.json',result); save(output/'producer.json',[s.summary() for s in transport.sockets])
        save(output/'pre_archive_generation_hashes.json',baselines)
        producer = [s.summary() for s in transport.sockets]
    assert result['storage']['reserved_bytes'] == 0 and result['pipeline']['children_reaped']
    assert result['public_connection_attempts'] == 2 and result['snapshot_requests'] == 1
    assert all(p['producer_thread_joined'] for p in producer)
    if required: assert result['outcome'] == 'ORIGINAL_DEADLINE',result['reason']
    if result['outcome'] != 'ORIGINAL_DEADLINE':
        row = dict(completed=False,outcome=result['outcome'],reason=result['reason'],
            pipeline_error=result['pipeline']['error'],children_reaped=True,reservations_released=True,
            no_retry_or_tuning=True,public_requests=0)
        save(output/'summary.json',row); save(output/'final_hashes.json',inventory(root)); return row
    before = inventory(root)
    if existing:
        from app.research.data.snapshot_feed_audit import audit_epoch
        scope = {k:result['audit'][k] for k in ('window_start_ns','window_end_ns','clock_domain')}
        actual = replay_capture(root,**result['handle'])
        expected = audit_epoch(output/'reference/raw',output/'reference/audit',**scope,max_intervals=10000)
    else:
        actual,expected = reference_replay(root,output/'reference',result['handle'])
    assert actual['status'] == 'COMPLETE' and encoded(actual['audit']) == encoded(result['audit'])
    for field in COMPARABLE: assert encoded(actual['audit'][field]) == encoded(expected[field]),field
    assert actual['source_reads']['RAW'] == 0 and actual['source_reads']['GZIP'] > 0
    assert replay_capture(root,**result['handle']) == actual and inventory(root) == before
    persisted = dict(public=0,market=0)
    def count(row):
        p = row['payload']
        if p['kind'] in ('WS','CLOSING_WS'): persisted[p['channel']] += 1
    replay_capture(root,**result['handle'],raw_sink=count)
    for p in producer:
        assert not p['overflow'] and p['received'] == persisted[p['channel']]
        assert p['produced'] == p['received']+p['queued_at_stop']
    costs = []
    policy_bytes = (root/'generation-retention-policy.json').stat().st_size
    for r in result['pipeline']['generations']:
        name = f'generation-{r["index"]:04d}'; original = baselines[name]; final = inventory(root/name)
        removed = set(original)-set(final)
        assert all('/segment-' in p and p.endswith('.jsonl') for p in removed)
        assert all(original[p] == final[p] for p in set(original)&set(final))
        assert sum(original[p][0] for p in removed) == r['raw_bytes']
        # The end hook precedes the normal next-generation handoff document.
        # Include that non-retention file in both sides of the same-run comparison.
        handoff_bytes = final.get('handoff.json',[0,None])[0]
        sealed_bytes = sum(v[0] for v in original.values())
        start_bytes,final_bytes = sealed_bytes+handoff_bytes,sum(v[0] for v in final.values())
        assert start_bytes-final_bytes-policy_bytes == r['conservative_net_savings_bytes'] > 0
        costs.append(dict(generation=r['index'],sealed_generation_bytes=sealed_bytes,normal_handoff_bytes=handoff_bytes,
                          pre_archive_bytes=start_bytes,post_archive_bytes=final_bytes,
                          net_reduction_bytes=start_bytes-final_bytes,removed_source_bytes=r['raw_bytes']))
    # Count logical replay work on THIS source, independently of wall time.
    # The old implementation replays 0..i twice; the new path replays i twice.
    work = result['pipeline']['audit_work']
    assert len(work) == 2*result['generations']
    previous_hash = '0'*64
    for index in range(result['generations']):
        directory = root/f'generation-{index:04d}'
        start = decoded((directory/'start.json').read_bytes())
        end = decoded((directory/'end.json').read_bytes())
        rows = work[2*index:2*index+2]
        assert [r['candidate'] for r in rows] == [False, True]
        for r in rows:
            assert r['index'] == index and r['audited_generations'] == 1
            assert r['processed_records'] == end['global_sequence']-start['global_sequence']
            assert r['processed_batches'] == end['global_audit_batches']-start['global_audit_batches']
        proof = decoded((directory/'archive-proof.json').read_bytes())
        assert proof['audit_receipt']['previous_proof_sha256'] == previous_hash
        previous_hash = file_hash(directory/'archive-proof.json')
    assert result['pipeline']['latest_proof_sha256'] == previous_hash
    assert result['pipeline']['trusted_completed_generations'] == result['generations']
    new_records = sum(r['processed_records'] for r in work)
    old_records = 2*sum(decoded((root/f'generation-{i:04d}'/'end.json').read_bytes())['global_sequence']
                         for i in range(result['generations']))
    new_batches = sum(r['processed_batches'] for r in work)
    assert new_records == 2*actual['audit']['last_audited_sequence']
    assert new_batches == 2*actual['audit']['valid_batches']
    assert new_records < old_records
    incremental_work = dict(actual_replayed_records=new_records,
        from_origin_replayed_records_same_capture=old_records,
        avoided_replayed_records=old_records-new_records,
        avoided_record_fraction=1-new_records/old_records,
        actual_replayed_batches=new_batches,
        max_audit_worker_elapsed_ns=max(r['elapsed_ns'] for r in work),
        one_generation_per_pass=True, historical_storage_rechecked=False)
    save(output/'incremental_work.json',incremental_work)
    owned = sum(v[0] for v in before.values()); assert owned == result['storage']['used_bytes']
    scope = {k:result['audit'][k] for k in ('window_start_ns','window_end_ns','clock_domain')}
    quality = combine_epochs(decoded((ROOT/'configs/research/forward_data_policy_v1.json').read_bytes()),[actual['audit']],**scope)
    save(output/'quality.json',quality); save(output/'recovered.json',actual)
    save(output/'reference_audit.json',expected); save(output/'costs.json',costs)
    save(output/'final_hashes.json',before)
    if required: assert result['total_units'] > 62
    row = dict(completed=True,incremental_work=incremental_work,generations=result['generations'],sealed_units=result['total_units'],
        peak_units_per_generation=result['peak_units_per_generation'],rotation_reconnects=0,additional_snapshots=0,
        max_handoff_ns=result['max_handoff_ns'],peak_parent_archive_work_ns=result['pipeline']['peak_parent_work_ns'],
        peak_pending_generations=result['pipeline']['peak_pending_generations'],
        capture_final_bytes=owned,capture_peak_bytes=result['storage']['peak_bytes'],
        peak_effective_bytes=result['storage']['peak_effective_bytes'],
        pre_archive_generation_bytes=sum(c['pre_archive_bytes'] for c in costs),
        post_archive_generation_bytes=sum(c['post_archive_bytes'] for c in costs),
        generation_net_reduction_bytes=sum(c['net_reduction_bytes'] for c in costs),
        raw_bytes_removed=result['pipeline']['raw_bytes_removed'],
        raw_bytes_removed_while_collecting=result['pipeline']['raw_bytes_removed_while_collecting'],
        semantic_fields_compared=17,gzip_only_replay=True,repeated_recovery_no_growth=True,
        dequeued_frames_equal_persisted_frames=True,children_reaped=True,reservations_released=True,
        quality=quality['quality'],long_history_index_bounded=False,full_day_ready=False,public_requests=0,actual_orders=0)
    save(output/'summary.json',row); return row


async def child(output,stage):
    root = output/'run'
    hits = 0
    def hook(current):
        nonlocal hits
        if current != stage: return
        hits += 1
        if stage.startswith('incremental_anchor:') and hits < 2: return
        handle = dict(plan_sha256=file_hash(root/'generation-plan.json'),
                      policy_sha256=file_hash(root/'generation-retention-policy.json'))
        save(output/'handle.json',handle); save(output/'before_crash_hashes.json',inventory(root))
        print(json.dumps(dict(stage=stage,pid=os.getpid())),flush=True)
        signal.pause(); raise RuntimeError('expected SIGKILL')
    await run_synthetic_capture(root,duration_ns=6*10**9,rotation_ns=2*10**9,
                                transport=QueuedTransport(),hook=hook)
    raise RuntimeError('stage not reached')


def recover(output,repeat):
    root = output/'run'; before = inventory(root)
    result = replay_capture(root,**decoded((output/'handle.json').read_bytes()))
    assert result['status'] == 'INTERRUPTED_PREFIX_PRESERVED'
    assert inventory(root) == before
    save(output/('repeat.json' if repeat else 'recovery.json'),result)


def crash_case(output,stage):
    output.mkdir(); command = [sys.executable,str(Path(__file__).resolve()),'--output',str(output)]
    process = subprocess.Popen(command+['--child',stage],cwd=ROOT,stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,start_new_session=True)
    try:
        with selectors.DefaultSelector() as watch:
            watch.register(process.stdout,selectors.EVENT_READ)
            if not watch.select(25): raise RuntimeError('archive crash stage timeout')
            line = process.stdout.readline(4097)
        if not line or len(line)>4096: raise RuntimeError(process.stderr.read().decode())
        ready = json.loads(line); assert ready['stage'] == stage
        os.kill(process.pid,signal.SIGKILL); process.wait(timeout=10); assert process.returncode == -9
        save(output/'signal.json',ready|dict(returncode=-9))
    finally:
        if process.poll() is None: os.killpg(process.pid,signal.SIGKILL); process.wait(timeout=10)
        process.stdout.close(); process.stderr.close()
    before = inventory(output/'run')
    for flag in ('--recover','--repeat'):
        p = subprocess.run(command+[flag],cwd=ROOT,capture_output=True,text=True,timeout=30)
        save(output/(flag[2:]+'_process.json'),dict(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr))
        assert p.returncode == 0,p.stderr
        assert inventory(output/'run') == before
    first = decoded((output/'recovery.json').read_bytes()); second = decoded((output/'repeat.json').read_bytes())
    assert first == second
    save(output/'final_hashes.json',before)
    return dict(passed=True,stage=stage,parent_sigkill_returncode=-9,recovery_no_growth=True,
        repeated_recovery_identical=True,source_reads=first['source_reads'],
        original_window_preserved=True,live_market_state_restored=False,public_requests=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--child',choices=STAGES); parser.add_argument('--recover',action='store_true')
    parser.add_argument('--repeat',action='store_true'); parser.add_argument('--continue-normal',action='store_true'); args = parser.parse_args()
    if args.child: asyncio.run(child(args.output,args.child))
    elif args.recover or args.repeat: recover(args.output,args.repeat)
    else:
        if not args.continue_normal: args.output.mkdir()
        normal = asyncio.run(fixed_case(args.output/'normal',seconds=40,per_tick=20,required=True,existing=args.continue_normal)); print(json.dumps(normal),flush=True)
        burst = asyncio.run(fixed_case(args.output/'burst',seconds=18,per_tick=200,required=False)); print(json.dumps(burst),flush=True)
        crashes = []
        for i,stage in enumerate(STAGES):
            row = crash_case(args.output/f'crash-{i:02d}',stage); crashes.append(row); print(json.dumps(row),flush=True)
        save(args.output/'summary.json',dict(normal=normal,burst=burst,crashes=crashes,
            public_requests=0,private_requests=0,actual_orders=0,full_day_ready=False))
