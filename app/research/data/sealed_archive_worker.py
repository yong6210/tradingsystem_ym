"""Read-only sealed-segment compressor; bounded stdin/stdout, no capture writes."""
import gzip
import os
from pathlib import Path
import resource
import struct
import sys
import threading
import time

from .durable_capture_log import decoded, encoded, integer, keys
from .sealed_segment_handoff import SegmentCursor, SealTicket, certificate, read_segment, sha

MAX_REQUEST = 32768
MAX_HEADER = 16384
OVERHEAD = 65536


def peak_rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == 'darwin' else value*1024


def watch_memory(limit):
    while True:
        if peak_rss_bytes() > limit: os._exit(73)
        time.sleep(.05)


def compress(request):
    keys(request, 'job_id cursor certificate rss_limit_bytes')
    integer(request['job_id'])
    limit = integer(request['rss_limit_bytes'], 1)
    if limit > 384*1024**2: raise ValueError('worker RSS policy bound')
    if type(request['certificate']) is not str: raise ValueError('ticket string required')
    ticket = SealTicket(request['certificate'].encode())
    row = certificate(ticket.certificate)
    cursor = SegmentCursor(**(request['cursor'] | dict(root=Path(request['cursor']['root']))))
    result = read_segment(ticket, cursor)
    compressed = gzip.compress(result.raw, compresslevel=1, mtime=0)
    if len(compressed) > row['segment']['bytes']+OVERHEAD:
        raise ValueError('compressed output bound')
    header = dict(version=1, job_id=request['job_id'], ticket_sha256=sha(ticket.certificate),
        compressed_bytes=len(compressed), compressed_sha256=sha(compressed), peak_rss_bytes=peak_rss_bytes())
    if header['peak_rss_bytes'] > limit: raise MemoryError('archive worker RSS bound')
    data = encoded(header)
    if len(data) > MAX_HEADER: raise ValueError('header bound')
    return struct.pack('!I', len(data))+data+compressed


def main():
    raw = sys.stdin.buffer.read(MAX_REQUEST+1)
    if len(raw) > MAX_REQUEST: raise ValueError('request size bound')
    request = decoded(raw)
    limit = integer(request['rss_limit_bytes'], 1)
    if limit > 384*1024**2: raise ValueError('worker RSS policy bound')
    threading.Thread(target=watch_memory, args=(limit,), daemon=True).start()
    sys.stdout.buffer.write(compress(request))
    sys.stdout.buffer.flush()


if __name__ == '__main__': main()
