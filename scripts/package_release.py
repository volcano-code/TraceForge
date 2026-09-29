"""Build a source release, exclude credentials/state, verify every archived file.
Run from repo root. Does not upload or publish anything.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
EXCLUDED={'.git','.traceforge','.venv','node_modules','dist','__pycache__','.pytest_cache','.coverage','.DS_Store'}
def allowed(path:Path)->bool:
    parts=path.relative_to(ROOT).parts
    if any(p in EXCLUDED or p.endswith('.egg-info') for p in parts):return False
    name=path.name
    if name.startswith('.env') and name!='.env.example':return False
    if name.endswith(('.pyc','.db','.sqlite','.sqlite3','.db-wal','.db-shm')):return False
    return path.is_file() and not path.is_symlink()
def main()->None:
    output=ROOT.parent/'TraceForge-v0.3.0-M2-start.zip'
    files=sorted(p for p in ROOT.rglob('*') if allowed(p) and p.name!='MANIFEST.sha256')
    secrets=[]
    env=ROOT/'.env'
    if env.exists():
        for line in env.read_text().splitlines():
            if '=' in line:
                key,value=line.split('=',1)
                if ('TOKEN' in key or 'SECRET' in key or 'PASSWORD' in key) and len(value)>=16:secrets.append(value.encode())
    for path in files:
        content=path.read_bytes()
        if any(secret in content for secret in secrets):raise RuntimeError(f'Credential found in selected release file: {path.relative_to(ROOT)}')
    manifest='\n'.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT).as_posix()}' for p in files)+'\n'
    (ROOT/'MANIFEST.sha256').write_text(manifest)
    files.append(ROOT/'MANIFEST.sha256')
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in files:archive.write(path,'traceforge/'+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for path in files:
            assert archive.read('traceforge/'+path.relative_to(ROOT).as_posix())==path.read_bytes()
    sha=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(f'{sha}  {output.name}\n')
    print(json.dumps({'archive':str(output),'files':len(files),'bytes':output.stat().st_size,'sha256':sha,'actual_local_credentials_excluded':True,'zip_integrity':'PASS'},indent=2))
if __name__=='__main__':main()
