"""One durable intent per run; no network calls under the control-plane lock.

A timeout or worker crash is not a negative acknowledgement. Reconciliation is
read-only and cannot resend. NOT_OBSERVED is not proof of absence: a delayed
request could still finish. In M1 a human must investigate that unresolved state.
"""
from __future__ import annotations
import uuid
from typing import TYPE_CHECKING
from sqlalchemy import select
from ..artifacts import canonical, digest
from ..domain import DomainError, Status, emit, transition
from ..models import Approval, Operation, Project, now
from .contracts import BoundAction, DeliveryCrash, DeliveryProvider, DefinitiveRejection, Observation
from .simulator import SQLiteDeliverySimulator

if TYPE_CHECKING:
    from ..services import Services


class DeliveryService:
    def __init__(self, services: Services, provider: DeliveryProvider | None = None):
        self.services = services
        self.provider = provider or SQLiteDeliverySimulator(services.settings.data_dir / 'provider-simulator' / 'external.sqlite')

    @staticmethod
    def _authorize(actor: str) -> None:
        if actor != 'reviewer':
            raise DomainError('FORBIDDEN', 'Reviewer role required', 403)

    def submit(self, run_id: str, approval_id: str, actor: str, *, crash_after_external_commit: bool = False) -> Operation:
        self._authorize(actor)
        svc = self.services
        with svc.db.transaction() as session:
            run = svc.get_run(session, run_id, True)
            approval = session.scalar(select(Approval).where(Approval.id == approval_id).with_for_update())
            if not approval or approval.run_id != run.id:
                raise DomainError('INVALID_APPROVAL', 'Approval is not for this run', 403)
            if approval.delivery_kind != 'SIMULATED_PR':
                raise DomainError('APPROVAL_SCOPE_MISMATCH', 'Explicit simulated-delivery approval required', 403)
            existing = session.scalar(select(Operation).where(Operation.run_id == run.id, Operation.kind == 'SIMULATED_PR'))
            if existing:
                # Read-only replay of exactly the same intent. Never call submit again.
                if existing.approval_id != approval.id:
                    raise DomainError('INTENT_CONFLICT', 'Existing operation binds a different approval')
                return existing
            if run.status != Status.APPROVED or approval.decision != 'APPROVED':
                raise DomainError('NOT_APPROVED', 'Valid human approval required', 403)
            if now() >= approval.expires_at:
                raise DomainError('APPROVAL_EXPIRED', 'Approval expired before dispatch')
            svc.check_evidence(session, run, approval)
            project = session.get(Project, run.project_id)
            action = BoundAction(repository='fixture:' + project.fixture_id, run_id=run.id,
                                 approval_id=approval.id, base_commit=run.base_commit,
                                 patch_hash=approval.patch_hash, validation_digest=approval.validation_digest)
            payload = action.model_dump()
            request_hash = digest(canonical(payload))
            key = digest(canonical({'namespace': 'tf-simulated-delivery/v1', 'action': payload}))
            intent = svc.store.put(session, run.id, 'delivery_intent', canonical(payload), 'application/json')
            token = str(uuid.uuid4())
            operation = Operation(run_id=run.id, kind='SIMULATED_PR', idempotency_key=key,
                                  status='EXECUTING', artifact_id=intent.id, approval_id=approval.id,
                                  request_hash=request_hash, request_payload=payload, lease_token=token,
                                  lease_until=now() + svc.settings.lease_seconds, generation=1, attempts=1)
            session.add(operation)
            session.flush()
            transition(session, run, Status.DELIVERING)
            emit(session, run, 'DELIVERY_DISPATCHED', {'operation_id': operation.id,
                 'request_hash': request_hash, 'mode': 'simulator', 'real_github_pr_created': False}, actor)
        # The durable intent is committed BEFORE the independently committed effect.
        try:
            receipt = self.provider.submit(action, key)
        except DefinitiveRejection:
            return self._finish(operation.id, token, 'BLOCKED', error='PROVIDER_REJECTED_NO_WRITE')
        except Exception:
            # Unknown provider exceptions may follow a completed write; don't guess.
            return self._finish(operation.id, token, 'IN_DOUBT', error='SUBMIT_OUTCOME_UNKNOWN')
        if crash_after_external_commit:
            raise DeliveryCrash('Injected crash after provider commit and before control-plane acknowledgement')
        return self._accept_receipt(operation.id, token, receipt)

    def reconcile(self, run_id: str, operation_id: str, actor: str) -> Operation:
        self._authorize(actor)
        svc = self.services
        with svc.db.transaction() as session:
            run = svc.get_run(session, run_id, True)
            operation = session.scalar(select(Operation).where(Operation.id == operation_id).with_for_update())
            if not operation or operation.run_id != run.id or operation.kind != 'SIMULATED_PR':
                raise DomainError('NOT_FOUND', 'Delivery operation not found for this run', 404)
            if operation.status in {'SUCCEEDED', 'BLOCKED'}:
                return operation
            if operation.status in {'EXECUTING', 'RECONCILING'} and operation.lease_until > now():
                return operation  # don't steal a live submit/reconcile lease
            token = str(uuid.uuid4())
            operation.status = 'RECONCILING'
            operation.lease_token = token
            operation.lease_until = now() + svc.settings.lease_seconds
            operation.generation += 1
            emit(session, run, 'RECONCILIATION_STARTED', {'operation_id': operation.id,
                 'generation': operation.generation, 'read_only': True}, actor)
            key = operation.idempotency_key
        # Deliberately no approval expiry/head checks here. This observes an OLD
        # authorized request, and never authorizes a new mutation.
        try:
            observation = self.provider.lookup(key)
        except Exception:
            return self._finish(operation_id, token, 'IN_DOUBT', error='LOOKUP_UNAVAILABLE')
        if not isinstance(observation, Observation):
            return self._finish(operation_id, token, 'IN_DOUBT', error='LOOKUP_MALFORMED')
        if observation.state == 'PRESENT' and observation.receipt is not None:
            return self._accept_receipt(operation_id, token, observation.receipt)
        reason = 'NOT_OBSERVED_IS_NOT_ABSENCE' if observation.state == 'NOT_OBSERVED' else 'LOOKUP_INCONCLUSIVE'
        return self._finish(operation_id, token, 'IN_DOUBT', error=reason)

    def _accept_receipt(self, operation_id: str, token: str, receipt: dict) -> Operation:
        with self.services.db.session() as session:
            operation = session.get(Operation, operation_id)
            try:
                canonical(receipt)  # Provider results must be finite, JSON-serializable data.
            except (ValueError, TypeError, UnicodeError):
                receipt = None
            valid = isinstance(receipt, dict) and (
                receipt.get('schema_version') == 'tf-simulator-receipt/v1'
                and receipt.get('provider') == 'independent_sqlite_simulator'
                and receipt.get('operation_key') == operation.idempotency_key
                and receipt.get('request_hash') == operation.request_hash
                and canonical(receipt.get('bound_action')) == canonical(operation.request_payload)
                and receipt.get('real_github_pr_created') is False
                and isinstance(receipt.get('external_ref'), str)
                and receipt['external_ref'].startswith('simulated-pr:')
            )
        if not valid:
            return self._finish(operation_id, token, 'IN_DOUBT', error='RECEIPT_BINDING_MISMATCH')
        return self._finish(operation_id, token, 'SUCCEEDED', receipt=receipt)

    def _finish(self, operation_id: str, token: str, target: str, *, error: str | None = None,
                receipt: dict | None = None) -> Operation:
        svc = self.services
        with svc.db.transaction() as session:
            initial = session.get(Operation, operation_id)
            if not initial:
                raise DomainError('NOT_FOUND', 'Operation not found', 404)
            run = svc.get_run(session, initial.run_id, True)
            operation = session.scalar(select(Operation).where(Operation.id == operation_id)
                                       .with_for_update().execution_options(populate_existing=True))
            if operation.lease_token != token:
                return operation  # stale worker is fenced: it cannot overwrite reconciliation
            operation.status = target
            operation.last_error = error
            operation.lease_token = None
            operation.lease_until = 0
            if target == 'SUCCEEDED':
                artifact = svc.store.put(session, run.id, 'simulated_delivery', canonical(receipt), 'application/json')
                operation.artifact_id = artifact.id
                operation.external_ref = receipt['external_ref']
                transition(session, run, Status.DELIVERED_SIMULATED)
            elif target == 'BLOCKED':
                transition(session, run, Status.DELIVERY_BLOCKED)
            elif run.status != Status.DELIVERY_IN_DOUBT:
                transition(session, run, Status.DELIVERY_IN_DOUBT)
            emit(session, run, 'DELIVERY_' + target, {'operation_id': operation.id,
                 'error_code': error, 'external_ref': operation.external_ref,
                 'real_github_pr_created': False}, 'delivery-service')
            return operation
