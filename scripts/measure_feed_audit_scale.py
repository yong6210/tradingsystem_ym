"""Predeclared, offline interval-reducer scale measurements in fresh processes.

Synthetic verified-point inputs only: not a day of raw replay or network data.
The baseline follows the frozen segmented auditor's lease/list reduction.
"""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.data.compact_feed_intervals import CompactIntervals, IntervalLimitError
from app.research.data.feed_coverage_audit import subtract
from app.research.foundation.forward_data_contract import REQUIREMENTS, merge_intervals
from app.research.data.durable_capture_log import file_hash

PERIOD=50_000_000
DAY=86_400*1_000_000_000
RSS_LIMIT=256*1024**2
CASES=[('baseline_small','baseline',100_001,'healthy'),
       ('baseline_day','baseline',1_728_001,'healthy'),
       ('compact_small','compact',100_001,'healthy'),
       ('compact_day','compact',1_728_001,'healthy'),
       ('compact_fragmented','compact',1_728_001,'fragmented')]


def save(path,value):
    with path.open('x') as stream: stream.write(json.dumps(value,indent=2)+'\n')


def rss_bytes():
    value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform=='darwin' else value*1024


class DiagnosticRSSLimit(RuntimeError): pass


def worker(output,mode,count,shape):
    start=time.monotonic_ns()
    processed=0
    reducer=None
    outcome='COMPLETE'
    intervals=None
    try:
        if mode=='compact':
            reducer=CompactIntervals(0,DAY)
        else:
            leases=[]
        for index in range(count):
            publication=index*PERIOD
            expiry=dict.fromkeys(REQUIREMENTS,publication+PERIOD)
            if shape=='fragmented' and index%2: expiry={}
            if reducer is not None:
                reducer.add(publication,expiry)
            else:
                leases.append((publication,expiry))
            processed+=1
            if processed%1024==0 and rss_bytes()>RSS_LIMIT:
                raise DiagnosticRSSLimit('256 MiB diagnostic process peak RSS limit')
        if reducer is not None:
            intervals,_=reducer.finish()
        else:
            intervals={name:[] for name in REQUIREMENTS}
            # Same chronological lease-to-interval loop as frozen auditor.
            # zip(leases, leases[1:]) also allocates a reference list; retained.
            for index,((left,expiry),(right,_)) in enumerate(zip(leases,leases[1:])):
                for name,until in expiry.items():
                    lo,hi=max(0,left),min(DAY,right,until)
                    if lo<hi: intervals[name].append([lo,hi])
                if index%1024==0 and rss_bytes()>RSS_LIMIT:
                    raise DiagnosticRSSLimit('256 MiB diagnostic process peak RSS limit')
            intervals={name:subtract(merge_intervals(rows,0,DAY),[]) for name,rows in intervals.items()}
        if shape=='healthy':
            assert all(rows==[[0,(count-1)*PERIOD]] for rows in intervals.values())
    except (DiagnosticRSSLimit,IntervalLimitError) as exc:
        outcome=type(exc).__name__
    elapsed=time.monotonic_ns()-start
    save(output,dict(mode=mode,shape=shape,requested_points=count,processed_points=processed,
        represented_calendar_ns=(count-1)*PERIOD,outcome=outcome,elapsed_ns=elapsed,
        process_peak_rss_bytes=rss_bytes(),diagnostic_rss_limit_bytes=RSS_LIMIT,
        compact_interval_limit=100_000,peak_merged_intervals=None if reducer is None else reducer.peak,
        result_intervals=intervals if outcome=='COMPLETE' else None,
        scope='INTERVAL_REDUCTION_ONLY_NOT_FULL_RAW_REPLAY',network_requests=0,full_day_ready=False))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--worker',choices=('baseline','compact'))
    parser.add_argument('--count',type=int)
    parser.add_argument('--shape',choices=('healthy','fragmented'))
    args=parser.parse_args()
    if args.worker:
        worker(args.output,args.worker,args.count,args.shape)
        return
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=False)
    sources=['scripts/measure_feed_audit_scale.py','app/research/data/compact_feed_intervals.py',
             'app/research/data/compact_feed_audit.py','app/research/data/segmented_feed_audit.py']
    save(output/'plan.json',dict(cases=CASES,period_ns=PERIOD,rss_limit_bytes=RSS_LIMIT,
        compact_max_intervals=100_000,worker_timeout_seconds=60,
        source_hashes={name:file_hash(ROOT/name) for name in sources},
        scope='INTERVAL_REDUCTION_ONLY_NOT_END_TO_END_REPLAY',network_requests=0))
    results=[]
    for name,mode,count,shape in CASES:
        with (output/(name+'.log')).open('x') as stream:
            subprocess.run([sys.executable,__file__,'--output',str(output/(name+'.json')),
                '--worker',mode,'--count',str(count),'--shape',shape],stdout=stream,stderr=subprocess.STDOUT,
                check=True,timeout=60)
        results.append(json.loads((output/(name+'.json')).read_text()))
    save(output/'results.json',results)
    print(json.dumps([{k:r[k] for k in ('mode','shape','requested_points','processed_points','outcome',
                                      'elapsed_ns','process_peak_rss_bytes','peak_merged_intervals')} for r in results]))


if __name__=='__main__': main()
