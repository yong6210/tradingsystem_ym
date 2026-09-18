"""Offline incremental raw/gzip equivalence, retained captures and four SIGKILLs."""
import argparse
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.data.archive_segment_reader import cursor_dict,restore_cursor
from app.research.data.durable_capture_log import file_hash
from app.research.data.incremental_feed_audit import IncrementalFeedAudit
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from tests import incremental_audit_fixture as fixtures

STAGES=('after_incremental_replay','after_audit_checkpoint_fsync',
        'after_audit_checkpoint_replace','after_audit_checkpoint_directory_fsync')
SOURCES=['app/research/data/archive_segment_reader.py','app/research/data/feed_audit_state_codec.py',
         'app/research/data/incremental_feed_audit.py','tests/incremental_audit_fixture.py',
         'tests/test_incremental_feed_audit.py','scripts/drill_incremental_feed_audit.py']
PUBLIC=ROOT/'reports/validation/feed_scale_20260918/public_60s/capture'


def save(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2);f.write('\n')


def read(path):return json.loads(path.read_text())

def hashes(root):return {str(p.relative_to(root)):file_hash(p) for p in root.rglob('*') if p.is_file()}


def run_replay(fix,work,state_name):
    state=IncrementalFeedAudit.create(fix['root']/state_name,budget=fix['budget'],contract=fix['contract'])
    rows=[]
    try:
        for index,(a,r) in enumerate(work):
            started=time.monotonic_ns();state.advance(a,r)
            elapsed=time.monotonic_ns()-started
            receipt=state.receipt()
            rows.append(dict(index=index,revision=receipt['revision'],advance_ns=elapsed,
                             selected_sources=list(state.reader.reads),checkpoint_bytes=state.path.stat().st_size))
            state.close()
            state=IncrementalFeedAudit.resume(fix['root']/state_name,budget=fix['budget'],contract=fix['contract'],anchor=receipt)
        result=state.finalize(raw_cursor=fix['raw_cursor'],audit_cursor=fix['audit_cursor'])
        comparison={k:result[k]==fix['expected'][k] for k in fixtures.COMPARABLE}
        assert all(comparison.values()),comparison
        return dict(result=result,comparison=comparison,jobs=rows,restarts=len(rows))
    finally:state.close()


def equivalence(case,**kwargs):
    case.mkdir()
    fix=fixtures.fixture(case,**kwargs)
    try:
        raw=run_replay(fix,fixtures.jobs(fix), 'raw-state')
        gzip=run_replay(fix,fixtures.jobs(fix,compressed=True),'gzip-state')
        assert raw['result']['audit_payload_chain_sha256']==gzip['result']['audit_payload_chain_sha256']
        report=dict(status='PASS',raw=raw,gzip=gzip,baseline=fix['expected'],
            semantic_fields=list(fixtures.COMPARABLE),raw_gzip_chain_equal=True,
            raw_records=fix['raw_cursor'].sequence,audit_records=fix['audit_cursor'].sequence,
            storage=fix['budget'].snapshot(),files=hashes(fix['root']))
        save(case/'result.json',report)
        return report
    finally:fix['budget'].close()


def child(case,stage):
    plan=read(case/'case_plan.json');root=case/'capture'
    budget=ReservedStorageBudget.resume(root,**plan['budget_contract'])
    state=IncrementalFeedAudit.resume(root/'state',budget=budget,contract=plan['contract'],anchor=plan['anchor'])
    def pause(current):
        if current==stage:
            print(json.dumps(dict(stage=stage,pid=os.getpid())),flush=True)
            while True:signal.pause()
    state.hook=pause
    state.advance(*plan['jobs'][5])
    raise RuntimeError('crash hook not reached')


def crashes(out):
    results=[]
    for stage in STAGES:
        case=out/stage;case.mkdir();fix=fixtures.fixture(case,buffered=True,raw_step=3,audit_step=1)
        jobs=fixtures.jobs(fix,compressed=True)
        state=IncrementalFeedAudit.create(fix['root']/'state',budget=fix['budget'],contract=fix['contract'])
        for pair in jobs[:5]:state.advance(*pair)
        plan=dict(budget_contract={k:v for k,v in fix['budget'].contract.items() if k!='version'},
            contract=fix['contract'],anchor=state.receipt(),jobs=jobs,
            raw_cursor=cursor_dict(fix['raw_cursor']),audit_cursor=cursor_dict(fix['audit_cursor']),baseline=fix['expected'])
        save(case/'case_plan.json',plan);state.close();fix['budget'].close()
        proc=subprocess.Popen([sys.executable,__file__,'--child',str(case),'--stage',stage],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
        try:
            if not select.select([proc.stdout],[],[],15)[0]:raise RuntimeError('crash stage timeout')
            line=proc.stdout.readline(16385)
            if not line.endswith(b'\n') or len(line)>16384:raise RuntimeError('crash IPC bound')
            reached=json.loads(line);assert reached['stage']==stage
            proc.kill();_,stderr=proc.communicate(timeout=5)
            assert proc.returncode==-signal.SIGKILL and not stderr,stderr
        finally:
            if proc.poll() is None:proc.kill()
            proc.communicate(timeout=5)
        before=hashes(fix['root']);checkpoint_before=(fix['root']/'state/checkpoint.json').read_bytes()
        (case/'checkpoint_at_recovery.json').write_bytes(checkpoint_before)
        budget=ReservedStorageBudget.resume(fix['root'],**plan['budget_contract'])
        state=None
        try:
            state=IncrementalFeedAudit.resume(fix['root']/'state',budget=budget,contract=plan['contract'],anchor=plan['anchor'])
            revision=state.receipt()['revision'];expected=5 if stage in STAGES[:2] else 6
            assert revision==expected
            assert all(file_hash(fix['root']/p)==h for p,h in before.items())
            for a,r in jobs[revision:]:state.advance(a,r)
            result=state.finalize(raw_cursor=fix['raw_cursor'],audit_cursor=fix['audit_cursor'])
            comparison={k:result[k]==fix['expected'][k] for k in fixtures.COMPARABLE}
            assert all(comparison.values()),comparison
            assert all(file_hash(fix['root']/p)==h for p,h in before.items() if p!='state/checkpoint.json')
            report=dict(stage=stage,status='PASS',actual_sigkill=True,returncode=proc.returncode,
                recovered_revision=revision,all_precrash_files_unchanged_at_recovery=True,
                continued_checkpoint_intentionally_advanced=True,other_files_unchanged_after_completion=True,
                before=before,after=hashes(fix['root']),result=result,comparison=comparison,storage=budget.snapshot())
            save(case/'result.json',report);results.append(report)
        finally:
            if state is not None:state.close()
            budget.close()
    return results


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    parser.add_argument('--child',type=Path);parser.add_argument('--stage',choices=STAGES)
    args=parser.parse_args()
    if args.child:return child(args.child,args.stage)
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    public_plan=read(PUBLIC/'plan.json')
    scope={k:public_plan[k] for k in ('window_start_ns','window_end_ns','clock_domain')}
    originals=hashes(PUBLIC)
    save(out/'plan.json',dict(source_hashes={p:file_hash(ROOT/p) for p in SOURCES},stages=STAGES,
        public_source=str(PUBLIC.relative_to(ROOT)),public_source_hashes=originals,public_scope=scope,
        synthetic=dict(seconds=1,buffered=True,raw_step=3,audit_step=1),
        public_raw_step=200,public_audit_step=25,new_network_requests=0,new_market_observation=False,
        semantic_fields=list(fixtures.COMPARABLE)))
    crashes(out)
    synthetic=equivalence(out/'synthetic',buffered=True,raw_step=3,audit_step=1)
    public=[]
    for epoch in ('epoch-00','epoch-01'):
        public.append(equivalence(out/epoch,source=PUBLIC/epoch,scope=scope,raw_step=200,audit_step=25))
    assert hashes(PUBLIC)==originals
    summary=dict(status='PASS_INCREMENTAL_RAW_GZIP_REPLAY_AND_PROCESS_CRASH_RECOVERY',
        actual_sigkill_cases=4,synthetic_raw_records=synthetic['raw_records'],
        public_raw_records=sum(r['raw_records'] for r in public),public_audit_records=sum(r['audit_records'] for r in public),
        public_epochs=2,all_semantic_comparisons_equal=True,
        total_restart_boundaries=sum(len(r[k]['jobs']) for r in [synthetic,*public] for k in ('raw','gzip')),
        original_public_files_preserved=True,new_network_requests=0,new_market_capture=False,
        live_collector_integration=False,live_market_state_restored=False,original_deletion=False,
        disk_space_reclaimed_bytes=0,full_day_ready=False,actual_orders=0)
    save(out/'summary.json',summary);print(json.dumps(summary))


if __name__=='__main__':main()
