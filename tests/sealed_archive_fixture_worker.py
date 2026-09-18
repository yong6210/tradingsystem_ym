"""Fault-only subprocess for archive supervisor tests (never writes capture)."""
import gzip
import json
import struct
import sys
import time
from pathlib import Path

from app.research.data.durable_capture_log import decoded, encoded
from app.research.data.sealed_archive_worker import compress
from app.research.data.sealed_segment_handoff import sha

request = decoded(sys.stdin.buffer.read())
mode = sys.argv[1]
if mode == 'hang': time.sleep(30)
if mode == 'crash': sys.exit(71)
if mode == 'stdout':
    sys.stdout.buffer.write(b'x'*(10*1024**2)); sys.stdout.buffer.flush(); time.sleep(30)
if mode == 'stderr':
    sys.stderr.buffer.write(b'x'*65536); sys.stderr.buffer.flush(); time.sleep(30)
if mode == 'gate':
    gate = Path(sys.argv[2])
    while not gate.exists(): time.sleep(.01)
if mode == 'invalid':
    sys.stdout.buffer.write(b'bad'); sys.exit(0)
reply = compress(request)
if mode in ('wrong-job','wrong-ticket','wrong-hash','wrong-length','oversize-header','rss',
            'corrupt-gzip','wrong-raw','expansion','trailing'):
    size = struct.unpack('!I',reply[:4])[0]
    header = decoded(reply[4:4+size]); payload = reply[4+size:]
    if mode == 'wrong-job': header['job_id'] += 1
    if mode == 'wrong-ticket': header['ticket_sha256'] = '0'*64
    if mode == 'wrong-hash': header['compressed_sha256'] = '0'*64
    if mode == 'wrong-length': header['compressed_bytes'] += 1
    if mode == 'rss': header['peak_rss_bytes'] = request['rss_limit_bytes']+1
    if mode == 'corrupt-gzip': payload = payload[:-1]+bytes([payload[-1]^1])
    if mode == 'wrong-raw': payload = gzip.compress(b'wrong',mtime=0)
    if mode == 'expansion':
        row=decoded(request['certificate'])
        payload = gzip.compress(b'x'*(row['segment']['bytes']+1),mtime=0)
    if mode in ('corrupt-gzip','wrong-raw','expansion'):
        header['compressed_bytes']=len(payload); header['compressed_sha256']=sha(payload)
    h=encoded(header)
    reply=struct.pack('!I',len(h))+h+payload
    if mode == 'oversize-header': reply=struct.pack('!I',16385)+reply[4:]
    if mode == 'trailing': reply += b'extra'
sys.stdout.buffer.write(reply)
sys.stdout.buffer.flush()
