"""Start disposable API/worker for browser CI; no production or model credentials."""
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='traceforge-e2e-') as tmp:
        env={**os.environ, 'PYTHONPATH':str(root/'src'), 'TF_DATA_DIR':tmp,
             'TF_DATABASE_URL':'sqlite:///'+str(Path(tmp)/'control.db'),
             'TF_DEVELOPER_TOKEN':'e2e-only-developer-not-a-real-secret',
             'TF_REVIEWER_TOKEN':'e2e-only-reviewer-not-a-real-secret',
             'TF_WEBHOOK_SECRET':'e2e-only-webhook-not-a-real-secret'}
        subprocess.run([sys.executable,'-m','traceforge.cli','init'],cwd=root,env=env,check=True)
        commands=[[sys.executable,'-m','uvicorn','traceforge.api:app','--host','127.0.0.1','--port','8000'],
                  [sys.executable,'-m','traceforge.worker']]
        children=[]
        try:
            for command in commands:
                children.append(subprocess.Popen(command,cwd=root,env=env))
            def stop(*_): raise KeyboardInterrupt()
            signal.signal(signal.SIGTERM,stop)
            children[0].wait()
            raise SystemExit(children[0].returncode or 1)
        except KeyboardInterrupt:
            pass
        finally:
            for child in children:
                if child.poll() is None: child.terminate()
            for child in children:
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired: child.kill();child.wait()

if __name__=='__main__': main()
