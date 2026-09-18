"""Offline fault injection only. Not selectable by the production worker CLI."""
import json
from pathlib import Path
import sys
import time

from app.research.data.background_audit_worker import execute


def main():
    request, mode, release = json.loads(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    if mode.startswith('wait'):
        while not release.exists(): time.sleep(.01)
    if mode in ('wait-fail', 'crash'): sys.exit(71)
    if mode == 'hang': time.sleep(100)
    if mode == 'stdout':
        while True: sys.stdout.buffer.write(b'x'*65_536); sys.stdout.buffer.flush()
    if mode == 'stderr':
        while True: sys.stderr.buffer.write(b'x'*65_536); sys.stderr.buffer.flush()
    if mode == 'invalid':
        print('not JSON'); return
    reply = execute(request)
    if mode == 'wrong-job': reply['job_id'] += 1
    if mode == 'wrong-window': reply['result']['window_end_ns'] += 1
    if mode == 'wrong-checkpoint': reply['checkpoints']['journal'] = '0'*64
    if mode == 'memory': reply['peak_rss_bytes'] = request['rss_limit_bytes']+1
    if mode == 'bad-result': del reply['result']['intervals']
    print(json.dumps(reply))


if __name__ == '__main__': main()
