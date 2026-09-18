"""Offline start gate only: release first audit during the second live fixture epoch."""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == '__main__':
    request, gate = sys.argv[1], Path(sys.argv[2])
    end = time.monotonic()+10
    while not gate.exists():
        if time.monotonic() >= end: raise TimeoutError('offline audit start gate')
        time.sleep(.005)
    from app.research.data.background_audit_worker import main
    sys.argv = [sys.argv[0], request]
    main()
