"""Observed storage scenarios, never a market-rate bound or pilot admission."""
from collections import deque
from pathlib import Path
import stat

from .durable_capture_log import encoded, integer
from .verified_journal_view import VerifiedJournalView

NS = 1_000_000_000


def rolling_peak(events, window_ns=NS):
    """Maximum retained record bytes in any (t-window, t], not aligned bins."""
    integer(window_ns, 1)
    queue, total, peak = deque(), 0, 0
    previous = -1
    for stamp, size in events:
        integer(stamp); integer(size)
        if stamp < previous: raise ValueError('events must be sorted')
        previous = stamp
        while queue and queue[0][0] <= stamp-window_ns:
            total -= queue.popleft()[1]
        queue.append((stamp, size)); total += size
        peak = max(peak, total)
    return peak


def inventory(root):
    root = Path(root)
    if root.resolve() != root.absolute(): raise ValueError('canonical capture required')
    device = root.stat().st_dev
    logical = allocated = files = 0
    for path in root.rglob('*'):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_dev != device:
            raise ValueError('symlink or different filesystem')
        if stat.S_ISDIR(info.st_mode): continue
        if not stat.S_ISREG(info.st_mode): raise ValueError('nonregular capture file')
        files += 1
        if files > 100_000: raise ValueError('inventory file limit')
        logical += info.st_size
        allocated += info.st_blocks*512
    return dict(logical_bytes=logical, allocated_bytes=allocated, files=files,
                allocation_scope='STAT_BLOCKS_NOT_APFS_SNAPSHOT_OR_EXCLUSIVE_PHYSICAL_USAGE')


def capture_sample(root, result, *, max_records=100_000):
    """Small closed qualification captures only; validate before deriving rates."""
    integer(max_records, 1)
    if max_records > 100_000: raise ValueError('sample record bound')
    root = Path(root).resolve()
    scope = result['original_window']
    start, end = scope['window_start_ns'], scope['window_end_ns']
    integer(start); integer(end, start+1)
    if end-start > 120*NS: raise ValueError('short sample only')
    before = inventory(root)
    if before['logical_bytes'] != result['storage_after_result']['used_bytes']:
        raise ValueError('retained inventory differs from collection result')
    events, raw_events, record_bytes, count = [], [], 0, 0
    after_window_bytes = 0
    for epoch in result['epochs']:
        name = epoch['directory']
        if not name.startswith('epoch-') or Path(name).name != name:
            raise ValueError('invalid epoch directory')
        for kind in ('journal', 'audit'):
            with VerifiedJournalView(root/name/kind) as view:
                if view.recovery['uncommitted_suffixes'] or view.recovery['pending_checkpoint_files']:
                    raise ValueError('uncertain tail cannot define input envelope')
                for record in view.records():
                    count += 1
                    if count > max_records: raise ValueError('sample record limit')
                    size = len(encoded(record))
                    payload = record['payload']
                    stamp = payload['received_ns'] if kind == 'journal' else payload['observation']['published_ns']
                    record_bytes += size
                    if start <= stamp < end:
                        events.append((stamp, size))
                        if kind == 'journal' and payload['kind'] == 'WS': raw_events.append((stamp, 1))
                    else:
                        after_window_bytes += size
    if inventory(root) != before: raise ValueError('capture changed during sample')
    if record_bytes > before['logical_bytes']: raise ValueError('record/inventory mismatch')
    return dict(capture=str(root), calendar_ns=end-start, **before,
        raw_and_audit_record_bytes=record_bytes, outside_window_record_bytes=after_window_bytes,
        headers_metadata_supervisor_result_bytes=before['logical_bytes']-record_bytes,
        peak_rolling_1s_record_bytes=rolling_peak(sorted(events)),
        peak_rolling_1s_received_ws_frames=rolling_peak(sorted(raw_events)),
        records=count, observed_rate_is_market_upper_bound=False,
        time_basis='RAW_APPLICATION_RECEIPT_AND_AUDIT_OBSERVATION_NOT_DISK_IO_OR_WIRE_ARRIVAL',
        includes_checkpoint_rewrite_io=False)


def project_storage(*, bytes_per_second, seconds, free_bytes, logical_cap_bytes,
                    reserve_bytes=16*1024**3, transient_allowance_bytes=64*1024**2):
    """Integer arithmetic and separate disk/logical constraints; assumption only."""
    for value in (bytes_per_second, seconds, logical_cap_bytes): integer(value, 1)
    for value in (free_bytes, reserve_bytes, transient_allowance_bytes): integer(value)
    retained = bytes_per_second*seconds
    required = retained+transient_allowance_bytes
    disk_available = max(0, free_bytes-reserve_bytes)
    usable = min(disk_available, logical_cap_bytes)
    return dict(status='CONDITIONAL_SPACE_SCENARIO_NOT_ADMISSION', seconds=seconds,
        assumed_bytes_per_second=bytes_per_second, projected_retained_bytes=retained,
        transient_allowance_bytes=transient_allowance_bytes, required_bytes=required,
        disk_available_above_reserve_bytes=disk_available, logical_cap_bytes=logical_cap_bytes,
        conditional_space_fit=required <= disk_available and required <= logical_cap_bytes,
        additional_free_bytes_needed=max(0, required-disk_available),
        logical_cap_shortfall_bytes=max(0, required-logical_cap_bytes),
        maximum_seconds_under_assumption=max(0, usable-transient_allowance_bytes)//bytes_per_second,
        rate_enforced=False, transient_allowance_proven_sufficient=False, full_day_ready=False)
