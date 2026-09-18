"""Integer capacity scenarios with protocol limits kept separate from space.

Compression and input rates are explicit assumptions, not enforceable market
bounds. Disk fit alone must never grant permission for a longer collection.
"""
from .durable_capture_log import integer


def retention_capacity(*,seconds,raw_bytes_per_second,gzip_ratio_ppm,metadata_bytes_per_unit,
                       seal_seconds,free_bytes,logical_cap_bytes,existing_bytes=0,
                       reserve_bytes=16*1024**3,transient_bytes=64*1024**2,
                       max_units_per_capture=62,max_attempts=7,max_supervisor_events=4096):
    for value in (seconds,raw_bytes_per_second,metadata_bytes_per_unit,seal_seconds,logical_cap_bytes,
                  max_units_per_capture,max_attempts,max_supervisor_events):integer(value,1)
    for value in (gzip_ratio_ppm,free_bytes,existing_bytes,reserve_bytes,transient_bytes):integer(value)
    if not 1<=gzip_ratio_ppm<=2_000_000:raise ValueError('compression assumption outside 0..2x bound')
    units=(seconds+seal_seconds-1)//seal_seconds
    raw=raw_bytes_per_second*seconds
    gzip_bytes=(raw*gzip_ratio_ppm+999_999)//1_000_000
    metadata=units*metadata_bytes_per_unit
    # Optimistic lower bound: two work events/receipts per unit, ignoring epoch
    # setup/final/recovery events. Even this bound may exhaust the protocol.
    minimum_events=2*units
    archive_steady=gzip_bytes+metadata
    retain_all=raw+archive_steady
    disk_available=max(0,free_bytes-reserve_bytes)
    logical_available=max(0,logical_cap_bytes-existing_bytes)
    blockers=[]
    if seconds>120:blockers.append('ORIGINAL_WINDOW_LIMIT_120_SECONDS')
    if units>max_units_per_capture*max_attempts:blockers.append('TOTAL_UNIT_BUDGET')
    if minimum_events>max_supervisor_events:blockers.append('SUPERVISOR_EVENT_BUDGET_EVEN_BEFORE_FIXED_OVERHEAD')
    blockers.extend(['CLOSED_CAPTURE_RETIREMENT_NOT_ACTIVE_SEGMENT_RETIREMENT',
                     'RATE_AND_COMPRESSION_ASSUMPTIONS_NOT_ENFORCED',
                     'METADATA_AND_TEMPORARY_PEAK_NOT_QUALIFIED_FOR_LONG_RUN'])
    return dict(status='CONDITIONAL_STORAGE_SCENARIO_NOT_ADMISSION',seconds=seconds,units=units,
        raw_bytes=raw,assumed_gzip_ratio_ppm=gzip_ratio_ppm,gzip_bytes=gzip_bytes,
        metadata_bytes=metadata,minimum_supervisor_events=minimum_events,
        archive_only_steady_bytes=archive_steady,retain_all_until_closed_bytes=retain_all,
        transient_bytes=transient_bytes,available_disk_above_reserve=disk_available,
        available_logical_bytes=logical_available,
        hypothetical_active_retirement_space_fit=archive_steady+transient_bytes<=min(disk_available,logical_available),
        current_closed_retirement_peak_space_fit=retain_all+transient_bytes<=min(disk_available,logical_available),
        blockers=blockers,active_retirement_implemented=False,long_run_admitted=False,
        physical_exclusive_bytes_estimated=False)
