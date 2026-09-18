"""Fixed-stage synthetic file generation and full verified replay. No network.

Large, newly generated fixtures are deleted only after successful replay and a
complete SHA256 manifest. Failed fixtures and the 10-minute fixture are retained.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.data.synthetic_feed_fixture import build_fixture
from app.research.data.compact_feed_audit import audit_epoch as compact
from app.research.data.snapshot_feed_audit import audit_epoch as snapshot
from app.research.data.durable_capture_log import file_hash

STAGES = [(600,('compact','snapshot')),(3600,('compact','snapshot')),(86400,('snapshot',))]
MAX_BYTES=6*1024**3
MIN_FREE=16*1024**3
RSS_LIMIT=384*1024**2
SOURCES=[
    'scripts/measure_full_feed_replay.py','app/research/data/synthetic_feed_fixture.py',
    'app/research/data/verified_journal_view.py','app/research/data/snapshot_feed_audit.py',
    'app/research/data/compact_feed_audit.py','app/research/data/compact_feed_intervals.py',
    'app/research/data/durable_capture_log.py','app/research/data/durable_market_feed.py',
    'app/research/data/local_order_book.py',
]


def save(path,value):
    with path.open('x') as stream: stream.write(json.dumps(value,indent=2)+'\n')


def rss():
    value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform=='darwin' else value*1024


def watchdog():
    began=time.monotonic()
    while True:
        time.sleep(1)
        peak=rss()
        if peak>RSS_LIMIT:
            print(json.dumps(dict(phase='RSS_LIMIT',rss_bytes=peak)),flush=True)
            os._exit(17)
        if int(time.monotonic()-began)%15==0:
            print(json.dumps(dict(phase='HEARTBEAT',elapsed_seconds=time.monotonic()-began,rss_bytes=peak)),flush=True)


def worker(args):
    threading.Thread(target=watchdog,daemon=True).start()
    began,cpu=time.monotonic_ns(),time.process_time_ns()
    if args.worker=='generate':
        result=build_fixture(args.fixture,args.seconds,max_bytes=MAX_BYTES,min_free_bytes=MIN_FREE,
                             progress=lambda v:print(json.dumps(v),flush=True))
    else:
        plan=json.loads(args.plan.read_text())
        scope={k:plan[k] for k in ('window_start_ns','window_end_ns','clock_domain')}
        result=(compact if args.worker=='compact' else snapshot)(args.raw,args.audit,**scope)
        assert not result['errors'] and not result['processor_errors'],result['errors']
        if plan.get('synthetic'):
            assert result['intervals']==plan['expected_intervals']
            assert result['committed_raw_records']==plan['raw_records']
            assert result['valid_batches']==plan['audit_batches']
            assert result['clean_stop_audited']
    wall,cpu=time.monotonic_ns()-began,time.process_time_ns()-cpu
    save(args.output,dict(mode=args.worker,wall_ns=wall,cpu_ns=cpu,process_peak_rss_bytes=rss(),result=result,
        network_requests=0,full_day_live_capture=False,cache_cleared=False))


def run_worker(stage,name,*args):
    with (stage/(name+'.log')).open('x') as log:
        subprocess.run([sys.executable,__file__,'--output',str(stage/(name+'.json')),*args],
            stdout=log,stderr=subprocess.STDOUT,timeout=600,check=True)
    return json.loads((stage/(name+'.json')).read_text())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--worker',choices=('generate','compact','snapshot'))
    parser.add_argument('--fixture',type=Path)
    parser.add_argument('--seconds',type=int)
    parser.add_argument('--raw',type=Path)
    parser.add_argument('--audit',type=Path)
    parser.add_argument('--plan',type=Path)
    args=parser.parse_args()
    if args.worker:
        worker(args)
        return
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=False)
    prior_plan=ROOT/'reports/validation/feed_scale_20260918/replay/plan.json'
    pairs=json.loads(prior_plan.read_text())['pairs']
    free_before=shutil.disk_usage(output).free
    plan=dict(stages=STAGES,max_fixture_bytes=MAX_BYTES,min_free_bytes=MIN_FREE,
        diagnostic_worker_rss_limit=RSS_LIMIT,worker_timeout_seconds=600,network_requests=0,
        source_hashes={name:file_hash(ROOT/name) for name in SOURCES},
        existing_input_plan=str(prior_plan),existing_input_plan_sha256=file_hash(prior_plan),
        retention='KEEP_600S_AND_FAILURES_DELETE_ONLY_OWN_SUCCESSFUL_3600S_86400S_AFTER_MANIFEST',
        profile='20Hz ticker,10Hz depth,1Hz mark,1Hz aggTrade,4Hz watchdog,20Hz observations;4 book levels',
        generator_commit_clock='SYNTHETIC_NOT_PHYSICAL_FSYNC_RECEIPT',
        generator_writes='BUFFERED_BULK_NOT_LIVE_COLLECTOR_WRITE_LATENCY',free_before=free_before,
        full_day_admission=False)
    save(output/'plan.json',plan)
    if free_before<MIN_FREE+MAX_BYTES+1024**3:
        save(output/'blocked.json',dict(reason='INSUFFICIENT_FIXTURE_HEADROOM',free_bytes=free_before))
        raise RuntimeError('fixture preflight headroom insufficient')
    existing=output/'existing'; existing.mkdir()
    comparison=[]
    for index,pair in enumerate(pairs):
        results={}
        for mode in ('compact','snapshot'):
            results[mode]=run_worker(existing,f'{index:02d}-{mode}','--worker',mode,
                '--raw',pair['raw'],'--audit',pair['audit'],'--plan',pair['plan'])
        assert results['compact']['result']==results['snapshot']['result']
        comparison.append(dict(pair=pair,equal=True,records=results['snapshot']['result']['committed_raw_records'],
                               batches=results['snapshot']['result']['valid_batches']))
    save(output/'existing_comparison.json',comparison)
    summaries=[]
    for seconds,modes in STAGES:
        stage=output/f'synthetic-{seconds}s'; stage.mkdir()
        fixture=stage/'fixture'
        generated=run_worker(stage,'generate','--worker','generate','--seconds',str(seconds),'--fixture',str(fixture))
        replays={}
        for mode in modes:
            replays[mode]=run_worker(stage,mode,'--worker',mode,'--raw',str(fixture/'journal'),
                '--audit',str(fixture/'audit'),'--plan',str(fixture/'plan.json'))
        if len(replays)==2:
            assert replays['compact']['result']==replays['snapshot']['result']
        files={str(p.relative_to(fixture)):dict(bytes=p.stat().st_size,sha256=file_hash(p))
               for p in sorted(fixture.rglob('*')) if p.is_file()}
        save(stage/'fixture_manifest.json',dict(files=files,deterministic_fixture=True,
             plan=generated['result'],exists_after_success=seconds==600))
        before_cleanup=shutil.disk_usage(output).free
        if seconds!=600:
            # This exact directory was created new by this stage's worker.
            assert fixture.parent==stage and fixture.name=='fixture' and not fixture.is_symlink()
            assert all(not p.is_symlink() for p in fixture.rglob('*'))
            shutil.rmtree(fixture)
        summary=dict(seconds=seconds,generated=generated,replay_measurements={mode:{k:v[k] for k in
                ('wall_ns','cpu_ns','process_peak_rss_bytes')} for mode,v in replays.items()},
            all_expected_intervals_verified=True,full_record_hash_validation=True,
            synthetic_fixture_retained=seconds==600,free_before_cleanup=before_cleanup,
            free_after_cleanup=shutil.disk_usage(output).free)
        save(stage/'summary.json',summary)
        summaries.append(summary)
        print(json.dumps(dict(seconds=seconds,bytes=generated['result']['total_bytes'],
            generation_seconds=generated['wall_ns']/1e9,
            replay_seconds={m:r['wall_ns']/1e9 for m,r in replays.items()},
            snapshot_rss_mib=replays['snapshot']['process_peak_rss_bytes']/1024**2)),flush=True)
    save(output/'summary.json',dict(status='PASS_SYNTHETIC_FULL_FILE_REPLAY',stages=summaries,
        existing_epochs=len(comparison),existing_records=sum(r['records'] for r in comparison),
        existing_batches=sum(r['batches'] for r in comparison),network_requests=0,
        full_day_market_capture=False,full_day_live_durability_qualified=False,full_day_admission=False))


if __name__=='__main__': main()
