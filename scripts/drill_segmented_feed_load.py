"""Two predeclared synthetic load cases for the new storage path; no network."""
import argparse
import asyncio
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_feed_load_drill import OfflineTransport
from app.research.data.segmented_feed_collector import run_bounded
from app.research.data.durable_capture_log import file_hash
from app.research.foundation.forward_data_contract import load_contract


def save(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2)+'\n')


def worker(directory, rate):
    directory.mkdir()
    transport = OfflineTransport(rate)
    policy = load_contract(ROOT/'configs/research/forward_data_policy_v1.json')
    began, cpu = time.monotonic_ns(), time.process_time_ns()
    result = asyncio.run(run_bounded(directory/'capture', duration_ns=2_000_000_000,
                                     transport=transport, policy=policy))
    elapsed, cpu_elapsed = time.monotonic_ns()-began, time.process_time_ns()-cpu
    assert result['stop_reason'] == 'ORIGINAL_DEADLINE'
    assert len(result['epochs']) == 1 and not result['audits'][0]['errors']
    assert result['epochs'][0]['eligible_point_observations'] > 0
    assert result['epochs'][0]['diagnostics']['retained_bridge_batches'] == 0
    assert all(socket.closed.is_set() for socket in transport.sockets)
    total = sum(path.stat().st_size for path in (directory/'capture').rglob('*') if path.is_file())
    assert result['storage_after_result']['used_bytes'] == total
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    save(directory/'result.json', dict(status='PASS_BOUNDED_SYNTHETIC_LOAD',
        requested_public_events_per_second=rate, duration_ns=2_000_000_000,
        generated_frames=sum(s.count for s in transport.sockets),
        generated_frames_per_original_second=sum(s.count for s in transport.sockets)/2,
        whole_worker_wall_ns=elapsed, cpu_ns=cpu_elapsed,
        process_peak_rss_bytes=rss if sys.platform=='darwin' else rss*1024,
        storage=result['storage_after_result'], diagnostics=result['epochs'][0]['diagnostics'],
        full_day_ready=False, network_requests=0, actual_orders=0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker-rate', type=int, choices=(200,2000))
    args = parser.parse_args()
    output = args.output.resolve()
    if args.worker_rate:
        worker(output, args.worker_rate)
        return
    output.mkdir(parents=True, exist_ok=False)
    sources = ['scripts/drill_segmented_feed_load.py', 'scripts/run_feed_load_drill.py',
               'app/research/data/shared_feed_storage.py', 'app/research/data/segmented_feed_collector.py',
               'app/research/data/segmented_feed_audit.py']
    save(output/'plan.json', dict(requested_public_event_rates=[200,2000], duration_ns_per_case=2_000_000_000,
        fixture='small synthetic frames, no separate producer queue or real exchange timestamps',
        source_hashes={name:file_hash(ROOT/name) for name in sources}, expected_stop='ORIGINAL_DEADLINE',
        network_requests=0, full_day_ready=False))
    for rate in (200,2000):
        with (output/f'worker-{rate}.log').open('x') as stream:
            subprocess.run([sys.executable,__file__,'--output',str(output/f'paced-{rate}'),
                            '--worker-rate',str(rate)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=30)
    print(json.dumps([json.loads((output/f'paced-{rate}'/'result.json').read_text()) for rate in (200,2000)]))


if __name__=='__main__': main()
