"""Reuse inspected samples; separate closed-retirement peak from future steady space."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.research.data.durable_capture_log import file_hash
from app.research.data.retention_capacity import retention_capacity


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();output=args.output.resolve()
    old=ROOT/'reports/validation/storage_envelope_20260918/capacity.json'
    prior=json.loads(old.read_text());free=shutil.disk_usage(output.parent).free
    # These are named sensitivity assumptions, not fitted throughput or safe
    # upper limits. Existing retained-average basis is a conservative proxy for
    # raw input and is explicitly not a pure raw-wire measurement.
    samples=[];bindings={str(old.relative_to(ROOT)):file_hash(old)}
    base=ROOT/'reports/validation/restartable_feed_capture_20260918/drills'
    for path in sorted(base.glob('*/run')):
        raw=list(path.glob('capture-*/epoch-*/*/segment-*.jsonl'))
        gzip=list(path.glob('capture-*/epoch-*/*-archives/*.gz'))
        total=sum(p.stat().st_size for p in path.rglob('*') if p.is_file())
        units=sum(json.loads(p.read_text())['kind']=='UNIT' for p in path.glob('capture-*/work-ledger/event-*.json'))
        if units:
            residual=total-sum(p.stat().st_size for p in raw+gzip)
            samples.append(dict(run=str(path.relative_to(ROOT)),units=units,total_bytes=total,
                raw_segment_bytes=sum(p.stat().st_size for p in raw),gzip_bytes=sum(p.stat().st_size for p in gzip),
                nonsegment_bytes=residual,nonsegment_bytes_per_unit=(residual+units-1)//units,
                inference='SHORT_SYNTHETIC_RUN_OVERHEAD_PROXY_NOT_LONG_RUN_BOUND'))
            for p in path.rglob('*'):
                if p.is_file():bindings[str(p.relative_to(ROOT))]=file_hash(p)
    metadata=max(s['nonsegment_bytes_per_unit'] for s in samples)
    scenarios=[]
    for basis,rate in prior['rate_bases'].items():
        for factor in (1,2):
            for ratio in (200000,1000000):
                for seconds in (120,3600,86400):
                    scenarios.append(dict(basis=basis,rate_multiplier=factor,
                        **retention_capacity(seconds=seconds,raw_bytes_per_second=rate*factor,
                          gzip_ratio_ppm=ratio,metadata_bytes_per_unit=metadata,seal_seconds=2,
                          free_bytes=free,logical_cap_bytes=64*1024**3)))
    result=dict(status='LONG_RUN_BLOCKED_DESPITE_POSSIBLE_COMPRESSED_SPACE_FIT',measured_utc_ns=time.time_ns(),
        free_bytes=free,reserve_bytes=16*1024**3,observed_rate_bases=prior['rate_bases'],
        rate_basis_caveat='Retained-average includes metadata; rolling-peak is record bytes. Neither is an enforced raw market-rate cap.',
        metadata_proxy_bytes_per_unit=metadata,metadata_samples=samples,scenarios=scenarios,
        input_hashes=bindings,new_market_requests=0,full_day_ready=False,
        compression_assumptions_fitted_to_profit=False,active_retirement_implemented=False,
        source_hashes={p:file_hash(ROOT/p) for p in ('scripts/report_retention_capacity.py','app/research/data/retention_capacity.py')})
    with output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(dict(scenarios=len(scenarios),metadata_proxy=metadata,free_bytes=free,full_day_ready=False)))


if __name__=='__main__':main()
