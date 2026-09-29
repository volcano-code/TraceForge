"""Bounded POSIX subprocesses for trusted command builders.

Process groups are lifecycle control, NOT an adversarial-code sandbox.
No shell interpolation and no implicit inheritance of the parent's environment.
"""
from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence
from ..domain import DomainError


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    termination: str
    elapsed_ms: int
    observed_output_bytes: int
    truncated: bool

    def as_dict(self) -> dict:
        return asdict(self)


class BoundedProcessRunner:
    def run(self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str],
            timeout: float = 10, max_output_bytes: int = 262144,
            cancelled: Callable[[], bool] | None = None) -> ProcessResult:
        if os.name != 'posix':
            raise DomainError('PLATFORM_UNSUPPORTED', 'Bounded execution requires Linux/WSL or another POSIX host', 503)
        if not argv or any(not isinstance(x, str) or '\0' in x for x in argv):
            raise ValueError('argv must contain valid strings')
        if not 0 < timeout <= 300 or not 256 <= max_output_bytes <= 4 * 1024 * 1024:
            raise ValueError('Execution bounds are outside policy')
        started = time.monotonic()
        # Check authority BEFORE creating a process, not after its first side effect.
        if cancelled is not None:
            try:
                revoked = cancelled()
                initial_reason = 'cancelled' if revoked else None
            except Exception:
                initial_reason = 'authority_check_failed'
            if initial_reason:
                return ProcessResult(-1, '', '', initial_reason, 0, 0, False)
        try:
            proc = subprocess.Popen(list(argv), cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    shell=False, start_new_session=True, close_fds=True)
        except OSError as error:
            raise DomainError('PROCESS_START_FAILED', 'Trusted command could not start', 503) from error
        selector = selectors.DefaultSelector()
        buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        seen, stored = 0, 0
        reason: str | None = None
        stopped_at: float | None = None
        killed = False

        def kill_group(sig: int) -> None:
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                pass

        def terminate(why: str) -> None:
            nonlocal reason, stopped_at
            if reason is None:
                reason, stopped_at = why, time.monotonic()
                kill_group(signal.SIGTERM)

        try:
            for stream, name in ((proc.stdout, 'stdout'), (proc.stderr, 'stderr')):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map() or proc.poll() is None:
                current = time.monotonic()
                if current - started >= timeout:
                    terminate('timeout')
                if cancelled is not None and reason is None:
                    try:
                        if cancelled():
                            terminate('cancelled')
                    except Exception:
                        # Failure to check authority is not permission to continue.
                        terminate('authority_check_failed')
                if stopped_at is not None and current - stopped_at >= .2 and not killed:
                    kill_group(signal.SIGKILL)
                    killed = True
                if stopped_at is not None and current - stopped_at >= 1.0:
                    break  # A deliberately detached process is outside this local runner's security scope.
                for key, _ in selector.select(.025):
                    try:
                        chunk = os.read(key.fileobj.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    seen += len(chunk)
                    remaining = max(0, max_output_bytes - stored)
                    kept = chunk[:remaining]
                    buffers[key.data].extend(kept)
                    stored += len(kept)
                    if len(kept) < len(chunk):
                        terminate('output_limit')
            if proc.poll() is None:
                kill_group(signal.SIGKILL)
            proc.wait(timeout=2)
        finally:
            # Also reap/stop ordinary descendants of successfully exited commands.
            kill_group(signal.SIGKILL)
            if proc.poll() is None:
                proc.wait(timeout=2)
            selector.close()
            for stream in (proc.stdout, proc.stderr):
                if stream and not stream.closed:
                    stream.close()
        return ProcessResult(exit_code=proc.returncode,
                             stdout=buffers['stdout'].decode('utf-8', errors='replace'),
                             stderr=buffers['stderr'].decode('utf-8', errors='replace'),
                             termination=reason or 'completed', elapsed_ms=int((time.monotonic()-started)*1000),
                             observed_output_bytes=seen, truncated=seen > stored)
