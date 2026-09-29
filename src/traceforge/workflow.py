from __future__ import annotations
import json
import platform
import uuid
from sqlalchemy import and_, or_, select
from . import __version__
from .artifacts import canonical, digest
from .domain import DomainError, EXECUTION_STEPS, STOP_STATES, Status, emit, transition
from .fixtures import FixtureExecutor, fixture, git
from .evidence import POLICY_VERSION
from .models import Approval, Artifact, Outbox, Project, Run, now
from .security import sanitize
from .services import Services

class SimulatedCrash(BaseException):
    """Only injected by tests, after a committed checkpoint."""

class Worker:
    def __init__(self,services: Services): self.services=services
    @staticmethod
    def _eligible():
        return or_(Outbox.status=="PENDING", and_(Outbox.status=="CLAIMED", Outbox.lease_until<now()))

    def _locked_pair(self, session, job_id):
        # All mutations use Run -> Outbox ordering, including cancel().
        # The initial read discovers the run ID but does not authorize execution.
        initial=session.get(Outbox,job_id)
        if not initial: return None,None
        run=self.services.get_run(session,initial.run_id,True)
        job=session.scalar(select(Outbox).where(Outbox.id==job_id).with_for_update()
                           .execution_options(populate_existing=True))
        return run,job

    def claim(self) -> tuple[str,str] | None:
        with self.services.db.transaction() as s:
            candidates=s.execute(select(Outbox.id,Outbox.run_id).where(self._eligible())
                                 .order_by(Outbox.created_at,Outbox.id).limit(32)).all()
            for job_id,run_id in candidates:
                run=s.scalar(select(Run).where(Run.id==run_id).with_for_update(skip_locked=True)
                             .execution_options(populate_existing=True))
                if not run: continue
                job=s.scalar(select(Outbox).where(Outbox.id==job_id,self._eligible())
                             .with_for_update(skip_locked=True).execution_options(populate_existing=True))
                if not job: continue
                if run.status in STOP_STATES:
                    job.status="DONE";job.lease_token=None;return job.id,""
                if job.attempts>=3:
                    run.failure_code="RETRY_EXHAUSTED";transition(s,run,Status.FAILED)
                    job.status="DONE";job.lease_token=None;return job.id,""
                token=str(uuid.uuid4());job.status="CLAIMED";job.lease_token=token
                job.lease_until=now()+self.services.settings.lease_seconds;job.attempts+=1
                emit(s,run,"WORKER_CLAIMED",{"attempt":job.attempts,"resumed":job.attempts>1})
                return job.id,token
            return None
    def execute_one(self,crash_after: str | None=None) -> bool:
        claimed=self.claim()
        if not claimed: return False
        job_id,token=claimed
        if not token: return True
        try:
            while True:
                with self.services.db.transaction() as s:
                    run,job=self._locked_pair(s,job_id)
                    if not job or job.lease_token!=token or job.lease_until<=now(): return True
                    if run.status in STOP_STATES:
                        job.status="DONE";job.lease_token=None;return True
                    job.lease_until=now()+self.services.settings.lease_seconds
                    project=s.get(Project,run.project_id)
                    snapshot={"id":run.id,"fixture_id":project.fixture_id,"base_commit":run.base_commit,
                              "status":run.status,"data":dict(run.data),"job_id":job.id,"lease_token":token}
                # No database write lock while running any subprocess.
                target,updates,artifacts,verified=self.step(snapshot)
                with self.services.db.transaction() as s:
                    run,job=self._locked_pair(s,job_id)
                    if not job or job.lease_token!=token or job.lease_until<=now(): return True
                    if run.status!=snapshot["status"]: return True # cancellation / fencing
                    data={**run.data,**updates}
                    for kind,content,media in artifacts:
                        artifact=self.services.store.put(s,run.id,kind,content,media)
                        data[kind+"_artifact_id"]=artifact.id
                        emit(s,run,"ARTIFACT_AVAILABLE",{"id":artifact.id,"kind":kind,"sha256":artifact.sha256})
                    run.data=data
                    if verified:
                        patch=s.get(Artifact,run.data["patch_artifact_id"])
                        before=s.get(Artifact,run.data["reproduction_artifact_id"])
                        after=s.get(Artifact,run.data["regression_artifact_id"])
                        spec=fixture(snapshot["fixture_id"])
                        bundle={"schema_version":"2","runtime":"fixture","synthetic_fixture":True,
                          "run_id":run.id,"fixture_id":spec.id,"objective":run.objective,
                          "base_commit":run.base_commit,"patch_hash":patch.sha256,
                          "verified":True,"before":run.data["before"],"after":run.data["after"],
                          "model_calls":0,"model_cost":0,"grader_visibility":"public_reviewed_fixture",
                          "trust_scope":"Infrastructure demonstration only; not an agent benchmark or hostile-code sandbox",
                          "environment":{"python":platform.python_version(),"platform":platform.system(),
                            "traceforge_version":__version__,"executor":run.data["after"]["execution_mode"],
                            "execution_environment":run.data["after"].get("execution_environment",{})},
                          "artifacts":[{"id":a.id,"sha256":a.sha256,"kind":a.kind} for a in (patch,before,after)]}
                        bundle["environment_fingerprint"]=digest(canonical(bundle["environment"]))
                        bundle["validator_policy_version"]=POLICY_VERSION
                        report=self.services.store.put(s,run.id,"validation",canonical(bundle),"application/json")
                        run.data={**run.data,"validation_artifact_id":report.id,"patch_hash":patch.sha256,
                                  "validation_digest":report.sha256}
                        approval=Approval(run_id=run.id,base_commit=run.base_commit,patch_hash=patch.sha256,
                            validation_digest=report.sha256,expires_at=now()+self.services.settings.approval_ttl_seconds)
                        s.add(approval);s.flush()
                        emit(s,run,"APPROVAL_REQUIRED",{"approval_id":approval.id,"expires_at":approval.expires_at})
                    transition(s,run,target)
                    if target==Status.WAITING_APPROVAL:
                        job.status="DONE";job.lease_token=None
                if crash_after==target.value: raise SimulatedCrash(target.value)
        except Exception as error:
            with self.services.db.transaction() as s:
                run,job=self._locked_pair(s,job_id)
                if job and job.lease_token==token and job.lease_until>now():
                    if run.status not in STOP_STATES:
                        run.failure_code=error.code if isinstance(error,DomainError) else "WORKER_ERROR"
                        emit(s,run,"RUN_ERROR",{"code":run.failure_code,"message":sanitize(str(error))[:1000]})
                        transition(s,run,Status.FAILED)
                    job.status="DONE";job.lease_token=None
            return True
    def _execution_revoked(self, snap: dict) -> bool:
        with self.services.db.session() as s:
            job=s.get(Outbox,snap["job_id"])
            run=s.get(Run,snap["id"])
            return (not job or not run or job.lease_token!=snap["lease_token"]
                    or job.lease_until<=now() or run.status!=snap["status"])
    def step(self,snap: dict):
        state=Status(snap["status"]); fid=snap["fixture_id"];run_id=snap["id"]
        wm=self.services.workspaces;spec=fixture(fid)
        cancelled=(lambda:self._execution_revoked(snap)) if "job_id" in snap else None
        if snap["data"].get("execution_backend", "reviewed_subprocess") != self.services.settings.execution_backend:
            raise DomainError("EXECUTION_BACKEND_CHANGED", "Queued run backend changed; no silent execution fallback")
        if state==Status.QUEUED: return Status.PREPARING,{},[],False
        if state==Status.PREPARING:
            wm.assert_head(fid,snap["base_commit"])
            wm.checkout(run_id,fid,snap["base_commit"],"workspace")
            return Status.REPRODUCING,{},[],False
        if state==Status.REPRODUCING:
            result=wm.test(wm.workspace(run_id),fid,cancelled=cancelled)
            if result["exit_code"]!=1 or result["failures"]!=[spec.expected_failure] or result["errors"] or result["skipped"]:
                raise DomainError("REPRODUCTION_MISMATCH","Expected bug assertion was not the sole reproduced failure")
            return Status.PATCHING,{"before":result},[("reproduction",canonical(result),"application/json")],False
        if state==Status.PATCHING:
            patch=FixtureExecutor().propose(wm.workspace(run_id),fid)
            if not patch: raise DomainError("EMPTY_PATCH","No change produced")
            return Status.VERIFYING,{},[("patch",patch.encode(),"text/x-diff")],False
        if state==Status.VERIFYING:
            with self.services.db.session() as s:
                artifact=s.get(Artifact,snap["data"]["patch_artifact_id"])
                if not artifact: raise DomainError("MISSING_PATCH","Patch missing")
                patch=self.services.store.read(artifact)
            clean=wm.checkout(run_id,fid,snap["base_commit"],"validator")
            patch_file=wm.run_root(run_id)/"candidate.diff";patch_file.write_bytes(patch)
            git(clean,"apply","--check",str(patch_file));git(clean,"apply",str(patch_file))
            changed=git(clean,"diff","--name-only").splitlines()
            if changed!=["module.py"]: raise DomainError("PROTECTED_PATH","Patch modified a protected file")
            result=wm.test(clean,fid,cancelled=cancelled)
            if result["exit_code"]!=0 or result["tests_run"]!=4 or result["failures"] or result["errors"] or result["skipped"]:
                raise DomainError("VALIDATION_FAILED","Independent fixture validation failed")
            if result["grader_sha256"]!=snap["data"]["before"]["grader_sha256"]:
                raise DomainError("GRADER_CHANGED","Before/after grader versions differ")
            return Status.WAITING_APPROVAL,{"after":result},[("regression",canonical(result),"application/json")],True
        raise DomainError("INVALID_STATE","No execution step for this phase")
