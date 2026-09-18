"""Run a short public data-only collector, optionally closing one local socket."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.bounded_feed_collector import run_bounded, NS
from app.research.data.public_feed_transport import PublicFeedTransport
from app.research.foundation.forward_data_contract import load_contract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=12)
    parser.add_argument('--reconnect-drill', action='store_true', help='Close public socket once, 3 seconds after setup.')
    args = parser.parse_args()
    if not 5 <= args.seconds <= 120:
        parser.error('bounded public probe requires 5..120 seconds')
    policy = load_contract(ROOT/'configs/research/forward_data_policy_v1.json')
    sources = ['app/research/data/bounded_feed_collector.py', 'app/research/data/public_feed_transport.py',
               'scripts/probe_bounded_feed.py', 'app/research/data/durable_market_feed.py',
               'app/research/data/durable_capture_log.py', 'app/research/data/feed_coverage_audit.py',
               'configs/research/forward_data_policy_v1.json']
    hashes = {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in sources}
    transport = PublicFeedTransport()
    result = asyncio.run(run_bounded(args.output, duration_ns=args.seconds*NS, transport=transport,
                         policy=policy, disconnect_once_after_ns=3*NS if args.reconnect_drill else None,
                         source_hashes=hashes))
    (args.output/'transport_timings.json').write_text(json.dumps(transport.timings, indent=2)+'\n')
    inspection = dict(source='PUBLIC_BTCUSDC_READ_ONLY_BOUNDED_COLLECTOR',
                      latest_inspected_utc=datetime.fromtimestamp(result['latest_received_utc_ns']/NS, timezone.utc).isoformat(),
                      latest_inspected_utc_ns=result['latest_received_utc_ns'],
                      prior_history_must_also_be_retained=True, new_strategy_evaluation=False)
    (args.output/'inspection_record.json').write_text(json.dumps(inspection, indent=2)+'\n')
    concise = {key:result[key] for key in ('stop_reason','retries_used','total_public_connection_attempts',
                                          'total_snapshot_requests','total_raw_bytes','actual_orders','errors')}
    concise['epochs'] = [{key:row[key] for key in ('outcome','reason','processor_errors','forced_local_disconnect','counts',
                          'audited_batches','eligible_point_observations','close_errors')} for row in result['epochs']]
    concise['quality'] = result['combined']['quality'] if result['combined'] else None
    print(json.dumps(concise, indent=2))
    return 0 if result['stop_reason']=='ORIGINAL_DEADLINE' and not result['errors'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
