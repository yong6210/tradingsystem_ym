"""Bounded-worker protocol fault fixtures. Never writes the capture root."""
from pathlib import Path
import sys
import time

from app.research.data.durable_capture_log import decoded,encoded
from app.research.data.incremental_audit_protocol import execute
from app.research.data.sealed_archive_worker import peak_rss_bytes
from app.research.data.sealed_segment_handoff import sha

request=decoded(sys.stdin.buffer.read());mode=sys.argv[1]
if mode=='hang':time.sleep(30)
if mode=='crash':sys.exit(71)
if mode=='stdout':sys.stdout.buffer.write(b'x'*(10*1024**2));sys.stdout.buffer.flush();time.sleep(30)
if mode=='stderr':sys.stderr.buffer.write(b'x'*65536);sys.stderr.buffer.flush();time.sleep(30)
if mode=='gate':
    while not Path(sys.argv[2]).exists():time.sleep(.01)
if mode=='invalid':sys.stdout.buffer.write(b'{bad');sys.exit(0)
reply=decoded(execute(request,peak_rss_bytes))
if mode=='wrong-job':reply['job_id']+=1
if mode=='wrong-request':reply['request_sha256']='0'*64
if mode=='wrong-base':reply['base_receipt']['revision']+=1
if mode=='rss':reply['peak_rss_bytes']=request['rss_limit_bytes']+1
if mode=='bad-checksum':reply['proposed_document']['state']['valid_batches']+=1
if mode in ('wrong-successor','bad-cursor','bad-state','final-state-change','raw-source-change'):
    doc=reply['proposed_document'];state=doc['state']
    if mode=='wrong-successor':doc['previous_checkpoint_sha256']='1'*64
    if mode=='bad-cursor':state['audit_cursor']['sequence']+=1
    if mode=='bad-state':state['replay']={'t':'pickle','v':[]}
    if mode=='raw-source-change':state['raw_position']['ref']['certificate']='bad'
    if mode=='final-state-change':state['valid_audit_bytes']+=1
    doc['checkpoint_sha256']=sha(encoded({k:v for k,v in doc.items() if k!='checkpoint_sha256'}))
if mode=='duplicate-key':sys.stdout.buffer.write(b'{"version":1,"version":1}');sys.exit(0)
sys.stdout.buffer.write(encoded(reply));sys.stdout.buffer.flush()
