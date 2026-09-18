"""Read-only-input gzip feasibility measurement on closed public capture segments.

Writes new benchmark archives; does not replace/delete raw files or alter live
collection. Includes flush/fsync and full decompression/hash verification.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.durable_capture_log import file_hash
from scripts.report_storage_envelope import PUBLIC_RUNS
from scripts.drill_queued_feed_load import save


def measure(output):
    output.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(output).free < 16*1024**3+32*1024**2:
        raise OSError('archive benchmark free-space reserve')
    save(output/'plan.json', dict(levels=[1, 6], buffer_bytes=256*1024,
        archive_byte_cap=32*1024**2, original_files_retained=True,
        source_hashes={p:file_hash(ROOT/p) for p in ('scripts/measure_feed_archive.py', 'scripts/report_storage_envelope.py')},
        source_runs=PUBLIC_RUNS, live_collector_changed=False, new_network_requests=0))
    used, rows = 0, []
    for level in (1, 6):
        for index, name in enumerate(PUBLIC_RUNS):
            capture = ROOT/name/'capture'
            paths = sorted(capture.glob('**/segment-*.jsonl'))
            total_retained = sum(p.stat().st_size for p in capture.rglob('*') if p.is_file())
            details = []
            for source in paths:
                target = output/f'gzip-{level}'/f'run-{index:02d}'/source.relative_to(capture)
                target = target.with_suffix(target.suffix+'.gz')
                target.parent.mkdir(parents=True, exist_ok=True)
                expected = file_hash(source)
                began = time.monotonic_ns()
                with source.open('rb') as reader, target.open('xb') as raw:
                    previous = 0
                    with gzip.GzipFile(filename='', fileobj=raw, mode='wb', compresslevel=level, mtime=0) as writer:
                        while chunk := reader.read(256*1024):
                            writer.write(chunk)
                            growth = raw.tell()-previous
                            used += growth; previous += growth
                            if used > 32*1024**2: raise OSError('benchmark archive cap')
                    used += raw.tell()-previous
                    if used > 32*1024**2: raise OSError('benchmark archive cap')
                    raw.flush(); os.fsync(raw.fileno())
                compressed_ns = time.monotonic_ns()-began
                digest, restored = hashlib.sha256(), 0
                began = time.monotonic_ns()
                with gzip.open(target, 'rb') as stream:
                    while chunk := stream.read(256*1024):
                        digest.update(chunk); restored += len(chunk)
                verify_ns = time.monotonic_ns()-began
                if digest.hexdigest() != expected or restored != source.stat().st_size or file_hash(source) != expected:
                    raise ValueError('archive roundtrip/source changed')
                details.append(dict(source=str(source.relative_to(ROOT)), source_sha256=expected,
                    archive=str(target.relative_to(output)), archive_sha256=file_hash(target),
                    raw_bytes=restored, archive_bytes=target.stat().st_size,
                    compression_and_file_fsync_ns=compressed_ns, full_decompression_hash_ns=verify_ns,
                    roundtrip_equal=True))
            original = sum(r['raw_bytes'] for r in details)
            archived = sum(r['archive_bytes'] for r in details)
            rows.append(dict(run=name, gzip_level=level, segment_raw_bytes=original,
                segment_archive_bytes=archived, segment_ratio_ppm=archived*1_000_000//original,
                retained_raw_capture_bytes=total_retained,
                hypothetical_archive_plus_unchanged_aux_bytes=total_retained-original+archived,
                compression_and_file_fsync_ns=sum(r['compression_and_file_fsync_ns'] for r in details),
                full_decompression_hash_ns=sum(r['full_decompression_hash_ns'] for r in details), files=details))
    save(output/'summary.json', dict(status='LOSSLESS_CLOSED_SEGMENT_FEASIBILITY_ONLY', rows=rows,
        archive_bytes_written=used, all_roundtrips_equal=True, original_files_retained=True,
        disk_space_reclaimed_bytes=0, live_compression_implemented=False,
        atomic_archive_promotion_implemented=False, crash_recovery_qualified=False,
        full_day_ready=False, input_rate_upper_bound_established=False,
        timing_scope='WARM_OR_UNCONTROLLED_OS_CACHE_SERIAL_FILE_COMPRESSION_FSYNC_AND_VERIFY',
        metadata_directory_fsync_included=False, new_network_requests=0))
    print(json.dumps([dict(run=r['run'], level=r['gzip_level'], ratio_ppm=r['segment_ratio_ppm'],
        compress_ms=r['compression_and_file_fsync_ns']/1e6, verify_ms=r['full_decompression_hash_ns']/1e6) for r in rows]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    measure(parser.parse_args().output.resolve())
