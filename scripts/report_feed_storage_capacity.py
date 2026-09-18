"""Retained-byte constant-rate scenarios; never a capacity certification."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    root=args.report.resolve()
    samples=[]
    inspections=[]
    for name in ('public_12s','public_60s','public_compact_12s'):
        run=root/name
        wrapper=json.loads((run/'harness_result.json').read_text())
        result=wrapper['result']
        capture=run/'capture'
        files=[p for p in capture.rglob('*') if p.is_file()]
        retained=sum(p.stat().st_size for p in files)
        assert retained==result['storage_after_result']['used_bytes']
        scope=result['original_window']
        duration=scope['window_end_ns']-scope['window_start_ns']
        audit_bytes=sum(p.stat().st_size for p in capture.glob('epoch-*/audit/segment-*.jsonl'))
        samples.append(dict(run=name,calendar_ns=duration,retained_bytes=retained,
            raw_segment_bytes=result['total_raw_bytes'],audit_segment_bytes=audit_bytes,
            other_retained_bytes=retained-result['total_raw_bytes']-audit_bytes,
            observed_peak_logical_bytes=result['storage_after_result']['peak_bytes'],
            scope='ALL_RETAINED_CAPTURE_FILES_AT_END_NOT_CUMULATIVE_WRITE_IO',
            includes_startup_disconnect_and_stop=True,
            joint_coverage_ppm=result['combined']['quality']['joint_coverage_ppm'],
            raw_records=sum(e['committed_raw_records'] for e in result['audits']),
            audited_batches=sum(e['valid_batches'] for e in result['audits']),
            connection_attempts=wrapper['connection_attempts'],snapshot_attempts=wrapper['snapshot_attempts']))
        inspections.append(json.loads((run/'inspection_record.json').read_text()))
    measured=time.time_ns()
    free=shutil.disk_usage(root).free
    reserve=16*1024**3
    available=max(0,free-reserve)
    day=86400*1_000_000_000
    scenarios=[]
    for sample in samples:
        for multiple in (1,2,5):
            hypothetical=(sample['retained_bytes']*day*multiple+sample['calendar_ns']-1)//sample['calendar_ns']
            scenarios.append(dict(run=sample['run'],rate_multiplier=multiple,day_bytes=hypothetical,
                exceeds_current_free_above_reserve=hypothetical>available,
                exceeds_aggregate_64_gib=hypothetical>64*1024**3,
                additional_free_bytes_needed_at_this_hypothetical_rate=max(0,hypothetical-available)))
    report=dict(status='DIAGNOSTIC_ONLY_NOT_24H_ADMISSION',samples=samples,scenarios=scenarios,
        measured_utc=datetime.fromtimestamp(measured/1e9,timezone.utc).isoformat(),
        free_bytes=free,min_free_bytes=reserve,available_above_reserve_bytes=available,
        method='LINEAR_SCALE_ALL_RETAINED_FILES_OVER_ORIGINAL_CALENDAR_WINDOW',
        includes_retained_metadata=True,includes_checkpoint_rewrite_io=False,
        includes_full_day_manifest_growth=False,includes_physical_allocation_overhead=False,
        burst_envelope_established=False,long_horizon_confidence_interval_available=False,full_day_ready=False)
    with (root/'capacity.json').open('x') as stream: stream.write(json.dumps(report,indent=2)+'\n')
    prior='reports/validation/bounded_feed_v3_20260918/inspection_history.json'
    upper=max(r['conservative_inspection_end_utc_ns'] for r in inspections)
    history=dict(prior_inspection_history=prior,prior_history_must_be_retained=True,
        latest_inspected_utc_upper_bound_ns=upper,
        latest_inspected_utc_upper_bound=datetime.fromtimestamp(upper/1e9,timezone.utc).isoformat(),
        basis='HARNESS_POST_COMPLETION_BOUND_INCLUDES_UNPERSISTED_RECEIVES',
        runs=[str(root/r['run']) for r in samples],
        total_public_connection_attempts=sum(r['connection_attempts'] for r in samples),
        total_snapshot_attempts=sum(r['snapshot_attempts'] for r in samples),
        new_strategy_evaluation=False,full_day_pilot=False,actual_orders=0)
    with (root/'inspection_history.json').open('x') as stream: stream.write(json.dumps(history,indent=2)+'\n')
    print(json.dumps(dict(samples=samples,free_above_reserve_gib=available/1024**3,
        scenarios=[dict(run=s['run'],multiplier=s['rate_multiplier'],gib=s['day_bytes']/1024**3,
            shortfall_gib=s['additional_free_bytes_needed_at_this_hypothetical_rate']/1024**3) for s in scenarios])))


if __name__=='__main__': main()
