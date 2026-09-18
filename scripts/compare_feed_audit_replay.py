"""Fresh-process full replay comparisons of immutable captured journals."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.data.segmented_feed_audit import audit_epoch as original
from app.research.data.compact_feed_audit import audit_epoch as compact
from app.research.data.durable_capture_log import file_hash


def save(path,value):
    with path.open('x') as stream: stream.write(json.dumps(value,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--capture',type=Path,action='append',default=[])
    parser.add_argument('--worker',choices=('original','compact'))
    parser.add_argument('--raw',type=Path)
    parser.add_argument('--audit',type=Path)
    parser.add_argument('--plan',type=Path)
    args=parser.parse_args()
    if args.worker:
        plan=json.loads(args.plan.read_text())
        scope={k:plan[k] for k in ('window_start_ns','window_end_ns','clock_domain')}
        began,cpu=time.monotonic_ns(),time.process_time_ns()
        result=(original if args.worker=='original' else compact)(args.raw,args.audit,**scope)
        wall,cpu=time.monotonic_ns()-began,time.process_time_ns()-cpu
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        save(args.output,dict(audit=result,wall_ns=wall,cpu_ns=cpu,
            process_peak_rss_bytes=rss if sys.platform=='darwin' else rss*1024))
        return
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=False)
    pairs=[]
    for capture in args.capture:
        capture=capture.resolve()
        for epoch in sorted(capture.glob('epoch-*')):
            pairs.append(dict(raw=str(epoch/'journal'),audit=str(epoch/'audit'),plan=str(capture/'plan.json')))
    legacy=ROOT/'reports/validation/bounded_feed_v3_20260918'
    converted=ROOT/'reports/validation/segmented_feed_storage_20260918/drills/archive_replay/capture'
    for epoch in sorted(converted.glob('epoch-*')):
        pairs.append(dict(raw=str(legacy/epoch.name/'journal'),audit=str(epoch),plan=str(legacy/'plan.json')))
    sources=['scripts/compare_feed_audit_replay.py','app/research/data/compact_feed_audit.py',
             'app/research/data/compact_feed_intervals.py','app/research/data/segmented_feed_audit.py']
    inputs={}
    for pair in pairs:
        for key in ('raw','audit'):
            for name in ('metadata.json','checkpoint.json'):
                path=Path(pair[key])/name; inputs[str(path)]=file_hash(path)
        inputs[pair['plan']]=file_hash(Path(pair['plan']))
    save(output/'plan.json',dict(pairs=pairs,source_hashes={n:file_hash(ROOT/n) for n in sources},
        input_bindings=inputs,full_raw_replay=True,synthetic_expansion=False,network_requests=0))
    comparisons=[]
    for index,pair in enumerate(pairs):
        results={}
        for mode in ('original','compact'):
            path=output/f'{index:02d}-{mode}.json'
            with (output/f'{index:02d}-{mode}.log').open('x') as log:
                subprocess.run([sys.executable,__file__,'--output',str(path),'--worker',mode,
                    '--raw',pair['raw'],'--audit',pair['audit'],'--plan',pair['plan']],
                    stdout=log,stderr=subprocess.STDOUT,check=True,timeout=60)
            results[mode]=json.loads(path.read_text())
        compact_result=dict(results['compact']['audit']); stats=compact_result.pop('interval_reduction')
        assert compact_result==results['original']['audit']
        assert not compact_result['errors']
        comparisons.append(dict(pair=pair,equivalent=True,records=compact_result['committed_raw_records'],
            batches=compact_result['valid_batches'],interval_reduction=stats,
            performance={mode:{k:row[k] for k in ('wall_ns','cpu_ns','process_peak_rss_bytes')}
                         for mode,row in results.items()}))
    save(output/'comparisons.json',comparisons)
    print(json.dumps(dict(epochs=len(comparisons),records=sum(r['records'] for r in comparisons),
                          batches=sum(r['batches'] for r in comparisons),all_equal=True)))


if __name__=='__main__': main()
