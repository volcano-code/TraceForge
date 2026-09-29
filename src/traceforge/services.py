from __future__ import annotations
import json
import platform
from sqlalchemy import select
from . import __version__
from .artifacts import ArtifactStore, canonical, digest
from .config import Settings
from .db import Database
from .domain import ApprovalDecision, DomainError, RunCreate, Status, emit, transition
from .fixtures import FIXTURES, WorkspaceManager
from .models import Approval, Artifact, Operation, Outbox, Project, Run, now

class Services:
    def __init__(self,settings: Settings,db: Database):
        self.settings,self.db=settings,db
        self.store=ArtifactStore(settings.data_dir)
        from .execution.readiness import make_backend
        self.workspaces=WorkspaceManager(settings.data_dir,test_backend=make_backend(settings))
    def seed(self) -> None:
        for fid,spec in FIXTURES.items():
            commit=self.workspaces.seed(fid)
            with self.db.transaction() as s:
                if not s.scalar(select(Project).where(Project.fixture_id==fid)):
                    s.add(Project(name=spec.title,fixture_id=fid,base_commit=commit))
    def get_run(self,s,run_id: str,lock: bool=False) -> Run:
        stmt=select(Run).where(Run.id==run_id)
        if lock: stmt=stmt.with_for_update().execution_options(populate_existing=True)
        run=s.scalar(stmt)
        if not run: raise DomainError("NOT_FOUND","Run not found",404)
        return run
    def create_run(self,request: RunCreate,key: str) -> Run:
        if not 8<=len(key)<=128: raise DomainError("BAD_IDEMPOTENCY_KEY","Use an 8-128 character Idempotency-Key",400)
        request_hash=digest(canonical(request.model_dump()))
        # A read-only replay must not contact an unavailable execution backend.
        with self.db.session() as read_session:
            existing=read_session.scalar(select(Run).where(Run.request_key==key))
            if existing:
                if existing.request_hash!=request_hash:
                    raise DomainError("IDEMPOTENCY_CONFLICT","Same key with different payload")
                return existing
        self.workspaces.test_backend.preflight() # No database write lock while inspecting a runtime.
        with self.db.transaction() as s:
            # Serialize the same project on PostgreSQL before the insert/replay check.
            project=s.scalar(select(Project).where(Project.id==request.project_id).with_for_update())
            if not project: raise DomainError("NOT_FOUND","Project not found",404)
            existing=s.scalar(select(Run).where(Run.request_key==key))
            if existing:
                if existing.request_hash!=request_hash: raise DomainError("IDEMPOTENCY_CONFLICT","Same key with different payload")
                return existing
            run=Run(project_id=project.id,objective=request.objective,base_commit=project.base_commit,
                    request_key=key,request_hash=request_hash,data={"execution_backend":self.settings.execution_backend,"execution_contract":"tf-reviewed-input/v1"},event_seq=0,version=1,status="QUEUED")
            s.add(run); s.flush()
            emit(s,run,"RUN_CREATED",{"runtime":"fixture","model_calls":0,"synthetic_fixture":True})
            s.add(Outbox(run_id=run.id))
            return run
    def cancel(self,run_id: str) -> Run:
        with self.db.transaction() as s:
            run=self.get_run(s,run_id,True)
            if run.status==Status.CANCELLED: return run
            if run.status in {Status.DELIVERING,Status.DELIVERY_IN_DOUBT}:
                raise DomainError("DELIVERY_UNRESOLVED","Reconcile the external operation before any further action")
            transition(s,run,Status.CANCELLED)
            job=s.scalar(select(Outbox).where(Outbox.run_id==run.id).with_for_update())
            if job: job.status="DONE";job.lease_token=None
            return run
    def check_evidence(self,s,run: Run,approval: Approval) -> None:
        project=s.get(Project,run.project_id)
        if not project or project.base_commit!=run.base_commit:
            raise DomainError("BASE_CHANGED","Base version changed; create a new verified run")
        self.workspaces.assert_head(project.fixture_id,run.base_commit)
        if approval.base_commit!=run.base_commit: raise DomainError("STALE_APPROVAL","Approval base does not match")
        from .evidence import EvidenceInspector
        EvidenceInspector(self.store).inspect(s,run,approval)
    def decide(self,approval_id: str,request: ApprovalDecision,actor: str) -> Approval:
        if actor!="reviewer": raise DomainError("FORBIDDEN","Reviewer role required",403)
        with self.db.transaction() as s:
            proposal=s.get(Approval,approval_id)
            if not proposal: raise DomainError("NOT_FOUND","Approval not found",404)
            run=self.get_run(s,proposal.run_id,True)
            approval=s.scalar(select(Approval).where(Approval.id==approval_id).with_for_update().execution_options(populate_existing=True))
            expected=(approval.base_commit,approval.patch_hash,approval.validation_digest)
            if (request.base_commit,request.patch_hash,request.validation_digest)!=expected:
                raise DomainError("STALE_APPROVAL","Approval must bind the displayed base, patch and report")
            if approval.decision!="PENDING":
                if approval.decision==request.decision:
                    if approval.delivery_kind!=request.delivery_kind:
                        raise DomainError("APPROVAL_SCOPE_MISMATCH","An approval cannot be reused for a different delivery action")
                    return approval
                raise DomainError("DECISION_FINAL","An approval decision cannot be reversed")
            if now()>=approval.expires_at: raise DomainError("APPROVAL_EXPIRED","Approval expired; create a new run")
            if run.status!=Status.WAITING_APPROVAL:
                raise DomainError("INVALID_STATE","Run is not waiting for approval")
            if request.decision=="APPROVED": self.check_evidence(s,run,approval)
            approval.decision=request.decision;approval.delivery_kind=request.delivery_kind
            approval.decided_by=actor;approval.decided_at=now()
            approval.comment=request.comment
            transition(s,run,Status(request.decision))
            emit(s,run,"APPROVAL_DECIDED",{"approval_id":approval.id,"decision":request.decision,"delivery_kind":request.delivery_kind},actor)
            return approval
    def deliver_local(self,run_id: str,approval_id: str,actor: str) -> Operation:
        if actor!="reviewer": raise DomainError("FORBIDDEN","Reviewer role required",403)
        with self.db.transaction() as s:
            run=self.get_run(s,run_id,True)
            approval=s.get(Approval,approval_id)
            if not approval or approval.run_id!=run.id: raise DomainError("INVALID_APPROVAL","Approval is not for this run",403)
            if approval.delivery_kind!="LOCAL_RECEIPT":
                raise DomainError("APPROVAL_SCOPE_MISMATCH","This approval does not authorize a local receipt",403)
            existing=s.scalar(select(Operation).where(Operation.run_id==run.id,Operation.kind=="LOCAL_RECEIPT"))
            if existing: return existing # read-only idempotent replay; no new side effect
            if approval.decision!="APPROVED" or run.status!=Status.APPROVED:
                raise DomainError("NOT_APPROVED","Valid human approval required",403)
            if now()>=approval.expires_at: raise DomainError("APPROVAL_EXPIRED","Approval expired before delivery")
            self.check_evidence(s,run,approval)
            key=digest(canonical({"run_id":run.id,"kind":"LOCAL_RECEIPT","base":run.base_commit,
                                  "patch":approval.patch_hash,"validation":approval.validation_digest}))
            receipt={"mode":"local_dry_run","real_github_pr_created":False,"external_url":None,
                     "operation_key":key,"run_id":run.id,"approval_id":approval.id,
                     "base_commit":run.base_commit,"patch_hash":approval.patch_hash,
                     "validation_digest":approval.validation_digest,"approved_by":actor}
            artifact=self.store.put(s,run.id,"delivery",canonical(receipt),"application/json")
            operation=Operation(run_id=run.id,kind="LOCAL_RECEIPT",idempotency_key=key,status="SUCCEEDED",artifact_id=artifact.id)
            s.add(operation);s.flush()
            transition(s,run,Status.DELIVERED_LOCAL)
            emit(s,run,"LOCAL_RECEIPT_CREATED",{"operation_id":operation.id,"real_pr":False},actor)
            return operation
