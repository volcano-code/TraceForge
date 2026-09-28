"""Explicit live PostgreSQL gate. No URL or missing driver is a failure, not a skip."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from traceforge.config import Settings
from traceforge.db import Database
from traceforge.domain import ApprovalDecision, RunCreate
from traceforge.models import Approval, Project, Run
from traceforge.services import Services
from traceforge.workflow import Worker


def test_live_postgres_migration_claim_approval_and_delivery(tmp_path, monkeypatch):
    url=os.getenv('TF_TEST_POSTGRES_URL','')
    assert url.startswith('postgresql+psycopg://'), 'TF_TEST_POSTGRES_URL required: gate not run'
    schema='tf_gate_'+uuid.uuid4().hex
    admin=create_engine(url)
    with admin.begin() as c: c.execute(text(f'CREATE SCHEMA "{schema}"'))
    # Isolate this gate without dropping or modifying unrelated schemas.
    separator='&' if '?' in url else '?'
    scoped=url+separator+'options=-csearch_path%3D'+schema
    db=None
    try:
        monkeypatch.setenv('TF_DATABASE_URL',scoped)
        monkeypatch.setenv('TF_DATA_DIR',str(tmp_path))
        cfg=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
        command.upgrade(cfg,'head');command.check(cfg)
        settings=Settings(database_url=scoped,data_dir=tmp_path,_env_file=None)
        db=Database(settings);svc=Services(settings,db);svc.seed()
        with db.session() as s: project=s.scalar(select(Project).where(Project.fixture_id=='pagination'))
        request=RunCreate(project_id=project.id,objective='Repair the reviewed pagination fixture.',runtime='fixture')
        with ThreadPoolExecutor(max_workers=4) as pool:
            runs=list(pool.map(lambda _:svc.create_run(request,'pg-identical-request'),range(4)))
        assert len({r.id for r in runs})==1
        run=runs[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims=list(pool.map(lambda _:Worker(svc).claim(),range(4)))
        claimed=[c for c in claims if c is not None]
        assert len(claimed)==1
        worker=Worker(svc);worker.claim=lambda:claimed[0]
        assert worker.execute_one()
        with db.session() as s:
            saved=s.get(Run,run.id)
            assert saved.status=='WAITING_APPROVAL'
            approval=s.scalar(select(Approval).where(Approval.run_id==run.id))
        decision=ApprovalDecision(decision='APPROVED',base_commit=approval.base_commit,
                  patch_hash=approval.patch_hash,validation_digest=approval.validation_digest)
        svc.decide(approval.id,decision,'reviewer')
        a=svc.deliver_local(run.id,approval.id,'reviewer');b=svc.deliver_local(run.id,approval.id,'reviewer')
        assert a.id==b.id and a.status=='SUCCEEDED'
    finally:
        if db: db.close()
        with admin.begin() as c: c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
