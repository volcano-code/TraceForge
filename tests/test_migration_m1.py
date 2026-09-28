"""Compatibility checks against a database created by the original M0 migration."""
import os
from pathlib import Path
import subprocess
import sys
import uuid
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]


def migrate(tmp_path, *args):
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'TF_DATA_DIR': str(tmp_path),
           'TF_DATABASE_URL': 'sqlite:///' + str(tmp_path / 'db.sqlite')}
    return subprocess.run([sys.executable, '-m', 'alembic', *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=30)


def test_m0_upgrade_preserves_approved_scope_and_operation(tmp_path):
    first = migrate(tmp_path, 'upgrade', 'a922eb20b205')
    assert first.returncode == 0, first.stderr
    engine = create_engine('sqlite:///' + str(tmp_path / 'db.sqlite'))
    ids = {k: str(uuid.uuid4()) for k in ('project', 'run', 'approval', 'artifact', 'operation')}
    with engine.begin() as connection:
        connection.execute(text('INSERT INTO projects VALUES (:project,"legacy","pagination",:sha,1)'), {**ids, 'sha': 'a' * 40})
        connection.execute(text('''INSERT INTO runs (id,project_id,objective,runtime,base_commit,status,version,event_seq,request_key,request_hash,data,failure_code,created_at,updated_at)
          VALUES (:run,:project,'legacy run','fixture',:sha,'DELIVERED_LOCAL',8,8,'legacy-key',:hash,'{}',NULL,1,1)'''), {**ids, 'sha': 'a' * 40, 'hash': 'b' * 64})
        connection.execute(text('''INSERT INTO approvals VALUES (:approval,:run,:sha,:hash,:hash,'APPROVED',9999999999,'reviewer',1,'original approval')'''), {**ids, 'sha': 'a' * 40, 'hash': 'b' * 64})
        connection.execute(text("INSERT INTO artifacts VALUES (:artifact,:run,'delivery',:hash,'application/json',2,1)"), {**ids, 'hash': 'c' * 64})
        connection.execute(text("INSERT INTO operations VALUES (:operation,:run,'LOCAL_RECEIPT',:hash,'SUCCEEDED',:artifact,NULL,1)"), {**ids, 'hash': 'd' * 64})
    result = migrate(tmp_path, 'upgrade', 'head')
    assert result.returncode == 0, result.stderr
    with engine.connect() as connection:
        row = connection.execute(text('SELECT decision,delivery_kind,comment FROM approvals')).one()
        assert tuple(row) == ('APPROVED', 'LOCAL_RECEIPT', 'original approval')
        row = connection.execute(text('SELECT id,status,artifact_id,attempts FROM operations')).one()
        assert tuple(row) == (ids['operation'], 'SUCCEEDED', ids['artifact'], 0)
    engine.dispose()


def test_downgrade_refuses_to_erase_external_operation_history(tmp_path):
    result = migrate(tmp_path, 'upgrade', 'head')
    assert result.returncode == 0, result.stderr
    from sqlalchemy.orm import Session
    from traceforge.models import Project, Run, Artifact, Operation
    engine = create_engine('sqlite:///' + str(tmp_path / 'db.sqlite'))
    with Session(engine) as session:
        project = Project(name='fixture', fixture_id='pagination', base_commit='a' * 40)
        session.add(project); session.flush()
        run = Run(project_id=project.id, objective='migration test', base_commit=project.base_commit,
                  request_key='migration-test', request_hash='b' * 64)
        session.add(run); session.flush()
        artifact = Artifact(run_id=run.id, kind='delivery_intent', sha256='c' * 64, byte_count=2)
        session.add(artifact); session.flush()
        operation = Operation(run_id=run.id, kind='SIMULATED_PR', idempotency_key='d' * 64,
                              status='IN_DOUBT', artifact_id=artifact.id)
        session.add(operation); session.commit()
    result = migrate(tmp_path, 'downgrade', 'a922eb20b205')
    assert result.returncode != 0
    assert 'Cannot downgrade while simulator operation history exists' in result.stderr
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM operations WHERE status=\'IN_DOUBT\'')) == 1
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == 'b82f4b61d2a0'
    engine.dispose()
