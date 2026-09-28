import hashlib
import json
import os
import re
from pathlib import Path
from sqlalchemy import select
from .domain import DomainError
from .models import Artifact

def canonical(value: object) -> bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()

def digest(data: bytes) -> str: return hashlib.sha256(data).hexdigest()

class ArtifactStore:
    def __init__(self, root: Path):
        self.root=(root/"blobs").resolve(); self.root.mkdir(parents=True,exist_ok=True)
    def path(self, sha: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}",sha):
            raise DomainError("INVALID_HASH","Invalid content hash",400)
        parent=self.root/sha[:2]
        if parent.is_symlink(): raise DomainError("UNSAFE_PATH","Symlink rejected")
        target=parent/sha
        if target.is_symlink(): raise DomainError("UNSAFE_PATH","Symlink rejected")
        return target
    def put(self, session, run_id: str, kind: str, data: bytes, media_type="text/plain") -> Artifact:
        sha=digest(data); path=self.path(sha); path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():
            # Atomic write; no partially written artifact is published.
            import tempfile
            fd,name=tempfile.mkstemp(dir=path.parent,prefix=".pending-")
            try:
                with os.fdopen(fd,"wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
                os.replace(name,path)
            finally:
                if os.path.exists(name): os.unlink(name)
        if digest(path.read_bytes())!=sha: raise DomainError("ARTIFACT_TAMPERED","Artifact hash mismatch")
        old=session.scalar(select(Artifact).where(Artifact.run_id==run_id,Artifact.kind==kind,Artifact.sha256==sha))
        if old: return old
        artifact=Artifact(run_id=run_id,kind=kind,sha256=sha,media_type=media_type,byte_count=len(data))
        session.add(artifact); session.flush(); return artifact
    def read(self, artifact: Artifact) -> bytes:
        path=self.path(artifact.sha256)
        try: data=path.read_bytes()
        except OSError as e: raise DomainError("ARTIFACT_MISSING","Artifact unavailable") from e
        if digest(data)!=artifact.sha256 or len(data)!=artifact.byte_count:
            raise DomainError("ARTIFACT_TAMPERED","Artifact integrity verification failed")
        return data
