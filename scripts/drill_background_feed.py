"""Retained offline evidence for audit/reconnect overlap and late failure."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.background_feed_audit import AuditLimits, BackgroundAudits
from app.research.data.background_feed_collector import run_bounded
from app.research.data.durable_capture_log import file_hash
from app.research.foundation.forward_data_contract import load_contract
from scripts.probe_background_feed import SOURCES, save
from tests.test_bounded_feed_collector import ScriptedTransport
from tests.test_background_feed_audit import command


async def case(root, mode, hashes):
    root.mkdir()
    managers, observations = [], []
    release = root/'release'
    def factory(**kwargs):
        manager = BackgroundAudits(**kwargs, _command=command(mode, release))
        managers.append(manager)
        return manager
    class Transport(ScriptedTransport):
        async def snapshot(self, *args, **kwargs):
            if self.snapshot_count == 1:
                observations.append(dict(event='SECOND_SNAPSHOT_STARTED',
                                         previous_audit_status=managers[0].jobs[0]['status']))
                release.touch()
            return await super().snapshot(*args, **kwargs)
    normal = mode == 'wait'
    transport = Transport(disconnect_first=mode.startswith('wait'))
    result = await run_bounded(root/'capture', duration_ns=2_000_000_000 if normal else 4_000_000_000,
        transport=transport, policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
        source_hashes=hashes, _audit_factory=factory,
        audit_limits=AuditLimits(drain_seconds=.15) if mode == 'hang' else None)
    checks = dict(terminal_reason=result['stop_reason'] == ('ORIGINAL_DEADLINE' if normal else 'FATAL_FAILURE'),
        persisted=result['result_persisted'], child_reaped=result['background_audit']['child_reaped'],
        sockets_closed=all(socket.closed.is_set() for socket in transport.sockets))
    if mode.startswith('wait'):
        checks['reconnected_while_audit_running'] = observations == [dict(
            event='SECOND_SNAPSHOT_STARTED', previous_audit_status='RUNNING')]
        checks['new_session_before_old_audit_completed'] = (
            transport.connections[2][1] < result['background_audit']['jobs'][0]['completed_ns'])
    if not normal:
        checks['failed_quality'] = result['combined']['quality']['status'] == 'QUALITY_INPUTS_REJECTED'
    if mode == 'wait-fail':
        checks['late_failure_stopped_active_epoch'] = result['epochs'][1]['outcome'] == 'FATAL_FAILURE'
        checks['stopped_before_original_deadline'] = result['completed_ns'] < result['original_window']['window_end_ns']
    save(root/'result.json', dict(result=result, observations=observations, checks=checks,
        simulated_connections=transport.connections, actual_network_requests=0, actual_orders=0))
    return dict(mode=mode, passed=all(checks.values()), checks=checks,
                stop_reason=result['stop_reason'], jobs=result['background_audit']['jobs'])


async def run(output):
    output.mkdir(parents=True, exist_ok=False)
    sources = [*SOURCES, 'scripts/drill_background_feed.py', 'tests/test_bounded_feed_collector.py',
               'tests/background_audit_fixture_worker.py', 'tests/test_background_feed_audit.py']
    hashes = {name:file_hash(ROOT/name) for name in sources}
    save(output/'plan.json', dict(source_hashes=hashes, modes=['wait', 'wait-fail', 'hang'],
        actual_network_requests=0, actual_orders=0, synthetic_data=True,
        purpose='CONTROL_FLOW_AND_PROCESS_LIFECYCLE_NOT_MARKET_PERFORMANCE'))
    rows = []
    for mode in ('wait', 'wait-fail', 'hang'):
        rows.append(await case(output/mode, mode, hashes))
    save(output/'summary.json', dict(passed=all(row['passed'] for row in rows), scenarios=rows,
                                    actual_network_requests=0, actual_orders=0))
    print(json.dumps(rows))
    if not all(row['passed'] for row in rows): raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(run(parser.parse_args().output.resolve()))
