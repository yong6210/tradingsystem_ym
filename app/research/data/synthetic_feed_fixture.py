"""Deterministic OFFLINE fixture builder; never a live capture or fsync benchmark.

Synthetic commit/observation clocks describe the model, not physical durability
receipts. Buffered files become physically committed at rotation/finalization.
The actual production reader validates every stored hash/sequence before replay.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil

from .durable_capture_log import encoded, atomic_json, sync_directory, ZERO, integer
from .durable_market_feed import MarketFeedProcessor, PUBLIC_URL, MARKET_URL, SNAPSHOT_URL

NS = 1_000_000_000
PERIOD = 50_000_000
EPOCH = 'synthetic-full-file-epoch-v1'
WALL_ORIGIN = 1_600_000_000_000_000_000  # Fictional origin, never an inspected market timestamp.


class FixtureBudget:
    def __init__(self, root, *, max_bytes=6*1024**3, min_free_bytes=16*1024**3):
        self.root = Path(root)
        self.max_bytes, self.min_free_bytes = integer(max_bytes, 1), integer(min_free_bytes)
        self.used = 0
        self.checked_at = 0
        self.check_space()

    def check_space(self):
        if shutil.disk_usage(self.root).free < self.min_free_bytes+4*1024**2:
            raise OSError('fixture physical free-space reserve')
        self.checked_at = self.used

    def reserve(self, size):
        if self.used+size > self.max_bytes:
            raise OSError('fixture aggregate byte limit')
        self.used += size
        if self.used-self.checked_at >= 1024**2:
            self.check_space()


class FixtureJournal:
    """Bulk fixture serializer for the frozen format, not a publication API."""
    def __init__(self, directory, budget, run_id, *, rotation_bytes):
        self.directory, self.budget = Path(directory), budget
        self.directory.mkdir()
        self.meta = dict(version=1, run_id=run_id, rotation_bytes=rotation_bytes,
                         max_record_bytes=4*1024**2, max_total_bytes=budget.max_bytes,
                         min_free_bytes=budget.min_free_bytes)
        self.sequence, self.record_hash = 0, ZERO
        self.entries = []
        self.stream = None
        self.closed = False
        self._json('metadata.json', self.meta)

    def _json(self, name, value):
        self.budget.reserve(len(encoded(value)))
        atomic_json(self.directory, name, value)

    def _close_segment(self):
        if self.stream is not None:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()
            self.stream = None

    def _write(self, line):
        self.budget.reserve(len(line))
        if self.stream.write(line) != len(line):
            raise OSError('short fixture write')
        self.active_hash.update(line)
        self.entries[-1]['bytes'] += len(line)
        self.entries[-1]['sha256'] = self.active_hash.hexdigest()

    def _segment(self):
        self._close_segment()
        index = len(self.entries)
        if index >= 10_000:
            raise ValueError('fixture manifest bound')
        header = encoded(dict(kind='SEGMENT', run_id=self.meta['run_id'], epoch=EPOCH,
            index=index, first_sequence=self.sequence+1,
            previous_segment_sha256=self.entries[-1]['sha256'] if self.entries else ZERO))
        name = f'segment-{index:07d}.jsonl'
        self.stream = (self.directory/name).open('xb', buffering=1024**2)
        self.active_hash = hashlib.sha256()
        self.entries.append(dict(name=name, bytes=0, sha256=ZERO))
        self._write(header)

    def append(self, payload):
        if self.closed:
            raise ValueError('fixture closed')
        body = dict(sequence=self.sequence+1, epoch=EPOCH, previous_record_sha256=self.record_hash, payload=payload)
        identity = hashlib.sha256(encoded(body)).hexdigest()
        line = encoded(body | dict(sha256=identity))
        if len(line) > self.meta['max_record_bytes']:
            raise ValueError('fixture record bound')
        if self.stream is None or self.entries[-1]['bytes']+len(line) > self.meta['rotation_bytes']:
            self._segment()
        if self.entries[-1]['bytes']+len(line) > self.meta['rotation_bytes']:
            raise ValueError('fixture record cannot fit')
        self._write(line)
        self.sequence, self.record_hash = body['sequence'], identity

    def finish(self):
        self._close_segment()
        self._json('checkpoint.json', dict(version=1, run_id=self.meta['run_id'],
            metadata_sha256=hashlib.sha256(encoded(self.meta)).hexdigest(), last_sequence=self.sequence,
            last_record_sha256=self.record_hash, segments=self.entries))
        sync_directory(self.directory)
        self.closed = True

    def close(self):
        # Error cleanup retains partial files without making a checkpoint.
        self._close_segment()
        self.closed = True


def build_fixture(root, seconds, *, max_bytes=6*1024**3, min_free_bytes=16*1024**3, progress=lambda value: None):
    integer(seconds, 1)
    if seconds > 86400:
        raise ValueError('synthetic fixture limited to one day')
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    budget = FixtureBudget(root, max_bytes=max_bytes, min_free_bytes=min_free_bytes)
    deadline = seconds*NS
    run_id = f'synthetic-full-feed-{seconds}s-v1'
    raw = FixtureJournal(root/'journal', budget, run_id, rotation_bytes=128*1024**2)
    audit = None
    try:
        audit = FixtureJournal(root/'audit', budget, run_id, rotation_bytes=32*1024**2)
        processor = MarketFeedProcessor()
        at = 0
        def emit(kind, channel, **fields):
            payload = dict(kind=kind, channel=channel, session=EPOCH if channel=='system' else channel,
                process_epoch=EPOCH, received_ns=at, received_utc_ns=WALL_ORIGIN+at) | fields
            raw.append(payload)
            processor.apply(raw.sequence, payload, processed_ns=at)
        def message(channel, stream, data):
            emit('WS', channel, wire_text=json.dumps(dict(stream=stream, data=data), separators=(',',':')))
        def batch(begin):
            observation = processor.observe(now_ns=at, committed_ns=at, committed_sequence=raw.sequence)
            if processor.errors:
                raise AssertionError(processor.errors)
            audit.append(dict(first_sequence=begin, last_sequence=raw.sequence, record_sha256=raw.record_hash,
                              committed_ns=at, observation=observation))
        depth_id = 12
        points = seconds*20
        for index in range(points):
            at = index*PERIOD
            begin = raw.sequence+1
            if index == 0:
                emit('RUN_WINDOW', 'system', started_ns=0, deadline_ns=deadline)
                emit('OPEN', 'public', url=PUBLIC_URL)
                emit('OPEN', 'market', url=MARKET_URL)
                emit('REQUEST', 'public', request_id='snapshot', url=SNAPSHOT_URL)
                emit('SNAPSHOT', 'public', request_id='snapshot', request_started_ns=0, http_status=200,
                    wire_text=json.dumps(dict(lastUpdateId=10,bids=[['100','2'],['99','3']],
                                              asks=[['101','4'],['102','5']]),separators=(',',':')))
            if index%2 == 0:
                previous = depth_id
                if index:
                    depth_id += 1
                message('public', 'btcusdc@depth@100ms', dict(e='depthUpdate',s='BTCUSDC',E=index+1000,T=index+999,
                    U=9 if index==0 else depth_id,u=depth_id,pu=8 if index==0 else previous,b=[],a=[]))
            message('public', 'btcusdc@bookTicker', dict(e='bookTicker',s='BTCUSDC',E=index+1000,T=index+999,
                u=depth_id,b='100',B='2',a='101',A='4'))
            if index%20 == 0:
                message('market','btcusdc@markPrice@1s',dict(e='markPriceUpdate',s='BTCUSDC',E=index+1000,
                    T=index+2000,p='100',i='100',r='0'))
                identity = index//20+1
                message('market','btcusdc@aggTrade',dict(e='aggTrade',s='BTCUSDC',E=index+1000,T=index+999,
                    a=identity,f=identity,l=identity,p='100',q='2',m=True))
            if index%5 == 0:
                emit('WATCHDOG','system',expected_ns=at)
            batch(begin)
            if index and index%20_000 == 0:
                progress(dict(phase='GENERATE',batches=index,of=points,logical_bytes=budget.used))
        at = deadline
        begin = raw.sequence+1
        emit('STOP','system',reason='SYNTHETIC_END')
        emit('END','public',reason='SYNTHETIC_END')
        emit('END','market',reason='SYNTHETIC_END')
        batch(begin)
        raw.finish()
        audit.finish()
        scope=dict(window_start_ns=0,window_end_ns=deadline,clock_domain='synthetic-full-file-v1')
        plan=dict(run_id=run_id,**scope,seconds=seconds,raw_records=raw.sequence,audit_batches=audit.sequence,
            logical_bytes_before_plan=budget.used,synthetic=True,new_market_capture=False,
            live_durability_timing=False,profile=dict(bookTicker_hz=20,depth_hz=10,mark_hz=1,aggTrade_hz=1,watchdog_hz=4),
            expected_intervals={key:[[0,deadline]] for key in ('l2','market_connection','mark','clock','durable_log')})
        budget.reserve(len(encoded(plan)))
        atomic_json(root,'plan.json',plan)
        sync_directory(root.parent)
        actual=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        assert budget.used == actual
        assert raw.sequence == 36*seconds+8
        assert audit.sequence == 20*seconds+1
        return plan | dict(total_bytes=actual)
    finally:
        raw.close()
        if audit is not None:
            audit.close()
