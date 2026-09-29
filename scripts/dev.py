"""Start API + local outbox worker; foreground only, loopback only."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
os.chdir(root)
env={**os.environ,"PYTHONPATH":str(root/"src")}
children=[]
try:
    children.append(subprocess.Popen([sys.executable,"-m","uvicorn","traceforge.api:app","--host","127.0.0.1","--port","8000"],env=env))
    children.append(subprocess.Popen([sys.executable,"-m","traceforge.worker"],env=env))
    print("TraceForge local workbench: http://127.0.0.1:8000/workbench",flush=True)
    print("Use local reviewer token from .env. Ctrl+C stops BOTH services.",flush=True)
    while all(c.poll() is None for c in children): time.sleep(0.5)
except KeyboardInterrupt: pass
finally:
    for child in children:
        if child.poll() is None: child.terminate()
    for child in children:
        try: child.wait(timeout=5)
        except subprocess.TimeoutExpired: child.kill();child.wait()
