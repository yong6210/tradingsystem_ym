"""Readiness evidence after full-file replay, with remaining live blockers."""
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
    summary=json.loads((root/'measurements/summary.json').read_text())
    assert summary['status']=='PASS_SYNTHETIC_FULL_FILE_REPLAY'
    stages={row['seconds']:row for row in summary['stages']}
    policy=json.loads(Path('configs/research/forward_data_policy_v1.json').read_text())
    prior=Path('reports/validation/feed_scale_20260918/capacity.json')
    capacity=json.loads(prior.read_text())
    two_x=next(row['day_bytes'] for row in capacity['scenarios']
               if row['run']=='public_60s' and row['rate_multiplier']==2)
    free=shutil.disk_usage(root).free
    available=max(0,free-policy['storage']['min_free_bytes'])
    synchronous_audit=stages[3600]['replay_measurements']['compact']['wall_ns']
    max_gap=policy['quality']['max_unavailable_seconds']*1_000_000_000
    result=dict(status='BLOCKED_FOR_24H_LIVE_ADMISSION',measured_utc=datetime.fromtimestamp(time.time(),timezone.utc).isoformat(),
        network_requests=0,actual_orders=0,full_day_market_capture=False,strategy_adoption=False,
        evidence_completed=['SYNTHETIC_DAY_FULL_FILE_REPLAY','PRIOR_PUBLIC_EPOCH_EQUIVALENCE',
                            'BOUNDED_SNAPSHOT_READER_VALIDATION'],
        live_collector_limit_seconds=120,live_pilot_contract_seconds=policy['duration_seconds'],
        registered=policy['binding']['status']!='UNREGISTERED',
        next_work_order=[
            dict(priority=1,id='REMOVE_SYNCHRONOUS_AUDIT_FROM_RECONNECT_PATH',
                 source='app/research/data/compact_feed_collector.py:64',
                 current_path='collect_epoch -> synchronous audit_epoch -> retry.after_failure -> sleep -> next epoch',
                 one_hour_synthetic_current_audit_ns=synchronous_audit,policy_max_unavailable_ns=max_gap,
                 synthetic_audit_alone_exceeds_gap=synchronous_audit>max_gap,
                 actual_hour_market_reconnect_measured=False,
                 required='Bounded offline auditing must not block reconnect; failures must still reject the whole run.'),
            dict(priority=2,id='STORAGE_HEADROOM_AND_RATE_ENVELOPE',
                 capacity_source=str(prior),free_bytes=free,reserve_bytes=policy['storage']['min_free_bytes'],
                 available_above_reserve_bytes=available,diagnostic_2x_day_bytes=two_x,
                 diagnostic_shortfall_bytes=max(0,two_x-available),diagnostic_2x_is_certified_peak=False,
                 full_day_live_write_rate_envelope_measured=False),
            dict(priority=3,id='LIVE_WRITE_AND_LARGER_BOOK_QUALIFICATION',
                 generated_profile='36 raw records/s,20 observations/s,4 book levels',
                 bulk_fixture_fsync_is_live_fsync_test=False,
                 full_day_live_fsync_latency_measured=False,
                 cold_filesystem_cache_controlled=False,
                 actual_burst_and_large_book_profile_qualified=False)],
        prior_inspection_history='reports/validation/feed_scale_20260918/inspection_history.json',
        inspection_history_advanced=False)
    with (root/'readiness.json').open('x') as stream:
        stream.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],available_gib=available/1024**3,
        diagnostic_2x_gib=two_x/1024**3,shortfall_gib=max(0,two_x-available)/1024**3,
        current_one_hour_audit_seconds=synchronous_audit/1e9)))


if __name__=='__main__': main()
