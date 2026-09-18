"""Bounded public qualification harness for the frozen segmented collector.

No credentials or order APIs. Harness evidence stays outside capture storage;
all live collection writes remain under the collector's aggregate budget.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.segmented_feed_collector import run_bounded, NS
from app.research.data.public_feed_transport import PublicFeedTransport
from app.research.data.durable_capture_log import file_hash
from app.research.foundation.forward_data_contract import load_contract

SOURCES = [
    'scripts/probe_segmented_feed.py', 'app/research/data/segmented_feed_collector.py',
    'app/research/data/segmented_feed_audit.py', 'app/research/data/shared_feed_storage.py',
    'app/research/data/bounded_feed_collector_v2.py', 'app/research/data/bounded_feed_collector.py',
    'app/research/data/feed_runtime_diagnostics.py', 'app/research/data/public_feed_transport.py',
    'app/research/data/durable_market_feed.py', 'app/research/data/durable_capture_log.py',
    'app/research/data/feed_coverage_audit.py', 'configs/research/forward_data_policy_v1.json',
]


def save(path, value):
    data = json.dumps(value, indent=2, ensure_ascii=False)+'\n'
    if len(data.encode()) > 1024**2:
        raise ValueError('harness artifact exceeds 1 MiB')
    with path.open('x') as stream:
        stream.write(data)


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=12)
    parser.add_argument('--reconnect-drill', action='store_true')
    args = parser.parse_args()
    if not 5 <= args.seconds <= 120:
        parser.error('duration must be 5..120 seconds')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    hashes = {name:file_hash(ROOT/name) for name in SOURCES}
    plan = dict(purpose='BOUNDED_PUBLIC_STORAGE_QUALIFICATION_NOT_STRATEGY_TEST',
                seconds=args.seconds, disconnect_after_setup_seconds=3 if args.reconnect_drill else None,
                source_hashes=hashes, private_requests=0, actual_orders=0, full_day_pilot=False)
    save(output/'harness_plan.json', plan)
    transport = CountedPublicTransport()
    result, error = None, None
    try:
        result = asyncio.run(run_bounded(output/'capture', duration_ns=args.seconds*NS,
            transport=transport, policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
            disconnect_once_after_ns=3*NS if args.reconnect_drill else None, source_hashes=hashes))
    except Exception as exc:
        error = type(exc).__name__+':'+str(exc)
    finally:
        # Conservative wall-clock bound includes frames that could not be stored.
        inspected_until = time.time_ns()
        save(output/'inspection_record.json', dict(
            source='PUBLIC_BTCUSDC_BOUNDED_STORAGE_QUALIFICATION',
            conservative_inspection_end_utc_ns=inspected_until,
            conservative_inspection_end_utc=datetime.fromtimestamp(inspected_until/NS,timezone.utc).isoformat(),
            prior_history_must_be_retained=True, connection_attempts=transport.connection_attempts,
            snapshot_attempts=transport.snapshot_attempts, private_requests=0, actual_orders=0,
            new_strategy_evaluation=False, error=error))
        save(output/'transport_timings.json', transport.timings)
    save(output/'harness_result.json', dict(result=result, error=error,
         connection_attempts=transport.connection_attempts, snapshot_attempts=transport.snapshot_attempts))
    success = bool(result and result['stop_reason']=='ORIGINAL_DEADLINE' and not result['errors'] and
                   result['result_persisted'] and result['audits'] and
                   all(not row['errors'] and not row['processor_errors'] for row in result['audits']))
    print(json.dumps(dict(success=success, stop_reason=result['stop_reason'] if result else None,
        error=error, connection_attempts=transport.connection_attempts,
        snapshot_attempts=transport.snapshot_attempts,
        records=sum(r['committed_raw_records'] for r in result['audits']) if result else 0,
        batches=sum(r['valid_batches'] for r in result['audits']) if result else 0,
        actual_orders=0)))
    return 0 if success else 1


if __name__=='__main__':
    raise SystemExit(main())
