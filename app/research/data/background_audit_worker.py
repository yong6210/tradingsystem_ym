"""One closed-epoch audit. No network, capture writes, or live market restoration."""
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import threading
import time

from .snapshot_feed_audit import audit_epoch


def checkpoint_hashes(directory):
    result = {}
    for name in ('journal', 'audit'):
        path = Path(directory)/name/'checkpoint.json'
        with path.open('rb') as stream:
            data = stream.read(65_537)
        if len(data) > 65_536:
            raise ValueError('oversized checkpoint')
        result[name] = hashlib.sha256(data).hexdigest()
    return result


def peak_rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == 'darwin' else value*1024


def watch_memory(limit):
    # Sampled guard, not an OS-enforced allocation ceiling. Parent also bounds
    # lifetime/output; no claim that a transient peak cannot exceed this limit.
    while True:
        if peak_rss_bytes() > limit:
            os._exit(73)
        time.sleep(.05)


def execute(request):
    directory = Path(request['directory'])
    if checkpoint_hashes(directory) != request['checkpoints']:
        raise ValueError('checkpoint changed before audit')
    result = audit_epoch(directory/'journal', directory/'audit',
                         **request['scope'], max_intervals=request['max_intervals'])
    if checkpoint_hashes(directory) != request['checkpoints']:
        raise ValueError('checkpoint changed during audit')
    return dict(job_id=request['job_id'], checkpoints=request['checkpoints'],
                result=result, peak_rss_bytes=peak_rss_bytes())


def main():
    if len(sys.argv) != 2 or len(sys.argv[1]) > 16_384:
        raise ValueError('one bounded request required')
    request = json.loads(sys.argv[1])
    threading.Thread(target=watch_memory, args=(request['rss_limit_bytes'],), daemon=True).start()
    reply = execute(request)
    if reply['peak_rss_bytes'] > request['rss_limit_bytes']:
        raise MemoryError('audit RSS limit')
    # Stream encoding avoids constructing another complete reply in the child.
    total = 0
    for chunk in json.JSONEncoder(allow_nan=False, separators=(',', ':')).iterencode(reply):
        encoded = chunk.encode()
        total += len(encoded)
        if total > request['max_reply_bytes']:
            raise ValueError('audit reply exceeds bound')
        sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()
