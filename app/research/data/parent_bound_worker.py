"""Read-only worker guardian: sampled parent ownership and independent lifetime.

No claim of an OS hard deadline: suspended processes cannot run this watchdog.
Targets are fixed local modules, never module names supplied by a request.
"""
import argparse
import os
import runpy
import threading
import time

TARGETS = {'archive': 'app.research.data.sealed_archive_worker',
           'audit': 'app.research.data.incremental_audit_worker'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=TARGETS)
    parser.add_argument('--parent', required=True, type=int)
    parser.add_argument('--seconds', required=True, type=float)
    args = parser.parse_args()
    if args.parent <= 0 or not 0 < args.seconds <= 15:
        raise ValueError('guardian parent/lifetime bound')
    deadline = time.monotonic()+args.seconds
    def watch():
        while True:
            if os.getppid() != args.parent or time.monotonic() >= deadline:
                os._exit(73)
            time.sleep(.05)
    if os.getppid() != args.parent:
        os._exit(73)
    threading.Thread(target=watch, daemon=True, name='parent-lifetime-guard').start()
    runpy.run_module(TARGETS[args.kind], run_name='__main__')


if __name__ == '__main__':
    main()
