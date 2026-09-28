"""One-time, hash-checked source transfer. Does not execute imported code."""
import base64
import hashlib
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import subprocess

assert os.environ.get('GITHUB_REPOSITORY') == 'volcano-code/TraceForge'
assert os.environ.get('GITHUB_REF') == 'refs/heads/fix/m2-hardening-20260929'
parts = sorted(Path('.transport').glob('part*.b64'))
assert len(parts) == 10
encoded = b''.join(p.read_bytes() for p in parts)
assert len(encoded) == 109936
compressed = base64.b64decode(encoded, validate=True)
assert hashlib.sha256(compressed).hexdigest() == '0efd86e9c6a1c29deda19ffd589fd57e80ad16592068f25df9f273025d33a280'
decoder = lzma.LZMADecompressor(memlimit=128 * 1024 * 1024)
raw = decoder.decompress(compressed, max_length=2 * 1024 * 1024)
assert decoder.eof and not decoder.unused_data
assert hashlib.sha256(raw).hexdigest() == '901c2863df645bc6dc7600e8c500d9822c81c82ea25fcd84b59e0e5333065400'
def unique(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result
        result[key] = value
    return result
files = json.loads(raw, object_pairs_hook=unique)
assert isinstance(files, dict) and len(files) == 95
for name, content in files.items():
    assert isinstance(name, str) and isinstance(content, str)
    p = PurePosixPath(name)
    assert not p.is_absolute() and p.as_posix() == name
    assert not any(x in ('..', '.', '.git', '.github', '.transport', '.env') for x in p.parts)
    assert '\\' not in name and '\x00' not in name
    target = Path(name)
    assert not any(x.is_symlink() for x in [target, *target.parents])
    assert not target.exists() or name == 'README.md', name
manifest = {}
for name, content in files.items():
    target = Path(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode('utf-8')
    target.write_bytes(data)
    manifest[name] = hashlib.sha256(target.read_bytes()).hexdigest()
Path('source-import-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
subprocess.run(['git', 'add', '-f', '--', *sorted(files), 'source-import-manifest.json'], check=True)
print(f'Imported and hashed {len(files)} files; product code was not executed.')
