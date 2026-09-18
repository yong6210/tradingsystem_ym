"""Offline worker replay equivalence, parent SIGKILL and shared-budget overlap."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.data.archive_segment_reader import cursor_dict,restore_cursor
from app.research.data.background_incremental_audit import BackgroundIncrementalAudits
from app.research.data.background_segment_archive import BackgroundArchives
from app.research.data.durable_capture_log import JournalError,file_hash
from app.research.data.incremental_feed_audit import IncrementalFeedAudit
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_segment_handoff import SealedJournal
from tests import incremental_audit_fixture as fixtures

STAGES=('after_audit_proposal_validated','after_audit_checkpoint_fsync',
        'after_audit_checkpoint_replace','after_audit_checkpoint_directory_fsync')
SOURCES=['app/research/data/incremental_audit_protocol.py','app/research/data/incremental_audit_worker.py',
         'app/research/data/background_incremental_audit.py','tests/incremental_audit_fixture_worker.py',
         'tests/test_background_incremental_audit.py','scripts/drill_background_incremental_audit.py']
PUBLIC=ROOT/'reports/validation/feed_scale_20260918/public_60s/capture'


def save(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2);f.write('\n')


def read(path):return json.loads(path.read_text())
def hashes(root):return {str(p.relative_to(root)):file_hash(p) for p in root.rglob('*') if p.is_file()}


async def until(predicate):
    async with asyncio.timeout(15):
        while not predicate():await asyncio.sleep(.005)


async def complete(owner,work,raw_cursor,audit_cursor):
    manager=BackgroundIncrementalAudits(owner)
    try:
        for a,r in work:
            await until(lambda:manager.pending<2 or manager.failed.is_set())
            manager.submit(a,r)
        await until(lambda:manager.pending<2 or manager.failed.is_set())
        manager.submit_finalize(raw_cursor=raw_cursor,audit_cursor=audit_cursor)
        await manager.finish()
        assert manager.process is None and manager.pending==0
        assert owner.budget.snapshot()['reserved_bytes']==0
        assert all(j['status']=='COMPLETE' and j['returncode']==0 for j in manager.jobs)
        return dict(result=owner.summary(),supervisor=manager.snapshot())
    finally:await manager.close()


async def equivalence(case,**kwargs):
    case.mkdir();fix=fixtures.fixture(case,**kwargs);reports={}
    try:
        for kind in ('raw','gzip'):
            work=fixtures.jobs(fix,compressed=kind=='gzip')
            state=IncrementalFeedAudit.create(fix['root']/(kind+'-state'),budget=fix['budget'],contract=fix['contract'])
            try:
                report=await complete(state,work,fix['raw_cursor'],fix['audit_cursor'])
                report['comparison']={k:report['result'][k]==fix['expected'][k] for k in fixtures.COMPARABLE}
                assert all(report['comparison'].values()),report['comparison']
                reports[kind]=report
            finally:state.close()
        assert reports['raw']['result']['audit_payload_chain_sha256']==reports['gzip']['result']['audit_payload_chain_sha256']
        report=dict(status='PASS',**reports,baseline=fix['expected'],semantic_fields=list(fixtures.COMPARABLE),
            raw_gzip_chain_equal=True,raw_records=fix['raw_cursor'].sequence,audit_records=fix['audit_cursor'].sequence,
            files=hashes(fix['root']))
        save(case/'result.json',report);return report
    finally:fix['budget'].close()


async def child(case,stage):
    plan=read(case/'case_plan.json');root=case/'capture'
    budget=ReservedStorageBudget.resume(root,**plan['budget_contract'])
    state=IncrementalFeedAudit.resume(root/'state',budget=budget,contract=plan['contract'],anchor=plan['anchor'])
    def pause(current):
        if current==stage:
            job=manager.jobs[0]
            assert manager.process is None and job['returncode']==0
            print(json.dumps(dict(stage=stage,pid=os.getpid(),worker_pid=job['pid'],
                                  worker_returncode=job['returncode'],worker_reaped=True)),flush=True)
            while True:signal.pause()
    manager=BackgroundIncrementalAudits(state,_hook=pause)
    manager.submit(*plan['jobs'][5]);await manager.finish()
    raise RuntimeError('crash hook not reached')


async def crashes(out):
    results=[]
    for stage in STAGES:
        case=out/stage;case.mkdir();fix=fixtures.fixture(case,buffered=True,raw_step=3,audit_step=1)
        work=fixtures.jobs(fix,compressed=True)
        state=IncrementalFeedAudit.create(fix['root']/'state',budget=fix['budget'],contract=fix['contract'])
        for pair in work[:5]:state.advance(*pair)
        plan=dict(budget_contract={k:v for k,v in fix['budget'].contract.items() if k!='version'},
            contract=fix['contract'],anchor=state.receipt(),jobs=work,
            raw_cursor=cursor_dict(fix['raw_cursor']),audit_cursor=cursor_dict(fix['audit_cursor']),baseline=fix['expected'])
        save(case/'case_plan.json',plan);state.close();fix['budget'].close()
        proc=subprocess.Popen([sys.executable,__file__,'--child',str(case),'--stage',stage],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
        try:
            if not select.select([proc.stdout],[],[],15)[0]:raise RuntimeError('crash stage timeout')
            line=proc.stdout.readline(16385)
            if not line.endswith(b'\n') or len(line)>16384:raise RuntimeError('crash IPC bound')
            reached=json.loads(line);assert reached['stage']==stage and reached['worker_reaped']
            proc.kill();_,stderr=proc.communicate(timeout=5)
            assert proc.returncode==-signal.SIGKILL and not stderr,stderr
        finally:
            if proc.poll() is None:proc.kill()
            proc.communicate(timeout=5)
        before=hashes(fix['root'])
        (case/'checkpoint_at_recovery.json').write_bytes((fix['root']/'state/checkpoint.json').read_bytes())
        budget=ReservedStorageBudget.resume(fix['root'],**plan['budget_contract']);state=None
        try:
            state=IncrementalFeedAudit.resume(fix['root']/'state',budget=budget,contract=plan['contract'],anchor=plan['anchor'])
            revision=state.receipt()['revision'];assert revision==(5 if stage in STAGES[:2] else 6)
            assert all(file_hash(fix['root']/p)==h for p,h in before.items())
            completed=await complete(state,work[revision:],fix['raw_cursor'],fix['audit_cursor'])
            comparison={k:completed['result'][k]==fix['expected'][k] for k in fixtures.COMPARABLE}
            assert all(comparison.values()),comparison
            assert all(file_hash(fix['root']/p)==h for p,h in before.items() if p!='state/checkpoint.json')
            report=dict(stage=stage,status='PASS',actual_sigkill=True,returncode=proc.returncode,reached=reached,
                recovered_revision=revision,all_precrash_files_unchanged_at_recovery=True,
                other_files_unchanged_after_completion=True,before=before,after=hashes(fix['root']),
                comparison=comparison,**completed)
            save(case/'result.json',report);results.append(report)
        finally:
            if state is not None:state.close()
            budget.close()
    return results


async def kill_worker(case):
    case.mkdir();fix=fixtures.fixture(case)
    state=IncrementalFeedAudit.create(fix['root']/'state',budget=fix['budget'],contract=fix['contract'])
    manager=BackgroundIncrementalAudits(state,_command=[sys.executable,'-m','tests.incremental_audit_fixture_worker','hang'])
    try:
        before=state.path.read_bytes();manager.submit(*fixtures.jobs(fix)[0])
        await until(lambda:manager.process is not None)
        pid=manager.process.pid;os.kill(pid,signal.SIGKILL)
        try:await manager.finish()
        except JournalError:pass
        else:raise AssertionError('worker death accepted')
        assert manager.process is None and manager.jobs[0]['returncode']==-signal.SIGKILL
        assert manager.failed.is_set() and state.failed and fix['budget'].failed
        assert state.path.read_bytes()==before and not manager.results
        assert fix['budget'].snapshot()['reserved_bytes']==0
        report=dict(status='PASS',actual_sigkill=True,worker='HANG_FIXTURE_TRANSPORT_FAILURE',
            checkpoint_unchanged=True,supervisor=manager.snapshot(),files=hashes(fix['root']))
        save(case/'result.json',report);return report
    finally:await manager.close();state.close();fix['budget'].close()


async def overlap(case):
    case.mkdir();fix=fixtures.fixture(case);release=case/'release'
    state=IncrementalFeedAudit.create(fix['root']/'state',budget=fix['budget'],contract=fix['contract'])
    auditor=BackgroundIncrementalAudits(state,_command=[sys.executable,'-m','tests.incremental_audit_fixture_worker','gate',str(release)])
    compressor=BackgroundArchives(fix['root']/'parallel-archives',budget=fix['budget'],
        cursor=restore_cursor(fix['contract']['raw_initial']),
        _command=[sys.executable,'-m','tests.sealed_archive_fixture_worker','gate',str(release)])
    active=None
    try:
        auditor.submit(*fixtures.jobs(fix)[0]);compressor.submit(fix['raw_tickets'][0])
        await until(lambda:auditor.process is not None and compressor.process is not None)
        pending=fix['budget'].snapshot();assert pending['pending_reservations']==2
        active=SealedJournal.create(fix['root']/'active',budget=fix['budget'],run_id=fix['budget'].contract['run_id'])
        active.append(dict(while_both_workers_wait=True));active.commit()
        assert active.publication_fence().sequence==1
        release.write_text('go');await asyncio.gather(auditor.finish(),compressor.finish())
        assert not fix['budget'].failed and fix['budget'].snapshot()['reserved_bytes']==0
        assert state.receipt()['revision']==1
        active.close();active=None
        report=dict(status='PASS',pending_storage=pending,active_journal_committed_while_workers_pending=True,
            auditor=auditor.snapshot(),compressor=compressor.snapshot(),files=hashes(fix['root']),
            full_collector_or_concurrent_compute_load=False)
        save(case/'result.json',report);return report
    finally:
        await auditor.close();await compressor.close()
        if active is not None:active.close()
        state.close();fix['budget'].close()


async def run(out):
    out.mkdir(parents=True,exist_ok=False);public_plan=read(PUBLIC/'plan.json')
    scope={k:public_plan[k] for k in ('window_start_ns','window_end_ns','clock_domain')};originals=hashes(PUBLIC)
    save(out/'plan.json',dict(source_hashes={p:file_hash(ROOT/p) for p in SOURCES},stages=STAGES,
        public_source=str(PUBLIC.relative_to(ROOT)),public_source_hashes=originals,public_scope=scope,
        synthetic=dict(seconds=1,buffered=True,raw_step=3,audit_step=1),public_raw_step=200,public_audit_step=25,
        new_network_requests=0,new_market_observation=False,semantic_fields=list(fixtures.COMPARABLE)))
    await crashes(out);await kill_worker(out/'worker_sigkill');await overlap(out/'shared_reservations')
    synthetic=await equivalence(out/'synthetic',buffered=True,raw_step=3,audit_step=1)
    public=[]
    for epoch in ('epoch-00','epoch-01'):
        public.append(await equivalence(out/epoch,source=PUBLIC/epoch,scope=scope,raw_step=200,audit_step=25))
    assert hashes(PUBLIC)==originals
    jobs=[j for row in [synthetic,*public] for k in ('raw','gzip') for j in row[k]['supervisor']['jobs']]
    summary=dict(status='PASS_BACKGROUND_INCREMENTAL_AUDIT_AND_PARENT_CHECKPOINT_COMPONENT',
        actual_parent_sigkill_cases=4,actual_worker_sigkill_cases=1,
        public_raw_records=sum(r['raw_records'] for r in public),public_audit_records=sum(r['audit_records'] for r in public),
        public_epochs=2,synthetic_raw_records=synthetic['raw_records'],all_semantic_comparisons_equal=True,
        equivalence_worker_jobs=len(jobs),max_parent_validation_and_commit_ns=max(j['parent_validation_and_commit_ns'] for j in jobs),
        max_worker_rss_bytes=max(j['peak_rss_bytes'] for j in jobs),original_public_files_preserved=True,
        new_network_requests=0,new_market_capture=False,live_collector_integration=False,
        original_deletion=False,disk_space_reclaimed_bytes=0,full_day_ready=False,actual_orders=0)
    save(out/'summary.json',summary);print(json.dumps(summary))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    parser.add_argument('--child',type=Path);parser.add_argument('--stage',choices=STAGES);args=parser.parse_args()
    asyncio.run(child(args.child,args.stage) if args.child else run(args.output.resolve()))


if __name__=='__main__':main()
