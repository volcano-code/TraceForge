"""Regression and release-metadata checks; all Docker stubs are contract-only."""
import json
import pytest
from traceforge.domain import DomainError
from traceforge.execution.docker import DockerFixtureBackend
from traceforge.execution.smoke import docker_smoke
from traceforge.execution.inputs import ReviewedInput
from traceforge.fixtures import FIXTURES
from test_execution_m2 import FakeDocker, backend, result


def test_cleanup_failure_does_not_erase_completed_execution(monkeypatch,svc):
    b=backend(FakeDocker(owner_mismatch=True))
    monkeypatch.setattr('traceforge.execution.smoke.DockerFixtureBackend',lambda *a,**kw:b)
    report=docker_smoke(svc.settings)
    assert report['status']=='FAIL'
    assert report['launch_attempts']==1
    assert report['containers_executed']==1
    attempt=report['attempts'][0]
    assert attempt['execution_completed'] is True
    assert attempt['cleanup_confirmed'] is None
    assert attempt['failure_stage']=='cleanup'


def test_preflight_failure_is_blocked_before_any_attempt(monkeypatch,svc):
    b=backend(FakeDocker(rootless=False))
    monkeypatch.setattr('traceforge.execution.smoke.DockerFixtureBackend',lambda *a,**kw:b)
    report=docker_smoke(svc.settings)
    assert report['status']=='BLOCKED' and report['launch_attempts']==0
    assert report['containers_executed']==0 and report['attempts']==[]


@pytest.mark.parametrize('termination',['timeout','output_limit','cancelled','authority_check_failed'])
def test_interrupted_execution_remains_unknown_not_zero(termination):
    b=backend(FakeDocker(termination=termination))
    with pytest.raises(DomainError) as caught:
        b.run(ReviewedInput.from_bytes('pagination',FIXTURES['pagination'].fixed.encode()))
    a=caught.value.attempt
    assert a['launch_attempted'] is True and a['execution_completed'] is None
    assert a['cleanup_confirmed'] is True and a['failure_stage']=='execution'
    assert a['container_id'] is None


def test_success_records_lifecycle_without_fabricating_container_id():
    output=backend(FakeDocker()).run(ReviewedInput.from_bytes('pagination',FIXTURES['pagination'].fixed.encode()))
    a=output['execution_attempt']
    assert a['execution_completed'] is True and a['validation_passed'] is True
    assert a['cleanup_confirmed'] is True and a['failure_stage'] is None
    assert a['container_id'] is None and a['container_name'].startswith('tf-fixture-')


def test_invalid_output_does_not_claim_container_completion():
    class Invalid(FakeDocker):
        def run(self,argv,**kwargs):
            response=super().run(argv,**kwargs)
            return result('invalid json') if 'run' in argv else response
    with pytest.raises(DomainError) as caught:
        backend(Invalid()).run(ReviewedInput.from_bytes('pagination',FIXTURES['pagination'].fixed.encode()))
    a=caught.value.attempt
    assert a['invocation_completed'] is True and a['execution_completed'] is None
    assert a['validation_passed'] is None and a['cleanup_confirmed'] is True
    assert a['failure_stage']=='decode'


def test_smoke_success_retains_all_attempts(monkeypatch,svc):
    from traceforge.execution.reviewed import ReviewedSubprocessBackend
    # Real local reviewed execution to produce valid expected results; explicitly
    # stub Docker lifecycle fields here, do not label this as live Docker.
    class ReviewedStub:
        def __init__(self,*args):pass
        def preflight(self):return {'contract_only':True}
        def run(self,snapshot):
            output=ReviewedSubprocessBackend().run(snapshot)
            output['execution_attempt']={'launch_attempted':True,'execution_completed':True,
                'cleanup_confirmed':True,'failure_stage':None,'validation_passed':output['exit_code']==0}
            return output
    monkeypatch.setattr('traceforge.execution.smoke.DockerFixtureBackend',ReviewedStub)
    r=docker_smoke(svc.settings)
    assert r['status']=='PASS' and r['launch_attempts']==r['containers_executed']==6
    assert r['unknown_execution_outcomes']==0 and r['validations_passed']==3
    assert len(r['attempts'])==6


def test_release_metadata_is_historical_and_not_current_host_authority(client,headers):
    assert client.get('/api/v1/meta').status_code==401
    meta=client.get('/api/v1/meta',headers=headers).json()
    release=meta['release']
    assert release['version']==meta['version']
    assert release['current_host_attested'] is False and release['coding_agent_ready'] is False
    assert release['history']['source_commit']=='911041016a817c26e6a6decd35f79657c9ff892e'
    assert '历史' in release['history']['scope']
    assert meta['real_llm_connected'] is False and meta['real_github_connected'] is False


def test_same_submission_after_discarded_response_has_one_run_and_outbox(client,headers,svc):
    from sqlalchemy import select,func
    from traceforge.models import Project,Run,Outbox,RunEvent
    with svc.db.session() as session: project=session.scalar(select(Project))
    payload={'project_id':project.id,'objective':'Discard first successful response and retry'}
    request_headers={**headers,'Idempotency-Key':'one-user-submission-intent'}
    first=client.post('/api/v1/runs',headers=request_headers,json=payload)
    assert first.status_code==201
    # Throw away its body, like a response lost after commit. No new key allocated.
    second=client.post('/api/v1/runs',headers=request_headers,json=payload)
    assert second.status_code==201 and second.json()['id']==first.json()['id']
    with svc.db.session() as session:
        assert session.scalar(select(func.count()).select_from(Run))==1
        assert session.scalar(select(func.count()).select_from(Outbox))==1
        assert session.scalar(select(func.count()).select_from(RunEvent).where(RunEvent.event_type=='RUN_CREATED'))==1
