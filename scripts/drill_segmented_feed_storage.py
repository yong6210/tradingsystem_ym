"""Offline process-crash, archive equivalence and rotation/retry drill. No network."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.shared_feed_storage import SharedStorageBudget, BudgetedJournal, SegmentedAudit
from app.research.data.durable_capture_log import inspect_journal, iter_committed, file_hash
from app.research.data.segmented_feed_collector import run_bounded
from app.research.data.segmented_feed_audit import audit_epoch
from app.research.data.feed_coverage_audit import audit_epoch as old_audit_epoch
from app.research.foundation.forward_data_contract import load_contract
from tests.test_bounded_feed_collector import ScriptedTransport

STAGES = ('after_append', 'after_raw_fsync', 'after_checkpoint_fsync',
          'after_checkpoint_replace', 'after_directory_fsync')
CONTRACT = dict(run_id='offline-storage-crash', max_bytes=1_000_000, min_free_bytes=0)
SOURCES = [
    'app/research/data/shared_feed_storage.py',
    'app/research/data/segmented_feed_audit.py',
    'app/research/data/segmented_feed_collector.py',
    'scripts/drill_segmented_feed_storage.py',
    'tests/test_segmented_feed_storage.py',
]


def save(path, value):
    # Harness evidence is outside the simulated run budget, never a collector
    # fallback writer. Reports do not represent live publications.
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')


def child(root, target, stage):
    disk=SharedStorageBudget.create(root, **CONTRACT)
    raw=BudgetedJournal.create(root/'raw',budget=disk,run_id=CONTRACT['run_id'],rotation_bytes=1024,max_record_bytes=768)
    audit=BudgetedJournal.create(root/'audit',budget=disk,run_id=CONTRACT['run_id'],rotation_bytes=1024,max_record_bytes=768)
    raw.append(dict(value=1,pad='r'*250)); receipt=raw.commit()
    audit.append(dict(raw_sequence=1,raw_sha256=receipt.record_sha256,pad='a'*250)); audit.commit()
    def stop(actual):
        if actual==stage:
            print('READY',flush=True)
            while True: time.sleep(1)
    (raw if target=='raw' else audit).hook=stop
    # Each second record forces a new physical segment before the tested hook.
    raw.append(dict(value=2,pad='r'*250)); receipt=raw.commit()
    audit.append(dict(raw_sequence=2,raw_sha256=receipt.record_sha256,pad='a'*250)); audit.commit()
    raise AssertionError('hook not reached')


def crash_case(directory, target, stage):
    directory.mkdir()
    root=directory/'capture'
    proc=subprocess.Popen([sys.executable,__file__,'--child',str(root),'--target',target,'--stage',stage],
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        if not select.select([proc.stdout],[],[],15)[0]:
            raise TimeoutError('crash hook did not become ready')
        ready=proc.stdout.readline()
        if ready.strip()!='READY':
            raise AssertionError('child failed before hook: '+ready+proc.stderr.read())
        proc.kill()
        stdout,stderr=proc.communicate(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill(); proc.wait(timeout=10)
    (directory/'child.log').write_text(ready+stdout+stderr)
    assert proc.returncode==-signal.SIGKILL
    old_hashes={str(p.relative_to(root)):file_hash(p) for p in root.rglob('*') if p.is_file()}
    raw_state,audit_state=inspect_journal(root/'raw'),inspect_journal(root/'audit')
    raw_rows,audit_rows=list(iter_committed(root/'raw')),list(iter_committed(root/'audit'))
    renamed=stage in ('after_checkpoint_replace','after_directory_fsync')
    expected_raw=2 if target=='audit' or renamed else 1
    expected_audit=2 if target=='audit' and renamed else 1
    assert len(raw_rows)==expected_raw and len(audit_rows)==expected_audit
    for row in audit_rows:
        ref=row['payload']
        assert raw_rows[ref['raw_sequence']-1]['sha256']==ref['raw_sha256']
    disk=SharedStorageBudget.resume(root,**CONTRACT)
    actual=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    assert disk.used==actual
    before=disk.snapshot()
    # Resume storage only: no market, clock, connection or retry state restored.
    resumed=BudgetedJournal.resume(root/target,budget=disk)
    assert resumed.recovery['live_market_state_restored'] is False
    recovery_fence=resumed.publication_fence().sequence
    resumed.close(); disk.close()
    assert old_hashes=={str(p.relative_to(root)):file_hash(p) for p in root.rglob('*') if p.is_file()}
    result=dict(target=target,stage=stage,exit_code=proc.returncode,raw=raw_state,audit=audit_state,
                expected_raw=expected_raw,expected_audit=expected_audit,recovery_fence=recovery_fence,
                aggregate=before,all_files_preserved=True,
                unaudited_committed_raw=len(raw_rows)-len(audit_rows),live_market_state_restored=False)
    save(directory/'result.json',result)
    return result


def archive_case(directory):
    directory.mkdir()
    source=ROOT/'reports/validation/bounded_feed_v3_20260918'
    plan=json.loads((source/'plan.json').read_text())
    scope={k:plan[k] for k in ('window_start_ns','window_end_ns','clock_domain')}
    disk=SharedStorageBudget.create(directory/'capture',run_id=plan['run_id'],max_bytes=16*1024**2,min_free_bytes=0)
    rows=[]
    for old in sorted(source.glob('epoch-*')):
        audit=SegmentedAudit(disk.root/old.name,budget=disk,rotation_bytes=16*1024,max_record_bytes=8*1024)
        with (old/'batches.jsonl').open() as stream:
            for line in stream: audit.append(json.loads(line))
        audit.close()
        legacy=old_audit_epoch(old/'journal',old/'batches.jsonl',**scope)
        current=audit_epoch(old/'journal',disk.root/old.name,**scope)
        equivalent=('status','intervals','exclusions','valid_batches','last_audited_sequence',
                    'committed_raw_records','unaudited_committed_records','first_audited_publication_ns',
                    'last_audited_publication_ns','valid_audit_bytes','unaudited_audit_bytes','audit_sha256',
                    'errors','processor_errors','clean_stop_audited')
        assert {k:legacy[k] for k in equivalent}=={k:current[k] for k in equivalent}
        assert current['audit_recovery']['committed_segments']>1
        rows.append(dict(epoch=old.name,equivalent_fields=list(equivalent),audit=current))
    inventory=disk.snapshot(); disk.close()
    result=dict(status='ARCHIVED_PAYLOAD_REPLAY_EQUIVALENT',new_market_capture=False,
                source=str(source.relative_to(ROOT)),epochs=rows,storage=inventory)
    save(directory/'result.json',result)
    return result


async def collector_case(directory):
    directory.mkdir()
    policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json')
    original=SegmentedAudit.__init__
    def small(writer,path,**kwargs):
        if Path(path).name=='audit': kwargs.update(rotation_bytes=4096,max_record_bytes=3840)
        original(writer,path,**kwargs)
    with patch.object(SegmentedAudit,'__init__',small):
        result=await run_bounded(directory/'capture',duration_ns=2_500_000_000,
            transport=ScriptedTransport(),policy=policy,disconnect_once_after_ns=550_000_000)
    assert result['stop_reason']=='ORIGINAL_DEADLINE' and result['retries_used']==1
    assert len(result['epochs'])==2 and all(not r['errors'] for r in result['audits'])
    assert all(r['audit_recovery']['committed_segments']>1 for r in result['audits'])
    assert result['storage_after_result']['used_bytes']==sum(p.stat().st_size for p in (directory/'capture').rglob('*') if p.is_file())
    save(directory/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path)
    parser.add_argument('--child',type=Path)
    parser.add_argument('--target',choices=('raw','audit'))
    parser.add_argument('--stage',choices=STAGES)
    args=parser.parse_args()
    if args.child:
        child(args.child.resolve(),args.target,args.stage)
        return
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    snapshot=output/'source_snapshot'; snapshot.mkdir()
    for name in SOURCES:
        dest=snapshot/name; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes((ROOT/name).read_bytes())
    save(output/'plan.json',dict(purpose='OFFLINE_SEGMENTED_STORAGE_QUALIFICATION',
        crash_cases=[dict(target=target,stage=stage) for target in ('raw','audit') for stage in STAGES],
        archive_source='reports/validation/bounded_feed_v3_20260918',
        collector_window_ns=2_500_000_000,disconnect_after_ns=550_000_000,
        source_hashes={name:file_hash(ROOT/name) for name in SOURCES},network_requests=0,
        live_restart=False,full_day_ready=False))
    crashes=[crash_case(output/(target+'_'+stage),target,stage) for target in ('raw','audit') for stage in STAGES]
    archived=archive_case(output/'archive_replay')
    collector=asyncio.run(collector_case(output/'rotation_reconnect'))
    result=dict(status='PASS_SCOPED_STORAGE_DRILLS',sigkill_cases=len(crashes),
                archived_batches=sum(e['audit']['valid_batches'] for e in archived['epochs']),
                rotation_reconnect_epochs=len(collector['epochs']),
                all_crash_files_preserved=all(c['all_files_preserved'] for c in crashes),
                network_requests=0,actual_orders=0,full_day_ready=False,live_restart=False)
    save(output/'result.json',result)
    print(json.dumps(result))


if __name__=='__main__': main()
