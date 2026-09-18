"""One pinned read-only replay proposal; no locks, journal writes or network."""
import sys
import threading

from .durable_capture_log import decoded,integer
from .incremental_audit_protocol import MAX_REQUEST,execute
from .sealed_archive_worker import peak_rss_bytes,watch_memory


def main():
    raw=sys.stdin.buffer.read(MAX_REQUEST+1)
    if len(raw)>MAX_REQUEST:raise ValueError('audit request byte bound')
    request=decoded(raw);limit=integer(request['rss_limit_bytes'],1)
    if limit>384*1024**2:raise ValueError('audit RSS bound')
    threading.Thread(target=watch_memory,args=(limit,),daemon=True).start()
    sys.stdout.buffer.write(execute(request,peak_rss_bytes));sys.stdout.buffer.flush()


if __name__=='__main__':main()
