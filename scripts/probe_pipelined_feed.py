"""Bounded public-only V6 qualification with independent post-capture checks.

No API keys, private endpoints or orders. Observation history includes failed
attempts; a successful transport run alone never counts as verified capture.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.durable_capture_log import encoded, file_hash, iter_committed
from app.research.data.pipelined_feed_collector import run_bounded, NS
from app.research.data.public_feed_transport import PublicFeedTransport
from app.research.data.snapshot_feed_audit import audit_epoch
from app.research.foundation.forward_data_contract import load_contract
from tests.incremental_audit_fixture import COMPARABLE
from scripts.drill_pipelined_feed_collector import SOURCES as PIPELINE_SOURCES

SOURCES = sorted(set(PIPELINE_SOURCES + ['scripts/probe_pipelined_feed.py',
    'scripts/drill_pipelined_feed_collector.py', 'tests/test_probe_pipelined_feed.py']))


def save(path, value):
    raw = json.dumps(value, indent=2, ensure_ascii=False)+'\n'
    if len(raw.encode()) > 4*1024**2:
        raise ValueError('harness artifact exceeds 4MiB')
    with path.open('x') as stream:
        stream.write(raw)


class CountedPublicTransport(PublicFeedTransport):
    def __init__(self):
        super().__init__()
        self.connection_attempts = self.snapshot_attempts = 0

    async def connect(self, *args, **kwargs):
        self.connection_attempts += 1
        return await super().connect(*args, **kwargs)

    async def snapshot(self, *args, **kwargs):
        self.snapshot_attempts += 1
        return await super().snapshot(*args, **kwargs)


def result_checks(result, *, duration_ns, reconnect):
    """Explicit nonempty/terminal checks, separate from live quality acceptance."""
    if not result:
        return dict(result_exists=False)
    epochs, audits = result['epochs'], result['audits']
    pipeline = result['pipeline']
    channels = pipeline['channels'] if pipeline else []
    all_managers = [c[k] for c in channels for k in ('raw','audit_log','auditor')]
    expected_epochs = 2 if reconnect else 1
    return dict(result_exists=True, planned_stop=result['stop_reason'] == 'ORIGINAL_DEADLINE',
        no_collector_errors=not result['errors'], result_persisted=result['result_persisted'],
        original_calendar=result['original_window']['window_end_ns']-result['original_window']['window_start_ns'] == duration_ns,
        expected_epochs=len(epochs) == expected_epochs,
        requested_reconnect=(result['retries_used'] == int(reconnect) and
            sum(bool(e['forced_local_disconnect']) for e in epochs) == int(reconnect)),
        epoch_audit_set=bool(epochs) and len(epochs) == len(audits) == len(channels),
        clean_final_audits=bool(audits) and all(a['status'] == 'AUDIT_PREFIX_COMPLETE' and a['clean_stop_audited'] and
            not a['errors'] and not a['processor_errors'] for a in audits),
        pipeline_final=bool(pipeline) and pipeline['closed'] and not pipeline['errors'] and
            bool(channels) and all(c['complete'] for c in channels),
        units_complete=bool(pipeline and pipeline['units']) and all(u['status'] == 'COMPLETE' for u in pipeline['units']),
        workers_complete=bool(all_managers) and all(m['closed'] and m['child_reaped'] and not m['pending'] and not m['errors'] and
            m['jobs'] and all(j['status'] == 'COMPLETE' and j.get('returncode') == 0 for j in m['jobs']) for m in all_managers),
        reservation_limit=bool(pipeline) and 0 < pipeline['peak_reservations'] <= 2,
        reservations_released=result['storage_after_result']['reserved_bytes'] == 0,
        no_orders=result['actual_orders'] == result['private_requests'] == 0,
        full_day_not_claimed=not result['full_day_pilot'] and not result['strategy_adoption'] and
            not result['continuous_runtime_coverage_certified'])


def verify_capture(capture, result):
    """Read-only full replay and all registered raw/gzip bytes after lock release."""
    comparisons, stops, registrations = [], [], []
    scope = result['original_window']
    stored = json.loads((capture/'collection_result.json').read_text())
    if encoded(stored['audits']) != encoded(result['audits']) or encoded(stored['epochs']) != encoded(result['epochs']):
        raise ValueError('persisted result differs from returned capture')
    for epoch, actual in zip(result['epochs'], result['audits'], strict=True):
        directory = capture/epoch['directory']
        baseline = audit_epoch(directory/'journal', directory/'audit', **scope, max_intervals=10000)
        comparisons.append(dict(directory=directory.name,
            fields={k:encoded(actual[k]) == encoded(baseline[k]) for k in COMPARABLE}))
        checkpoint = json.loads((directory/'replay-state/checkpoint.json').read_text())
        digest = hashlib.sha256(encoded({k:v for k,v in checkpoint.items() if k != 'checkpoint_sha256'})).hexdigest()
        if (digest != checkpoint['checkpoint_sha256'] or not checkpoint['state']['finalized'] or
                {k:checkpoint[k] for k in ('revision','checkpoint_sha256')} != actual['receipt']):
            raise ValueError('final replay checkpoint differs from audit receipt')
        for name, expected in checkpoint['contract']['implementations'].items():
            if file_hash(ROOT/'app/research/data'/name) != expected:
                raise ValueError('replay implementation changed')
        stop_ns = min((r['payload']['received_ns'] for r in iter_committed(directory/'journal')
                       if r['payload']['kind'] == 'STOP'), default=None)
        if stop_ns is None:
            raise ValueError('clean STOP missing')
        eligible_after_stop = eligible_after_deadline = 0
        for record in iter_committed(directory/'audit'):
            point = record['payload']['observation']
            eligible_after_stop += int(point['eligible'] and point['published_ns'] >= stop_ns)
            eligible_after_deadline += int(point['eligible'] and point['published_ns'] >= scope['window_end_ns'])
        intervals_after_stop = any(end > stop_ns for spans in actual['intervals'].values() for _,end in spans)
        stops.append(dict(directory=directory.name, stop_ns=stop_ns, eligible_after_stop=eligible_after_stop,
            eligible_after_deadline=eligible_after_deadline, intervals_after_stop=intervals_after_stop))
        for journal, archive in [('journal','raw-archives'), ('audit','audit-archives')]:
            source_cp = json.loads((directory/journal/'checkpoint.json').read_text())
            expected_names = {r['name'] for r in source_cp['segments']}
            seen = set()
            for descriptor_path in sorted((directory/archive).glob('*.json')):
                descriptor = json.loads(descriptor_path.read_text())
                identity = descriptor['identity']
                if (identity['journal'] != str((directory/journal).relative_to(capture)) or
                        identity['segment_name'] in seen):
                    raise ValueError('archive identity mismatch or duplicate source')
                checksum = hashlib.sha256(encoded({k:v for k,v in descriptor.items() if k != 'descriptor_sha256'})).hexdigest()
                if checksum != descriptor['descriptor_sha256']:
                    raise ValueError('archive descriptor checksum')
                seen.add(identity['segment_name'])
                source = directory/journal/identity['segment_name']
                compressed = directory/archive/descriptor['compressed_name']
                raw = gzip.decompress(compressed.read_bytes())
                if (not descriptor['originals_retained'] or raw != source.read_bytes() or
                        len(raw) != identity['raw_bytes'] or hashlib.sha256(raw).hexdigest() != identity['raw_sha256'] or
                        compressed.stat().st_size != descriptor['compressed_bytes'] or
                        file_hash(compressed) != descriptor['compressed_sha256']):
                    raise ValueError('registered gzip or original bytes differ')
                registrations.append(dict(journal=identity['journal'], segment=identity['segment_name'],
                    raw_bytes=len(raw), compressed_bytes=descriptor['compressed_bytes'], restored_equal=True))
            if seen != expected_names:
                raise ValueError('registered gzip set differs from complete journal')
    checks = dict(nonempty_replay=bool(comparisons), full_replay_equal=all(all(r['fields'].values()) for r in comparisons),
        no_eligible_after_stop=bool(stops) and all(r['eligible_after_stop'] == 0 for r in stops),
        no_eligible_after_deadline=bool(stops) and all(r['eligible_after_deadline'] == 0 for r in stops),
        intervals_respect_stop=bool(stops) and all(not r['intervals_after_stop'] for r in stops),
        all_gzip_registered_and_equal=bool(registrations))
    return dict(checks=checks, comparisons=comparisons, stops=stops, registrations=registrations,
        raw_records=sum(a['last_audited_sequence'] for a in result['audits']),
        audit_batches=sum(a['valid_batches'] for a in result['audits']))


async def run_probe(output, *, seconds=12, reconnect=True, _transport=None, _runner=run_bounded):
    if type(seconds) is not int or not 5 <= seconds <= 120:
        raise ValueError('duration must be integer 5..120 seconds')
    if type(reconnect) is not bool:
        raise ValueError('reconnect must be bool')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    hashes = {p:file_hash(ROOT/p) for p in SOURCES}
    plan = dict(purpose='SHORT_PUBLIC_PIPELINED_TRANSPORT_QUALIFICATION_NOT_STRATEGY_EVALUATION',
        seconds=seconds, reconnect=reconnect, disconnect_after_setup_seconds=3 if reconnect else None,
        default_seal_seconds=2, source_hashes=hashes, python=sys.version,
        libraries={k:importlib.metadata.version(k) for k in ('websockets','httpx')},
        private_requests=0, actual_orders=0, full_day_pilot=False)
    save(output/'harness_plan.json', plan)
    transport = _transport if _transport is not None else CountedPublicTransport()
    result = error = None
    try:
        result = await _runner(output/'capture', duration_ns=seconds*NS, transport=transport,
            policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
            disconnect_once_after_ns=3*NS if reconnect else None, source_hashes=hashes)
    except (Exception, asyncio.CancelledError, KeyboardInterrupt) as exc:
        error = type(exc).__name__+':'+str(exc)
    finally:
        # Includes frames received but not saved. Offline verification makes no
        # new market requests after this conservative wall-clock observation end.
        inspected_until = time.time_ns()
        save(output/'inspection_record.json', dict(source='PUBLIC_BTCUSDC_PIPELINED_QUALIFICATION',
            conservative_inspection_end_utc_ns=inspected_until,
            conservative_inspection_end_utc=datetime.fromtimestamp(inspected_until/NS, timezone.utc).isoformat(),
            prior_history_must_be_retained=True, connection_attempts=transport.connection_attempts,
            snapshot_attempts=transport.snapshot_attempts, private_requests=0, actual_orders=0,
            new_strategy_evaluation=False, error=error))
        save(output/'transport_timings.json', transport.timings)
    checks = result_checks(result, duration_ns=seconds*NS, reconnect=reconnect)
    checks['sources_unchanged'] = all(file_hash(ROOT/p) == h for p,h in hashes.items())
    checks['no_harness_error'] = error is None
    validation = None
    validation_error = None
    if result and result['result_persisted']:
        try:
            validation = verify_capture(output/'capture', result)
            save(output/'capture_verification.json', validation)
        except Exception as exc:
            validation_error = type(exc).__name__+':'+str(exc)
    checks['independent_capture_verified'] = bool(validation and all(validation['checks'].values()))
    row = dict(success=all(checks.values()), checks=checks, result=result, error=error,
        validation_error=validation_error, connection_attempts=transport.connection_attempts,
        snapshot_attempts=transport.snapshot_attempts, actual_orders=0, private_requests=0)
    save(output/'harness_result.json', row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seconds', type=int, default=12)
    parser.add_argument('--no-reconnect', action='store_true')
    args = parser.parse_args()
    row = asyncio.run(run_probe(args.output, seconds=args.seconds, reconnect=not args.no_reconnect))
    print(json.dumps(dict(success=row['success'], checks=row['checks'], error=row['error'],
        validation_error=row['validation_error'], connection_attempts=row['connection_attempts'],
        snapshot_attempts=row['snapshot_attempts'], actual_orders=0)))
    return 0 if row['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
