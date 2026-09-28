"""Pure-data verification of the tiny, reviewed fixture patch format.

This is deliberately NOT a general Git patch parser. Binary patches, renames,
mode changes, extra files and no-newline markers are rejected. No candidate
code is imported or executed. Production repositories need a sandboxed Git
apply plus independently pinned verification, not this fixture-only policy.
"""
from __future__ import annotations

import hashlib
import re
from .domain import DomainError


def _invalid() -> None:
    raise DomainError('INVALID_EVIDENCE', 'Patch does not bind the reviewed before/after source bytes')


def _blob_id(content: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content,
                        usedforsecurity=False).hexdigest()


def verify_reviewed_patch(patch: bytes, original: bytes, fixed: bytes) -> None:
    """Require a valid module.py text diff which produces exactly ``fixed``."""
    if not patch or len(patch) > 65536:
        _invalid()
    try:
        lines = patch.decode('utf-8').splitlines(keepends=True)
        source = original.decode('utf-8').splitlines(keepends=True)
        if len(lines) < 6 or any(not line.endswith('\n') for line in lines):
            _invalid()
        if lines[0] != 'diff --git a/module.py b/module.py\n':
            _invalid()
        index = re.fullmatch(r'index ([a-f0-9]{7,40})\.\.([a-f0-9]{7,40}) 100644\n', lines[1])
        if not index or not _blob_id(original).startswith(index[1]) or not _blob_id(fixed).startswith(index[2]):
            _invalid()
        if lines[2:4] != ['--- a/module.py\n', '+++ b/module.py\n']:
            _invalid()
        cursor, i, hunks = 0, 4, 0
        output: list[str] = []
        while i < len(lines):
            match = re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n', lines[i])
            if not match:
                _invalid()
            old_start, old_count = int(match[1]), int(match[2] or '1')
            new_start, new_count = int(match[3]), int(match[4] or '1')
            old_index = old_start - 1 if old_count else old_start
            new_index = new_start - 1 if new_count else new_start
            if old_index < cursor or old_index > len(source):
                _invalid()
            output.extend(source[cursor:old_index])
            cursor = old_index
            if new_index != len(output):
                _invalid()
            removed, added = 0, 0
            i += 1
            while i < len(lines) and not lines[i].startswith('@@ '):
                marker, text = lines[i][0], lines[i][1:]
                if marker not in {' ', '+', '-'}:
                    _invalid()
                if marker in {' ', '-'}:
                    if cursor >= len(source) or source[cursor] != text:
                        _invalid()
                    cursor += 1
                    removed += 1
                if marker in {' ', '+'}:
                    output.append(text)
                    added += 1
                i += 1
            if removed != old_count or added != new_count:
                _invalid()
            hunks += 1
        output.extend(source[cursor:])
        if hunks == 0 or ''.join(output).encode('utf-8') != fixed:
            _invalid()
    except (UnicodeError, ValueError, IndexError):
        _invalid()
