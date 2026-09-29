import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from traceforge.delivery.contracts import DeliveryCrash, Observation
from traceforge.delivery.service import DeliveryService
from traceforge.delivery.simulator import SQLiteDeliverySimulator
from traceforge.domain import DomainError
from traceforge.models import Approval, Operation, Run, now
from traceforge.services import Services


def provider(svc, fault='none'):
    return SQLiteDeliverySimulator(svc.settings.data_dir / 'provider-simulator' / 'external.sqlite', fault)


def approve(svc, complete):
    run, proposal, request = complete()
    svc.decide(proposal.id, request.model_copy(update={'delivery_kind':'SIMULATED_PR'}), 'reviewer')
    return run, proposal


def expire_lease(svc, operation_id):
    with svc.db.transaction() as session:
        session.get(Operation, operation_id).lease_until = now() - 1


def op_for(svc, run):
    with svc.db.session() as session:
        return session.scalar(select(Operation).where(Operation.run_id == run.id))


def test_normal_delivery_and_duplicate_submit_are_idempotent(svc, complete):
    run, proposal = approve(svc, complete)
    external = provider(svc)
    service = DeliveryService(svc, external)
    first = service.submit(run.id, proposal.id, 'reviewer')
    again = service.submit(run.id, proposal.id, 'reviewer')
    assert first.id == again.id and first.status == 'SUCCEEDED'
    assert first.external_ref.startswith('simulated-pr:')
    assert external.metrics() == {'submit_invocations': 1, 'committed_actions': 1}
    assert service.reconcile(run.id, first.id, 'reviewer').id == first.id
    with svc.db.session() as session:
        assert session.get(Run, run.id).status == 'DELIVERED_SIMULATED'


def test_lost_response_reconcile_after_services_restart(svc, complete):
    run, proposal = approve(svc, complete)
    external = provider(svc, 'response_lost')
    op = DeliveryService(svc, external).submit(run.id, proposal.id, 'reviewer')
    assert op.status == 'IN_DOUBT'
    assert external.metrics()['committed_actions'] == 1
    restarted = DeliveryService(Services(svc.settings, svc.db), provider(svc))
    assert restarted.submit(run.id, proposal.id, 'reviewer').status == 'IN_DOUBT'
    resolved = restarted.reconcile(run.id, op.id, 'reviewer')
    assert resolved.status == 'SUCCEEDED'
    assert external.metrics() == {'submit_invocations': 1, 'committed_actions': 1}


def test_crash_after_external_commit_recovers_after_lease(svc, complete):
    run, proposal = approve(svc, complete)
    external = provider(svc)
    service = DeliveryService(svc, external)
    with pytest.raises(DeliveryCrash):
        service.submit(run.id, proposal.id, 'reviewer', crash_after_external_commit=True)
    op = op_for(svc, run)
    assert op.status == 'EXECUTING' and external.metrics()['committed_actions'] == 1
    assert service.reconcile(run.id, op.id, 'reviewer').status == 'EXECUTING'
    expire_lease(svc, op.id)
    assert DeliveryService(svc, provider(svc)).reconcile(run.id, op.id, 'reviewer').status == 'SUCCEEDED'
    assert external.metrics()['submit_invocations'] == 1


def test_not_observed_never_authorizes_resubmission(svc, complete):
    run, proposal = approve(svc, complete)
    external = provider(svc, 'request_not_observed')
    service = DeliveryService(svc, external)
    op = service.submit(run.id, proposal.id, 'reviewer')
    for _ in range(3):
        result = service.reconcile(run.id, op.id, 'reviewer')
        assert result.status == 'IN_DOUBT'
        assert result.last_error == 'NOT_OBSERVED_IS_NOT_ABSENCE'
        assert service.submit(run.id, proposal.id, 'reviewer').id == op.id
    assert external.metrics() == {'submit_invocations': 1, 'committed_actions': 0}


def test_lookup_unknown_is_not_failure_or_success(svc, complete):
    run, proposal = approve(svc, complete)
    op = DeliveryService(svc, provider(svc, 'response_lost')).submit(run.id, proposal.id, 'reviewer')
    result = DeliveryService(svc, provider(svc, 'lookup_unknown')).reconcile(run.id, op.id, 'reviewer')
    assert result.status == 'IN_DOUBT' and result.last_error == 'LOOKUP_INCONCLUSIVE'


def test_wrong_receipt_binding_requires_reconciliation(svc, complete):
    run, proposal = approve(svc, complete)
    service = DeliveryService(svc, provider(svc, 'receipt_mismatch'))
    op = service.submit(run.id, proposal.id, 'reviewer')
    assert op.status == 'IN_DOUBT' and op.last_error == 'RECEIPT_BINDING_MISMATCH'
    assert service.reconcile(run.id, op.id, 'reviewer').status == 'SUCCEEDED'


def test_external_base_changed_blocks_without_mutation(svc, complete):
    run, proposal = approve(svc, complete)
    external = provider(svc)
    external.set_head('fixture:pagination', 'f' * 40)
    op = DeliveryService(svc, external).submit(run.id, proposal.id, 'reviewer')
    assert op.status == 'BLOCKED' and external.metrics()['committed_actions'] == 0
    with svc.db.session() as session:
        assert session.get(Run, run.id).status == 'DELIVERY_BLOCKED'


def test_expired_approval_stops_new_dispatch_not_read_only_reconciliation(svc, complete):
    run, proposal = approve(svc, complete)
    service = DeliveryService(svc, provider(svc, 'response_lost'))
    op = service.submit(run.id, proposal.id, 'reviewer')
    with svc.db.transaction() as session:
        session.get(Approval, proposal.id).expires_at = now() - 1
    assert service.reconcile(run.id, op.id, 'reviewer').status == 'SUCCEEDED'


def test_expired_approval_before_dispatch_has_no_intent_or_effect(svc, complete):
    run, proposal = approve(svc, complete)
    with svc.db.transaction() as session: session.get(Approval, proposal.id).expires_at = now() - 1
    external = provider(svc)
    with pytest.raises(DomainError) as caught: DeliveryService(svc, external).submit(run.id, proposal.id, 'reviewer')
    assert caught.value.code == 'APPROVAL_EXPIRED'
    assert op_for(svc, run) is None and external.metrics()['committed_actions'] == 0


def test_cancel_unknown_delivery_is_rejected(svc, complete):
    run, proposal = approve(svc, complete)
    DeliveryService(svc, provider(svc, 'response_lost')).submit(run.id, proposal.id, 'reviewer')
    with pytest.raises(DomainError) as caught: svc.cancel(run.id)
    assert caught.value.code == 'DELIVERY_UNRESOLVED'


def test_concurrent_submits_make_one_external_request(svc, complete):
    run, proposal = approve(svc, complete)
    external = provider(svc)
    service = DeliveryService(svc, external)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.submit(run.id, proposal.id, 'reviewer'), range(4)))
    assert len({r.id for r in results}) == 1
    assert external.metrics() == {'submit_invocations': 1, 'committed_actions': 1}


def test_stale_response_is_fenced_after_reconcile(svc, complete):
    run, proposal = approve(svc, complete)
    service = DeliveryService(svc, provider(svc))
    with pytest.raises(DeliveryCrash): service.submit(run.id, proposal.id, 'reviewer', crash_after_external_commit=True)
    old = op_for(svc, run)
    expire_lease(svc, old.id)
    assert service.reconcile(run.id, old.id, 'reviewer').status == 'SUCCEEDED'
    assert service._finish(old.id, old.lease_token, 'IN_DOUBT', error='STALE_WORKER').status == 'SUCCEEDED'


def test_cross_run_and_developer_reconciliation_rejected(svc, complete):
    run, proposal = approve(svc, complete)
    service = DeliveryService(svc, provider(svc, 'response_lost'))
    op = service.submit(run.id, proposal.id, 'reviewer')
    other, _, _ = complete('empty-mean')
    with pytest.raises(DomainError) as caught: service.reconcile(other.id, op.id, 'reviewer')
    assert caught.value.status == 404
    with pytest.raises(DomainError) as caught: service.reconcile(run.id, op.id, 'developer')
    assert caught.value.status == 403


def test_delivery_api(client, headers, complete, svc):
    run, proposal = approve(svc, complete)
    path = f'/api/v1/runs/{run.id}'
    response = client.post(path + '/deliveries/simulated', headers=headers, json={'approval_id': proposal.id})
    assert response.status_code == 200 and response.json()['status'] == 'SUCCEEDED'
    op = response.json()
    assert client.get(path + '/operations', headers=headers).json()['items'][0]['id'] == op['id']
    assert client.post(path + f'/operations/{op["id"]}/reconcile', headers=headers).json()['id'] == op['id']
    assert client.post(path + '/deliveries/pr', headers=headers, json={'approval_id': proposal.id}).status_code == 503


def test_approval_action_scope_cannot_be_changed_or_reused(svc, complete):
    run, proposal, request = complete()
    svc.decide(proposal.id, request, 'reviewer')
    service = DeliveryService(svc, provider(svc))
    with pytest.raises(DomainError) as caught: service.submit(run.id, proposal.id, 'reviewer')
    assert caught.value.code == 'APPROVAL_SCOPE_MISMATCH'
    with pytest.raises(DomainError) as caught:
        svc.decide(proposal.id, request.model_copy(update={'delivery_kind':'SIMULATED_PR'}), 'reviewer')
    assert caught.value.code == 'APPROVAL_SCOPE_MISMATCH'
    assert op_for(svc, run) is None


def test_simulator_approval_cannot_be_used_for_local_delivery(svc, complete):
    run, proposal = approve(svc, complete)
    with pytest.raises(DomainError) as caught: svc.deliver_local(run.id, proposal.id, 'reviewer')
    assert caught.value.code == 'APPROVAL_SCOPE_MISMATCH'
