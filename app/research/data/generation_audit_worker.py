"""Read-only closed-prefix audit worker with parent/lifetime guardian."""
import argparse
import os
import sys
import threading
import time

from .durable_capture_log import decoded, encoded, keys
from .read_archived_generation_capture import audit_closed_prefix
from .sealed_archive_worker import peak_rss_bytes, watch_memory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent', type=int, required=True)
    parser.add_argument('--seconds', type=float, required=True)
    args = parser.parse_args()
    if args.parent <= 0 or not 0 < args.seconds <= 15: raise ValueError('guardian bounds')
    deadline = time.monotonic()+args.seconds
    def watch():
        while True:
            if os.getppid() != args.parent or time.monotonic() >= deadline: os._exit(73)
            time.sleep(.05)
    if os.getppid() != args.parent: os._exit(73)
    threading.Thread(target=watch, daemon=True).start()
    threading.Thread(target=watch_memory, args=(384*1024**2,), daemon=True).start()
    request = sys.stdin.buffer.read(65537)
    if len(request) > 65536: raise ValueError('audit request bound')
    request = decoded(request)
    keys(request, 'root plan_sha256 policy_sha256 stop_after candidate')
    result = audit_closed_prefix(**request)
    result['peak_rss_bytes'] = peak_rss_bytes()
    if result['peak_rss_bytes'] > 384*1024**2: raise MemoryError('generation audit RSS bound')
    response = encoded(result)
    if len(response) > 8*1024**2: raise ValueError('audit response bound')
    sys.stdout.buffer.write(response)


if __name__ == '__main__': main()
