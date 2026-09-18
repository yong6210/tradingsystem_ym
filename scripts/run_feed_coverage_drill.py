"""Offline durable-feed crash/restart drills; no network or order transport.

Market payloads are scripted. Commit/publication clocks and child SIGKILLs
are real. All children belong to this invocation's one host clock domain.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.durable_capture_log import DurableCaptureLog
from app.research.data.durable_market_feed import DurableFeedBridge, PUBLIC_URL, MARKET_URL, SNAPSHOT_URL
from app.research.data.feed_coverage_audit import audit_epoch, combine_epochs
from app.research.foundation.forward_data_contract import load_contract

STAGES = ('before_raw_commit', 'before_audit_write', 'torn_audit', 'after_audit_fsync')


def dump(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2)+'\n')
        stream.flush()
        os.fsync(stream.fileno())


def hashes(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob('*')) if p.is_file()}


def new_plan(directory):
    start = time.monotonic_ns()
    plan = dict(window_start_ns=start, window_end_ns=start+10_000_000_000,
                clock_domain='single-host-invocation:'+uuid.uuid4().hex)
    dump(directory/'plan.json', plan)
    return plan


class ScriptedFeed:
    def __init__(self, directory, plan):
        directory.mkdir()
        self.directory, self.plan = directory, plan
        self.journal = DurableCaptureLog.create(directory/'journal', run_id='offline-feed-drill',
                                                min_free_bytes=0)
        self.bridge = DurableFeedBridge(self.journal)
        self.sessions = dict(public='public-1', market='market-1', system=self.journal.epoch)
        self.add('RUN_WINDOW', 'system', started_ns=plan['window_start_ns'], deadline_ns=plan['window_end_ns'])
        self.add('OPEN', 'public', url=PUBLIC_URL)
        self.add('OPEN', 'market', url=MARKET_URL)

    def add(self, kind, channel, **fields):
        received = time.monotonic_ns()
        if kind == 'WATCHDOG':
            fields['expected_ns'] = received
        self.bridge.append(dict(kind=kind, channel=channel, session=self.sessions[channel],
                                received_ns=received, received_utc_ns=time.time_ns()) | fields)
        return received

    def fresh_depth(self, identity=10):
        started = self.add('REQUEST', 'public', url=SNAPSHOT_URL, request_id='snapshot-'+str(identity))
        snapshot = dict(lastUpdateId=identity, bids=[['100', '2'], ['99', '3']],
                        asks=[['101', '4'], ['102', '5']])
        self.add('SNAPSHOT', 'public', request_id='snapshot-'+str(identity), request_started_ns=started,
                 http_status=200, wire_text=json.dumps(snapshot))
        event = dict(e='depthUpdate', s='BTCUSDC', E=1000+identity, T=999+identity,
                     U=identity-1, u=identity+2, pu=identity-2, b=[], a=[])
        self.add('WS', 'public', wire_text=json.dumps(dict(stream='btcusdc@depth@100ms', data=event)))

    def fresh_mark(self, event_time=1000):
        event = dict(e='markPriceUpdate', s='BTCUSDC', E=event_time, T=2000, p='100', i='100', r='0')
        self.add('WS', 'market', wire_text=json.dumps(dict(stream='btcusdc@markPrice@1s', data=event)))

    def save(self, batch, *, torn=False):
        line = (json.dumps(batch)+'\n').encode()
        with (self.directory/'batches.jsonl').open('ab') as stream:
            stream.write(line[:len(line)//2] if torn else line)
            stream.flush()
            os.fsync(stream.fileno())

    def flush(self):
        batch = self.bridge.flush()
        self.save(batch)
        return batch['observation']

    def healthy(self):
        self.fresh_depth()
        self.fresh_mark()
        self.add('WATCHDOG', 'system')
        assert self.flush()['eligible']

    def tick(self):
        self.add('WATCHDOG', 'system')
        return self.flush()

    def stop(self):
        self.add('STOP', 'system')
        self.add('END', 'public')
        self.add('END', 'market')
        assert not self.flush()['eligible']
        self.journal.close()

    def audit(self):
        return audit_epoch(self.directory/'journal', self.directory/'batches.jsonl', **self.plan)


def kill_worker(case, stage):
    plan = json.loads((case/'plan.json').read_text())
    feed = ScriptedFeed(case/'before_crash', plan)
    feed.healthy()
    time.sleep(.02)
    feed.add('WATCHDOG', 'system')
    if stage != 'before_raw_commit':
        batch = feed.bridge.flush()
        if stage == 'torn_audit':
            feed.save(batch, torn=True)
        elif stage == 'after_audit_fsync':
            feed.save(batch)
    dump(case/'kill_marker.json', dict(stage=stage, sequence=feed.journal.sequence,
                                      committed_sequence=feed.journal.receipt.sequence,
                                      process_epoch=feed.journal.epoch))
    os.kill(os.getpid(), signal.SIGKILL)
    raise AssertionError('SIGKILL did not terminate worker')


def crash_case(output, stage, policy):
    case = output/stage
    case.mkdir()
    plan = new_plan(case)
    child = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', str(case),
                            '--stage', stage], capture_output=True, text=True, timeout=8)
    assert child.returncode == -signal.SIGKILL, (child.returncode, child.stderr)
    original = case/'before_crash'
    before = hashes(original)
    first = audit_epoch(original/'journal', original/'batches.jsonl', **plan)
    assert first['raw_prefix_valid']
    assert first['valid_batches'] == (2 if stage == 'after_audit_fsync' else 1)
    assert first['unaudited_committed_records'] == (1 if stage in ('before_audit_write', 'torn_audit') else 0)
    assert bool(first['raw_recovery']['uncommitted_suffixes']) == (stage == 'before_raw_commit')
    if stage == 'before_raw_commit':
        assert 'UNCOMMITTED_RAW_SUFFIX_PRESENT' in first['errors']
    assert not first['clean_stop_audited']
    # Raw recovery remains available for inspection, never for resurrecting
    # live order-book/connection/watchdog state in this feed bridge.
    with DurableCaptureLog.resume(original/'journal') as recovered:
        try:
            DurableFeedBridge(recovered)
        except ValueError:
            old_live_state_rejected = True
        else:
            raise AssertionError('old raw journal was accepted as fresh live state')
    assert hashes(original) == before

    restarted = ScriptedFeed(case/'after_restart', plan)
    restarted.add('WATCHDOG', 'system')
    warmup = restarted.flush()
    assert not warmup['eligible'] and not warmup['gates']['l2'] and not warmup['gates']['mark']
    restarted.healthy()
    time.sleep(.02)
    assert restarted.tick()['eligible']
    restarted.stop()
    second = restarted.audit()
    assert not second['errors'] and not second['processor_errors'] and second['clean_stop_audited']
    assert first['epoch'] != second['epoch']
    assert all(lo >= warmup['published_ns'] for spans in second['intervals'].values() for lo, hi in spans)
    combined = combine_epochs(policy, [first, second], **plan)
    assert combined['quality']['calendar_ns'] == 10_000_000_000
    assert combined['quality']['joint_eligible_ns'] > 0
    gap_left, gap_right = first['last_audited_publication_ns'], second['first_audited_publication_ns']
    assert gap_left < gap_right
    assert all(hi <= gap_left or lo >= gap_right for spans in combined['intervals'].values() for lo, hi in spans)
    if stage != 'after_audit_fsync':
        assert 'EPOCH_AUDIT_OR_PROCESSOR_FAILURE' in combined['quality']['reasons']
    assert hashes(original) == before
    result = dict(status='PASS_SCOPED_PROCESS_CRASH_RESTART', stage=stage, child_exit_code=child.returncode,
                  original_bytes_unchanged=True, old_live_state_rejected=old_live_state_rejected,
                  new_epoch_requires_fresh_inputs=True, restart_gap_ns=gap_right-gap_left,
                  original_window_preserved=True, before_crash=first, after_restart=second, combined=combined)
    dump(case/'result.json', result)
    return dict(stage=stage, status=result['status'], child_exit_code=child.returncode,
                missing_committed_audit_records=first['unaudited_committed_records'],
                restart_gap_ns=result['restart_gap_ns'], quality_status=combined['quality']['status'])


def disconnect_case(output, policy):
    case = output/'disconnect_reconnect'
    case.mkdir()
    plan = new_plan(case)
    feed = ScriptedFeed(case/'epoch', plan)
    feed.healthy()
    time.sleep(.02)
    feed.tick()
    cuts = []
    for channel in ('market', 'public'):
        receipt = feed.add('END', channel)
        time.sleep(.02)  # Deliberately separate failure receipt and publication.
        ended = feed.flush()
        assert not ended['eligible']
        cuts.append([receipt, ended['published_ns']])
        feed.sessions[channel] = channel+'-2'
        feed.add('OPEN', channel, url=MARKET_URL if channel == 'market' else PUBLIC_URL)
        assert not feed.flush()['eligible']
        if channel == 'market':
            feed.fresh_mark(event_time=1001)
        else:
            feed.fresh_depth(identity=20)
        feed.add('WATCHDOG', 'system')
        assert feed.flush()['eligible']
        time.sleep(.02)
        assert feed.tick()['eligible']
    feed.stop()
    audit = feed.audit()
    assert not audit['errors'] and not audit['processor_errors']
    combined = combine_epochs(policy, [audit], **plan)
    for left, right in cuts:
        assert all(hi <= left or lo >= right for spans in combined['intervals'].values() for lo, hi in spans)
    result = dict(status='PASS_SCRIPTED_CHANNEL_RECONNECT', scripted_channels=['market', 'public'],
                  detection_to_publication_excluded=cuts, new_sessions_require_fresh_inputs=True,
                  real_network_outage=False, audit=audit, combined=combined)
    dump(case/'result.json', result)
    return dict(status=result['status'], scripted_channels=result['scripted_channels'])


def archived_capture(output, policy):
    source = ROOT/'reports/validation/durable_market_feed_v2_20260917'
    before = hashes(source)
    result = json.loads((source/'probe_result.json').read_text())
    plan = dict(window_start_ns=result['started_ns'], window_end_ns=result['planned_end_ns'],
                clock_domain='archived-durable-market-feed-v2-only')
    audit = audit_epoch(source/'journal', source/'batches.jsonl', **plan)
    assert not audit['errors'] and not audit['processor_errors']
    assert audit['valid_batches'] == result['batches']
    combined = combine_epochs(policy, [audit], **plan)
    assert combined['quality']['calendar_ns'] == 12_000_000_000
    assert combined['quality']['status'] == 'QUALITY_INPUTS_REJECTED'
    assert 'NOT_REGISTERED_PILOT_DURATION' in combined['quality']['reasons']
    assert hashes(source) == before
    report = dict(source=str(source.relative_to(ROOT)), source_unchanged=True,
                  new_capture=False, audit=audit, combined=combined)
    dump(output/'archived_capture_intervals.json', report)
    return combined['quality']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--stage', choices=STAGES)
    args = parser.parse_args()
    if args.worker:
        if args.stage is None:
            parser.error('--stage required for worker')
        kill_worker(args.worker, args.stage)
        return
    if args.output is None:
        parser.error('--output required')
    args.output.mkdir(parents=True, exist_ok=False)
    policy = load_contract(ROOT/'configs/research/forward_data_policy_v1.json')
    cases = [crash_case(args.output, stage, policy) for stage in STAGES]
    reconnect = disconnect_case(args.output, policy)
    archive = archived_capture(args.output, policy)
    result = dict(status='PASS_SCOPED_FEED_COVERAGE_DRILLS', killed_child_processes=len(cases),
                  crashes=cases, reconnect=reconnect, archived_capture_quality=archive,
                  network_requests=0, private_requests=0, actual_orders=0, strategy_adoption=False,
                  continuous_runtime_coverage_certified=False,
                  limitations=['Scripted feed content with real local process crashes and fsync clocks.',
                               'No actual network fault, power-cut or long-duration qualification.',
                               'Intervals model recorded states and TTLs; unobserved faults remain unproven.',
                               'No extrapolation after the final verified processing observation.',
                               'Clock domains require independent evidence; labels alone are insufficient.'])
    dump(args.output/'drill_summary.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
