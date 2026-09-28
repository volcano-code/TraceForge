import difflib
import hashlib
import json
import pytest
from traceforge.artifacts import canonical
from traceforge.domain import DomainError
from traceforge.fixtures import FIXTURES
from traceforge.models import Approval, Artifact, Run
from traceforge.patches import verify_reviewed_patch


def blob(text):
    data = text.encode()
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data, usedforsecurity=False).hexdigest()[:7]


def patch_for(spec):
    header = f'diff --git a/module.py b/module.py\nindex {blob(spec.original)}..{blob(spec.fixed)} 100644\n'
    diff = ''.join(difflib.unified_diff(spec.original.splitlines(True), spec.fixed.splitlines(True),
                                     fromfile='a/module.py', tofile='b/module.py'))
    return (header + diff).encode()


@pytest.mark.parametrize('fid', sorted(FIXTURES))
def test_reviewed_patch_binds_each_fixture_without_executing(fid):
    spec = FIXTURES[fid]
    verify_reviewed_patch(patch_for(spec), spec.original.encode(), spec.fixed.encode())


@pytest.mark.parametrize('mutation', ['extra_file','mode','rename','index','context','hunk_count','binary','empty','huge','utf8'])
def test_patch_language_is_fail_closed(mutation):
    spec = FIXTURES['pagination']
    patch = patch_for(spec)
    if mutation == 'extra_file': patch += b'diff --git a/other.py b/other.py\n'
    if mutation == 'mode': patch = patch.replace(b'100644', b'100755')
    if mutation == 'rename': patch = patch.replace(b'b/module.py', b'b/other.py')
    if mutation == 'index': patch = patch.replace(blob(spec.fixed).encode(), b'0000000')
    if mutation == 'context': patch = patch.replace(b'    start =', b'    bogus =')
    if mutation == 'hunk_count': patch = patch.replace(b'@@ -', b'@@ -999')
    if mutation == 'binary': patch = b'GIT binary patch\n'
    if mutation == 'empty': patch = b''
    if mutation == 'huge': patch = b' ' * 65537
    if mutation == 'utf8': patch = b'\xff\n'
    with pytest.raises(DomainError) as caught:
        verify_reviewed_patch(patch, spec.original.encode(), spec.fixed.encode())
    assert caught.value.code == 'INVALID_EVIDENCE'


def test_legacy_v2_report_is_reaudited_without_rewriting_prior_bytes(svc, complete):
    run, approval, request = complete('slug-space')
    with svc.db.transaction() as s:
        stored = s.get(Run, run.id)
        original = s.get(Artifact, stored.data['validation_artifact_id'])
        prior_bytes = svc.store.read(original)
        report = json.loads(prior_bytes)
        report['validator_policy_version'] = 'reviewed-fixture-integrity-v2'
        revised = svc.store.put(s, run.id, 'validation', canonical(report), 'application/json')
        stored.data = {**stored.data, 'validation_artifact_id': revised.id, 'validation_digest': revised.sha256}
        s.get(Approval, approval.id).validation_digest = revised.sha256
        request = request.model_copy(update={'validation_digest':revised.sha256})
    assert svc.decide(approval.id, request, 'reviewer').decision == 'APPROVED'
    assert svc.store.read(original) == prior_bytes
