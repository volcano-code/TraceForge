import shutil
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from traceforge.api import create_app
from traceforge.config import Settings
from traceforge.db import Database
from traceforge.domain import ApprovalDecision, RunCreate
from traceforge.models import Approval, Base, Project, Run
from traceforge.services import Services
from traceforge.workflow import Worker

DEV="test-developer-"+"a"*40
REVIEW="test-reviewer-"+"b"*40
SECRET="test-webhook-"+"c"*40

@pytest.fixture(scope="session")
def origins(tmp_path_factory):
    root=tmp_path_factory.mktemp("seed")
    settings=Settings(_env_file=None,database_url="sqlite:///"+str(root/"db.sqlite"),data_dir=root,
                      developer_token=DEV,reviewer_token=REVIEW,webhook_secret=SECRET)
    db=Database(settings);Base.metadata.create_all(db.engine);Services(settings,db).seed();db.close()
    return root/"origins"

@pytest.fixture
def svc(tmp_path,origins):
    shutil.copytree(origins,tmp_path/"origins")
    settings=Settings(_env_file=None,database_url="sqlite:///"+str(tmp_path/"db.sqlite"),data_dir=tmp_path,
                      developer_token=DEV,reviewer_token=REVIEW,webhook_secret=SECRET)
    db=Database(settings);Base.metadata.create_all(db.engine)
    service=Services(settings,db);service.seed()
    yield service
    db.close()

@pytest.fixture
def client(svc):
    with TestClient(create_app(svc.settings,svc.db)) as c: yield c

@pytest.fixture
def headers(): return {"Authorization":"Bearer "+REVIEW}

@pytest.fixture
def new_run(svc):
    def create(fid="pagination",key=None):
        with svc.db.session() as s: p=s.scalar(select(Project).where(Project.fixture_id==fid))
        return svc.create_run(RunCreate(project_id=p.id,objective="Repair the reviewed synthetic fixture"),key or str(uuid.uuid4()))
    return create

@pytest.fixture
def complete(svc,new_run):
    def finish(fid="pagination"):
        run=new_run(fid);Worker(svc).execute_one()
        with svc.db.session() as s:
            run=s.get(Run,run.id)
            assert run.status=="WAITING_APPROVAL",run.failure_code
            approval=s.scalar(select(Approval).where(Approval.run_id==run.id))
            request=ApprovalDecision(decision="APPROVED",base_commit=approval.base_commit,
                patch_hash=approval.patch_hash,validation_digest=approval.validation_digest)
            return run,approval,request
    return finish
