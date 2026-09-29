"""Capture once, validate bytes, and stage outside the mutable workspace."""
from __future__ import annotations
import os
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from ..artifacts import canonical, digest
from ..domain import DomainError


@dataclass(frozen=True)
class ReviewedInput:
    fixture_id: str
    source: bytes
    grader: bytes

    @classmethod
    def from_bytes(cls, fixture_id: str, source: bytes) -> 'ReviewedInput':
        from ..fixtures import fixture, grader_source
        spec = fixture(fixture_id)
        if source not in {spec.original.encode('utf-8'), spec.fixed.encode('utf-8')}:
            raise DomainError('UNTRUSTED_SOURCE', 'Only reviewed fixture bytes are permitted in this execution slice')
        return cls(fixture_id, bytes(source), grader_source(fixture_id).encode('utf-8'))

    @classmethod
    def capture(cls, path: Path, fixture_id: str) -> 'ReviewedInput':
        if path.is_symlink():
            raise DomainError('UNSAFE_FIXTURE', 'Symlink source is not permitted')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        try:
            fd = os.open(path, flags)
            with os.fdopen(fd, 'rb') as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > 65536:
                    raise DomainError('UNSAFE_FIXTURE', 'Only small regular fixture source files are permitted')
                content = stream.read(65537)
                after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise DomainError('SOURCE_CHANGED', 'Source changed while capturing its bytes')
        except OSError as error:
            raise DomainError('UNSAFE_FIXTURE', 'Fixture source could not be captured safely') from error
        return cls.from_bytes(fixture_id, content)

    def validate(self) -> None:
        expected = ReviewedInput.from_bytes(self.fixture_id, self.source)
        if self.grader != expected.grader:
            raise DomainError('UNTRUSTED_GRADER', 'Only the control-plane reviewed grader may be staged')

    @property
    def manifest(self) -> dict:
        return {'schema_version':'tf-reviewed-input/v1', 'fixture_id':self.fixture_id,
                'source_sha256':digest(self.source), 'grader_sha256':digest(self.grader)}

    @property
    def fingerprint(self) -> str:
        return digest(canonical(self.manifest))

    @contextmanager
    def staged(self):
        self.validate()
        with tempfile.TemporaryDirectory(prefix='traceforge-input-') as tmp:
            path = Path(tmp)
            # Readable by the unprivileged container UID; the bind mount is read-only.
            path.chmod(0o755)
            for name, data in (('module.py', self.source), ('runner.py', self.grader),
                               ('manifest.json', canonical(self.manifest))):
                destination = path/name
                destination.write_bytes(data)
                destination.chmod(0o444)
            yield path
