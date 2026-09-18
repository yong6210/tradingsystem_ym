"""Compare short observed rolling peaks, retained averages and current storage.

No fitting, confidence claims, new market requests, deletions or pilot admission.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.durable_capture_log import file_hash
from app.research.data.feed_storage_envelope import capture_sample, project_storage
from scripts.drill_queued_feed_load import save

PUBLIC_RUNS = [
    'reports/validation/feed_scale_20260918/public_12s',
    'reports/validation/feed_scale_20260918/public_60s',
    'reports/validation/feed_scale_20260918/public_compact_12s',
    'reports/validation/background_feed_audit_20260918/public_12s',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--load-drill', type=Path, required=True)
    args = parser.parse_args()
    samples = []
    bindings = {}
    for name in PUBLIC_RUNS:
        path = ROOT/name/'harness_result.json'
        result = json.loads(path.read_text())['result']
        sample = capture_sample(ROOT/name/'capture', result)
        sample['source_kind'] = 'PREVIOUSLY_INSPECTED_PUBLIC_CAPTURE'
        sample['run'] = name
        samples.append(sample)
        bindings[str(path.relative_to(ROOT))] = file_hash(path)
    synthetic = []
    for path in sorted(args.load_drill.glob('*/result.json')):
        row = json.loads(path.read_text())
        if row['storage_sample'] is not None:
            synthetic.append(dict(case=row['case'], source_kind='SYNTHETIC_CONTROLLED_INPUT',
                                  sample=row['storage_sample']))
        bindings[str(path.resolve().relative_to(ROOT))] = file_hash(path)
    free = shutil.disk_usage(args.output.parent.resolve()).free
    reference = max(samples, key=lambda s:s['peak_rolling_1s_record_bytes'])
    rates = dict(max_observed_rolling_1s_record_bytes=reference['peak_rolling_1s_record_bytes'],
        max_short_calendar_retained_average_bytes_per_second=max(
            (s['logical_bytes']*1_000_000_000+s['calendar_ns']-1)//s['calendar_ns'] for s in samples))
    scenarios = []
    for basis, rate in rates.items():
        for multiplier in (1, 2, 5):
            for seconds in (120, 3600, 86400):
                scenarios.append(dict(basis=basis, multiplier=multiplier, **project_storage(
                    bytes_per_second=rate*multiplier, seconds=seconds, free_bytes=free,
                    logical_cap_bytes=64*1024**3)))
    report = dict(status='OBSERVED_STORAGE_SCENARIOS_LONG_RUN_BLOCKED', measured_utc_ns=time.time_ns(),
        public_samples=samples, synthetic_samples=synthetic, free_bytes=free,
        reserve_bytes=16*1024**3, available_above_reserve_bytes=max(0,free-16*1024**3),
        rate_bases=rates, reference_peak_run=reference['run'], scenarios=scenarios,
        input_hashes=bindings, source_hashes={p:file_hash(ROOT/p) for p in (
            'scripts/report_storage_envelope.py', 'app/research/data/feed_storage_envelope.py')},
        transient_allowance_bytes=64*1024**2,
        transient_allowance_basis='EXPLICIT_ENGINEERING_SCENARIO_NOT_MEASURED_UPPER_BOUND',
        caveats=['SHORT_SAMPLES_NOT_MARKET_MAXIMUM', 'AVERAGE_INCLUDES_DISCONNECT_AND_SHUTDOWN',
                 'ROLLING_PEAK_USES_RECEIPT_AND_OBSERVATION_NOT_DISK_IO_CLOCK',
                 'FULL_DAY_METADATA_GROWTH_AND_FILESYSTEM_ALLOCATION_NOT_BOUNDED',
                 'NO_CHECKPOINT_REWRITE_IO_FORECAST', 'SPACE_FIT_DOES_NOT_CERTIFY_THROUGHPUT'],
        input_rate_upper_bound_established=False, recommended_long_run_seconds=None,
        collector_qualification_limit_seconds=120, full_day_ready=False,
        new_network_requests=0, inspection_history_advanced=False,
        prior_inspection_history='reports/validation/background_feed_audit_20260918/inspection_history.json')
    save(args.output, report)
    print(json.dumps(dict(rates=rates, free_above_reserve_gib=report['available_above_reserve_bytes']/1024**3,
        day_scenarios=[row for row in scenarios if row['seconds']==86400], full_day_ready=False)))


if __name__ == '__main__': main()
