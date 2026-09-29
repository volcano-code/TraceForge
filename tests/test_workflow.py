import json
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import func,select
from traceforge.domain import DomainError,RunCreate
from traceforge.models import Approval,Artifact,Operation,Outbox,Project,Run,RunEvent,now
from traceforge.services import Services
from traceforge.workflow import SimulatedCrash,Worker

@pytest.mark.parametrize("fid",["pagination","empty-mean","slug-space"])
def test_real_fixture_reproduction_patch_and_verification(svc,complete,fid):
    run,approval,request=complete(fid)
    assert run.data["before"]["exit_code"]==1
    assert len(run.data["before"]["failures"])==1
    assert run.data["after"]["exit_code"]==0
    assert run.data["after"]["tests_run"]==4
    assert run.data["after"]["grader_sha256"]==run.data["before"]["grader_sha256"]
    with svc.db.session() as s:
        report=json.loads(svc.store.read(s.get(Artifact,run.data["validation_artifact_id"])))
    assert report["verified"] is True
    assert report["model_calls"]==0 and report["runtime"]=="fixture"
    assert (svc.workspaces.run_root(run.id)/"validator") != svc.workspaces.workspace(run.id)
    svc.decide(approval.id,request,"reviewer")
    first=svc.deliver_local(run.id,approval.id,"reviewer")
    second=svc.deliver_local(run.id,approval.id,"reviewer")
    assert first.id==second.id
    assert first.external_ref is None
    with svc.db.session() as s:
        receipt=json.loads(svc.store.read(s.get(Artifact,first.artifact_id)))
        assert receipt["real_github_pr_created"] is False
        assert s.scalar(select(func.count()).select_from(Operation))==1
        assert s.get(Run,run.id).status=="DELIVERED_LOCAL"

@pytest.mark.parametrize("phase",["PREPARING","REPRODUCING","PATCHING","VERIFYING"])
def test_checkpoint_recovery_from_committed_phase(svc,new_run,phase):
    run=new_run()
    with pytest.raises(SimulatedCrash): Worker(svc).execute_one(crash_after=phase)
    with svc.db.transaction() as s:
        job=s.scalar(select(Outbox).where(Outbox.run_id==run.id));job.lease_until=now()-1
    # New service / worker instances use the existing database, not Python memory.
    recovered=Worker(Services(svc.settings,svc.db));assert recovered.execute_one()
    with svc.db.session() as s:
        assert s.get(Run,run.id).status=="WAITING_APPROVAL"
        transitions=list(s.scalars(select(RunEvent).where(RunEvent.run_id==run.id,RunEvent.event_type=="PHASE_CHANGED")))
        targets=[e.payload["to"] for e in transitions]
        assert len(targets)==len(set(targets))
        assert s.scalar(select(func.count()).select_from(Approval).where(Approval.run_id==run.id))==1


def test_event_sequences_are_gap_free(svc,complete):
    run,_,_=complete()
    with svc.db.session() as s:
        events=list(s.scalars(select(RunEvent).where(RunEvent.run_id==run.id).order_by(RunEvent.sequence)))
        assert [e.sequence for e in events]==list(range(1,len(events)+1))
        assert [e.state_version for e in events]==sorted(e.state_version for e in events)

def test_create_is_idempotent_and_outbox_atomic(svc,new_run):
    first=new_run(key="same-request-key");second=new_run(key="same-request-key")
    assert first.id==second.id
    with svc.db.session() as s:
        assert s.scalar(select(func.count()).select_from(Run))==1
        assert s.scalar(select(func.count()).select_from(Outbox))==1

def test_changed_payload_cannot_reuse_key(svc,new_run):
    first=new_run(key="same-request-key")
    with pytest.raises(DomainError,match="different payload"):
        svc.create_run(RunCreate(project_id=first.project_id,objective="A different request"),"same-request-key")

def test_concurrent_creation_same_key(svc,new_run):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:new_run(key="parallel-same-key").id,range(4)))
    assert len(set(results))==1

def test_concurrent_workers_single_claim(svc,new_run):
    run=new_run()
    with ThreadPoolExecutor(max_workers=3) as pool:
        claims=list(pool.map(lambda _:Worker(svc).claim(),range(3)))
    assert sum(c is not None for c in claims)==1

def test_cancelled_run_does_not_execute(svc,new_run):
    run=new_run();svc.cancel(run.id);assert not Worker(svc).execute_one()
    with svc.db.session() as s: assert s.get(Run,run.id).status=="CANCELLED"

def test_cancel_is_idempotent(svc,new_run):
    run=new_run();a=svc.cancel(run.id);b=svc.cancel(run.id);assert a.version==b.version

def test_cancel_after_checkpoint_prevents_resume(svc,new_run):
    run=new_run()
    with pytest.raises(SimulatedCrash): Worker(svc).execute_one(crash_after="VERIFYING")
    svc.cancel(run.id);assert not Worker(svc).execute_one()
    with svc.db.session() as s: assert not s.scalar(select(Approval).where(Approval.run_id==run.id))

def test_stale_worker_is_fenced_on_cancel(svc,new_run,monkeypatch):
    run=new_run();worker=Worker(svc);original=worker.step
    def step(snapshot):
        result=original(snapshot)
        if snapshot["status"]=="PREPARING": svc.cancel(run.id)
        return result
    monkeypatch.setattr(worker,"step",step);worker.execute_one()
    with svc.db.session() as s: assert s.get(Run,run.id).status=="CANCELLED"

def test_retry_exhaustion_safe_failure(svc,new_run):
    run=new_run()
    with svc.db.transaction() as s:
        job=s.scalar(select(Outbox).where(Outbox.run_id==run.id));job.attempts=3
    Worker(svc).execute_one()
    with svc.db.session() as s: assert s.get(Run,run.id).failure_code=="RETRY_EXHAUSTED"

def test_worker_error_classification(svc,new_run,monkeypatch):
    run=new_run();worker=Worker(svc)
    def bad(_): raise DomainError("TEST_FAILURE","token=should-not-leak")
    monkeypatch.setattr(worker,"step",bad);worker.execute_one()
    with svc.db.session() as s:
        assert s.get(Run,run.id).failure_code=="TEST_FAILURE"
        error=s.scalar(select(RunEvent).where(RunEvent.event_type=="RUN_ERROR"))
        assert "should-not-leak" not in error.payload["message"]
