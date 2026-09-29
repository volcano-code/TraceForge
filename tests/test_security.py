import json
import pytest
from sqlalchemy import select
from traceforge.domain import DomainError
from traceforge.fixtures import fixture
from traceforge.models import Approval,Artifact,Project,Run,now
from traceforge.security import authenticate,sanitize


def test_developer_cannot_approve(svc,complete):
    _,a,r=complete()
    with pytest.raises(DomainError) as e: svc.decide(a.id,r,"developer")
    assert e.value.status==403

def test_delivery_without_approval_denied(svc,complete):
    run,a,_=complete()
    with pytest.raises(DomainError) as e: svc.deliver_local(run.id,a.id,"reviewer")
    assert e.value.code=="NOT_APPROVED"

@pytest.mark.parametrize("field",["base_commit","patch_hash","validation_digest"])
def test_binding_rejects_stale_hash(svc,complete,field):
    _,a,r=complete()
    r=r.model_copy(update={field:"0"*len(getattr(r,field))})
    with pytest.raises(DomainError) as e: svc.decide(a.id,r,"reviewer")
    assert e.value.code=="STALE_APPROVAL"

def test_expired_approval_denied(svc,complete):
    _,a,r=complete()
    with svc.db.transaction() as s: s.get(Approval,a.id).expires_at=now()-1
    with pytest.raises(DomainError) as e: svc.decide(a.id,r,"reviewer")
    assert e.value.code=="APPROVAL_EXPIRED"

def test_expiry_rechecked_at_delivery(svc,complete):
    run,a,r=complete();svc.decide(a.id,r,"reviewer")
    with svc.db.transaction() as s: s.get(Approval,a.id).expires_at=now()-1
    with pytest.raises(DomainError) as e: svc.deliver_local(run.id,a.id,"reviewer")
    assert e.value.code=="APPROVAL_EXPIRED"

@pytest.mark.parametrize("kind",["patch","validation","reproduction","regression"])
def test_artifact_tamper_denied_at_delivery(svc,complete,kind):
    run,a,r=complete();svc.decide(a.id,r,"reviewer")
    with svc.db.session() as s: artifact=s.get(Artifact,run.data[kind+"_artifact_id"])
    svc.store.path(artifact.sha256).write_bytes(b"tampered")
    with pytest.raises(DomainError) as e: svc.deliver_local(run.id,a.id,"reviewer")
    assert e.value.code=="ARTIFACT_TAMPERED"

def test_branch_change_invalidates_approval(svc,complete):
    run,a,r=complete();svc.decide(a.id,r,"reviewer")
    with svc.db.transaction() as s: s.get(Project,run.project_id).base_commit="a"*40
    with pytest.raises(DomainError) as e: svc.deliver_local(run.id,a.id,"reviewer")
    assert e.value.code=="BASE_CHANGED"

def test_reject_is_terminal(svc,complete):
    run,a,r=complete();r=r.model_copy(update={"decision":"REJECTED"})
    svc.decide(a.id,r,"reviewer")
    assert svc.decide(a.id,r,"reviewer").decision=="REJECTED"
    with pytest.raises(DomainError): svc.decide(a.id,r.model_copy(update={"decision":"APPROVED"}),"reviewer")
    with pytest.raises(DomainError): svc.deliver_local(run.id,a.id,"reviewer")

def test_cross_run_approval_denied(svc,complete):
    one,a,r=complete();two,_,_=complete("empty-mean");svc.decide(a.id,r,"reviewer")
    with pytest.raises(DomainError) as e: svc.deliver_local(two.id,a.id,"reviewer")
    assert e.value.code=="INVALID_APPROVAL"

@pytest.mark.parametrize("path",["../escape","/tmp/escape","abc/../../root"])
def test_workspace_traversal_rejected(svc,path):
    with pytest.raises(DomainError): svc.workspaces.run_root(path)

def test_artifact_hash_path_rejected(svc):
    with pytest.raises(DomainError): svc.store.path("../../etc/passwd")

def test_symlink_source_rejected(svc,new_run):
    run=new_run();wm=svc.workspaces;path=wm.checkout(run.id,"pagination",run.base_commit,"workspace")
    source=path/"module.py";source.unlink();source.symlink_to(wm.origin("pagination")/"module.py")
    with pytest.raises(DomainError) as e: wm.test(path,"pagination")
    assert e.value.code=="UNSAFE_FIXTURE"

def test_arbitrary_code_is_not_executed(svc,new_run):
    run=new_run();wm=svc.workspaces;path=wm.checkout(run.id,"pagination",run.base_commit,"workspace")
    marker=path/"marker.txt"
    (path/"module.py").write_text(f'open({str(marker)!r},"w").write("bad")')
    with pytest.raises(DomainError) as e: wm.test(path,"pagination")
    assert e.value.code=="UNTRUSTED_SOURCE"
    assert not marker.exists()

def test_missing_configuration_fails_closed():
    with pytest.raises(DomainError) as e: authenticate("Bearer anything","","")
    assert e.value.status==503

def test_duplicate_role_tokens_fail_closed():
    with pytest.raises(DomainError): authenticate("Bearer "+"x"*40,"x"*40,"x"*40)

def test_redaction_examples():
    assert "ABCDEF" not in sanitize("Authorization: Bearer ABCDEF")
    assert "sensitive" not in sanitize("api_key=sensitive password=sensitive")
