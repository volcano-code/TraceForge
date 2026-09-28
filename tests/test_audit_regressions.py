"""Regression gates discovered by the independent M1 audit.

These mutations model evidence producer bugs / corrupted internal references,
NOT remote authentication bypass or protection against a compromised database.
"""
import copy
import json
import pytest
from traceforge.artifacts import canonical, digest
from traceforge.domain import DomainError
from traceforge.evidence import EvidenceInspector, verify_export_integrity
from traceforge.models import Approval, Artifact, Run


def export_bundle(svc, run, approval):
    with svc.db.session() as s:
        return EvidenceInspector(svc.store).export(s, s.get(Run, run.id), s.get(Approval, approval.id))


def test_rebound_wrong_patch_cannot_reuse_passing_source_evidence(svc, complete):
    run, proposal, request = complete()
    with svc.db.transaction() as s:
        stored = s.get(Run, run.id)
        patch = s.get(Artifact, stored.data['patch_artifact_id'])
        text = svc.store.read(patch).decode().replace('min(page, pages)', 'max(page, pages)')
        assert text.encode() != svc.store.read(patch)
        replacement = svc.store.put(s, run.id, 'patch', text.encode(), 'text/x-diff')
        validation = s.get(Artifact, stored.data['validation_artifact_id'])
        report = json.loads(svc.store.read(validation))
        report['patch_hash'] = replacement.sha256
        report['artifacts'] = [dict(id=replacement.id, sha256=replacement.sha256, kind='patch') if r['kind']=='patch' else r for r in report['artifacts']]
        revised = svc.store.put(s, run.id, 'validation', canonical(report), 'application/json')
        stored.data = {**stored.data, 'patch_artifact_id':replacement.id, 'patch_hash':replacement.sha256,
                       'validation_artifact_id':revised.id, 'validation_digest':revised.sha256}
        approval = s.get(Approval, proposal.id)
        approval.patch_hash, approval.validation_digest = replacement.sha256, revised.sha256
        request = request.model_copy(update={'patch_hash':replacement.sha256, 'validation_digest':revised.sha256})
    with pytest.raises(DomainError) as caught:
        svc.decide(proposal.id, request, 'reviewer')
    assert caught.value.code == 'INVALID_EVIDENCE'


@pytest.mark.parametrize('field,value', [('patch_hash','a'*64), ('validation_digest','a'*64),
                                         ('run_id','00000000-0000-0000-0000-000000000000'), ('base_commit','a'*40)])
def test_offline_audit_binding_must_match_exported_report(svc, complete, field, value):
    run, approval, _ = complete()
    bundle = export_bundle(svc, run, approval)
    bundle['audit'][field] = value
    bundle['bundle_digest'] = digest(canonical({k:v for k,v in bundle.items() if k!='bundle_digest'}))
    with pytest.raises(DomainError) as caught:
        verify_export_integrity(bundle)
    assert caught.value.code == 'INVALID_EVIDENCE'


def test_runtime_metadata_mismatch_is_rejected(svc, complete):
    run, approval, request = complete()
    with svc.db.transaction() as s:
        s.get(Run, run.id).runtime = 'not-the-executed-runtime'
    with pytest.raises(DomainError) as caught:
        svc.decide(approval.id, request, 'reviewer')
    assert caught.value.code == 'INVALID_EVIDENCE'


def test_malformed_provider_receipt_remains_unknown(svc, complete):
    from traceforge.delivery.service import DeliveryService
    from traceforge.delivery.simulator import SQLiteDeliverySimulator
    class Provider(SQLiteDeliverySimulator):
        def submit(self, action, key):
            receipt = super().submit(action, key)
            receipt['bound_action']['base_commit'] = float('nan')
            return receipt
    run, approval, request = complete()
    svc.decide(approval.id, request.model_copy(update={'delivery_kind':'SIMULATED_PR'}), 'reviewer')
    external = Provider(svc.settings.data_dir / 'external.sqlite')
    service = DeliveryService(svc, external)
    operation = service.submit(run.id, approval.id, 'reviewer')
    assert operation.status == 'IN_DOUBT'
    assert external.metrics()['committed_actions'] == 1
    assert service.reconcile(run.id, operation.id, 'reviewer').status == 'SUCCEEDED'


def test_malformed_provider_observation_stays_unknown(svc, complete):
    from traceforge.delivery.service import DeliveryService
    from traceforge.delivery.simulator import SQLiteDeliverySimulator
    class Provider(SQLiteDeliverySimulator):
        def lookup(self, key):
            return {'state':'PRESENT'}  # Not a parsed provider-contract result.
    run, approval, request = complete()
    svc.decide(approval.id, request.model_copy(update={'delivery_kind':'SIMULATED_PR'}), 'reviewer')
    external = Provider(svc.settings.data_dir / 'external.sqlite', 'response_lost')
    service = DeliveryService(svc, external)
    operation = service.submit(run.id, approval.id, 'reviewer')
    result = service.reconcile(run.id, operation.id, 'reviewer')
    assert result.status == 'IN_DOUBT' and result.last_error == 'LOOKUP_MALFORMED'


def test_noncanonical_offline_value_is_typed_failure():
    from traceforge.evidence import verify_export_integrity
    bundle = {'schema_version':'tf-evidence-bundle/v1', 'audit': {'bogus':float('nan')},
              'artifacts':[], 'bundle_digest':'a'*64}
    with pytest.raises(DomainError) as caught:
        verify_export_integrity(bundle)
    assert caught.value.code == 'INVALID_EVIDENCE'
