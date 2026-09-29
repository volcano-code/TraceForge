import copy
import json
import pytest
from sqlalchemy import select
from traceforge.artifacts import canonical, digest
from traceforge.domain import DomainError
from traceforge.evidence import EvidenceInspector, verify_export_integrity
from traceforge.models import Approval, Artifact, Run


def test_complete_evidence_export_and_offline_integrity(svc, complete):
    run, approval, _ = complete()
    inspector = EvidenceInspector(svc.store)
    with svc.db.session() as session:
        bundle = inspector.export(session, session.get(Run, run.id), session.get(Approval, approval.id))
    assert bundle['audit']['integrity_and_fixture_policy_passed'] is True
    assert bundle['audit']['independent_tests_rerun_by_this_endpoint'] is False
    result = verify_export_integrity(bundle)
    assert result == {'integrity_passed': True, 'authenticity_proven': False, 'tests_rerun': False,
                      'run_id': run.id, 'bundle_digest': bundle['bundle_digest'], 'artifact_count': 4}
    changed = copy.deepcopy(bundle)
    changed['artifacts'][0]['content'] += '\n# tampered'
    with pytest.raises(DomainError): verify_export_integrity(changed)
    payload = {k: v for k, v in changed.items() if k != 'bundle_digest'}
    changed['bundle_digest'] = digest(canonical(payload))
    with pytest.raises(DomainError): verify_export_integrity(changed)


@pytest.mark.parametrize('mutation', ['empty_refs', 'duplicate_refs', 'wrong_run', 'wrong_fixture',
    'wrong_environment', 'fewer_tests', 'embedded_mismatch', 'bool_verified', 'unsupported_schema'])
def test_semantically_invalid_report_cannot_authorize(svc, complete, mutation):
    run, approval, request = complete()
    # Simulates a self-consistent hashed but semantically invalid report. We
    # update its approval digest too so the test exercises semantics, not merely hashing.
    with svc.db.transaction() as session:
        stored = session.get(Run, run.id)
        old = session.get(Artifact, stored.data['validation_artifact_id'])
        report = json.loads(svc.store.read(old))
        if mutation == 'empty_refs': report['artifacts'] = []
        if mutation == 'duplicate_refs': report['artifacts'][1] = report['artifacts'][0]
        if mutation == 'wrong_run': report['run_id'] = 'different-run'
        if mutation == 'wrong_fixture': report['fixture_id'] = 'empty-mean'
        if mutation == 'wrong_environment': report['environment']['python'] = 'forged'
        if mutation == 'fewer_tests': report['after']['tests_run'] = 0
        if mutation == 'embedded_mismatch': report['before']['failures'] = []
        if mutation == 'bool_verified': report['verified'] = 1
        if mutation == 'unsupported_schema': report['schema_version'] = '999'
        new = svc.store.put(session, stored.id, 'validation', canonical(report), 'application/json')
        stored.data = {**stored.data, 'validation_artifact_id': new.id, 'validation_digest': new.sha256}
        session.get(Approval, approval.id).validation_digest = new.sha256
        request = request.model_copy(update={'validation_digest': new.sha256})
    with pytest.raises(DomainError) as caught: svc.decide(approval.id, request, 'reviewer')
    assert caught.value.code == 'INVALID_EVIDENCE'


def test_cross_run_artifact_rejected_even_if_hash_matches(svc, complete):
    one, approval, request = complete()
    two, _, _ = complete()
    with svc.db.transaction() as session:
        stored = session.get(Run, one.id)
        stored.data = {**stored.data, 'patch_artifact_id': two.data['patch_artifact_id']}
    with pytest.raises(DomainError) as caught: svc.decide(approval.id, request, 'reviewer')
    assert caught.value.code == 'INVALID_EVIDENCE'


def test_export_before_verification_fails_closed(client, headers, new_run):
    run = new_run()
    response = client.get(f'/api/v1/runs/{run.id}/evidence/export', headers=headers)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'MISSING_EVIDENCE'


def test_evidence_api_auth_and_export(client, headers, complete):
    run, _, _ = complete()
    path = f'/api/v1/runs/{run.id}/evidence'
    assert client.get(path).status_code == 401
    audit = client.get(path, headers=headers)
    assert audit.status_code == 200
    assert {'patch_to_source_binding', 'runtime_binding'} <= set(audit.json()['checks'])
    export = client.get(path + '/export', headers=headers)
    assert export.status_code == 200
    assert export.headers['content-disposition'].startswith('attachment;')
    assert verify_export_integrity(export.json())['integrity_passed']
