"""Real reviewed-byte subprocess tests and explicit mocked Docker contract tests."""
import json
import os
import sys
import time
from pathlib import Path
import pytest
from traceforge.domain import DomainError
from traceforge.execution.docker import DockerFixtureBackend
from traceforge.execution.inputs import ReviewedInput
from traceforge.execution.process import BoundedProcessRunner, ProcessResult
from traceforge.execution.readiness import readiness_report
from traceforge.execution.reviewed import ReviewedSubprocessBackend
from traceforge.fixtures import FIXTURES


@pytest.mark.parametrize('fid', sorted(FIXTURES))
def test_actual_snapshot_before_after(fid):
    spec=FIXTURES[fid]
    backend=ReviewedSubprocessBackend()
    before=backend.run(ReviewedInput.from_bytes(fid,spec.original.encode()))
    after=backend.run(ReviewedInput.from_bytes(fid,spec.fixed.encode()))
    assert before['exit_code']==1 and before['failures']==[spec.expected_failure]
    assert after['exit_code']==0 and after['tests_run']==4
    assert before['input_fingerprint']!=after['input_fingerprint']
    assert before['grader_sha256']==after['grader_sha256']
    assert after['process']['termination']=='completed'


def test_captured_bytes_do_not_follow_later_workspace_replacement(tmp_path):
    path=tmp_path/'module.py';path.write_text(FIXTURES['pagination'].original)
    snapshot=ReviewedInput.capture(path,'pagination')
    path.write_text('raise RuntimeError("this replacement must not execute")\n')
    result=ReviewedSubprocessBackend().run(snapshot)
    assert result['failures']==['test_delete_last_page'] and result['errors']==[]
    assert path.read_text().startswith('raise RuntimeError')


@pytest.mark.parametrize('kind',['symlink','directory','fifo','unknown_bytes'])
def test_unsafe_input_is_rejected(tmp_path,kind):
    target=tmp_path/'module.py'
    if kind=='symlink':
        source=tmp_path/'other.py';source.write_text(FIXTURES['pagination'].original);target.symlink_to(source)
    if kind=='directory': target.mkdir()
    if kind=='fifo': os.mkfifo(target)
    if kind=='unknown_bytes': target.write_text('print("not reviewed")\n')
    with pytest.raises(DomainError): ReviewedInput.capture(target,'pagination')


def test_forged_grader_never_executes():
    source=FIXTURES['pagination'].original.encode()
    forged=ReviewedInput('pagination',source,b'print("fake pass")\n')
    with pytest.raises(DomainError) as caught: ReviewedSubprocessBackend().run(forged)
    assert caught.value.code=='UNTRUSTED_GRADER'


def command(tmp_path,code,**kwargs):
    return BoundedProcessRunner().run([sys.executable,'-I','-c',code],cwd=tmp_path,
                                     env={'PATH':os.defpath,'HOME':str(tmp_path)},**kwargs)


def test_process_has_explicit_environment_not_parent_secrets(tmp_path,monkeypatch):
    monkeypatch.setenv('TF_SECRET_CANARY','synthetic-audit-secret')
    r=command(tmp_path,'import os; print(os.getenv("TF_SECRET_CANARY", "ABSENT"))')
    assert r.termination=='completed' and r.stdout.strip()=='ABSENT'


def test_process_wall_timeout(tmp_path):
    started=time.monotonic();r=command(tmp_path,'import time; time.sleep(10)',timeout=.15)
    assert r.termination=='timeout' and r.exit_code!=0 and time.monotonic()-started<3


def test_process_output_is_bounded(tmp_path):
    r=command(tmp_path,'import sys\nwhile True: sys.stdout.write("x"*4096); sys.stdout.flush()',max_output_bytes=1024)
    assert r.termination=='output_limit' and r.truncated
    assert len((r.stdout+r.stderr).encode())<=1024


def test_process_cancellation(tmp_path):
    started=time.monotonic()
    r=command(tmp_path,'import time; time.sleep(10)',cancelled=lambda:time.monotonic()-started>.1)
    assert r.termination=='cancelled' and time.monotonic()-started<3


def test_failed_authority_check_stops_execution(tmp_path):
    def broken(): raise RuntimeError('storage unavailable')
    r=command(tmp_path,'import time; time.sleep(10)',cancelled=broken)
    assert r.termination=='authority_check_failed'


def ordinary_child_stopped(pid):
    """Process disappearance between open/read is successful cleanup, not a failure."""
    try:
        stat = Path(f'/proc/{pid}/stat').read_text()
    except (FileNotFoundError, ProcessLookupError):
        return True
    # comm may contain spaces; state follows the final closing parenthesis.
    return stat.rsplit(')', 1)[1].split()[0] == 'Z'


@pytest.mark.parametrize('error', [FileNotFoundError, ProcessLookupError])
def test_proc_cleanup_probe_handles_disappearance(monkeypatch, error):
    def vanished(*args, **kwargs):
        raise error('process was already reaped')
    monkeypatch.setattr(Path, 'read_text', vanished)
    assert ordinary_child_stopped(12345)


def test_process_group_cleanup_covers_ordinary_child(tmp_path):
    code='import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(15)"]); print(p.pid,flush=True); time.sleep(15)'
    r=command(tmp_path,code,timeout=2.0)
    assert r.termination=='timeout'
    pid=int(r.stdout.strip())
    for _ in range(30):
        if ordinary_child_stopped(pid): break
        time.sleep(.02)
    else: pytest.fail('ordinary child process remained running')


@pytest.mark.parametrize('timeout,limit',[(0,1024),(301,1024),(1,1)])
def test_invalid_process_limits_rejected(tmp_path,timeout,limit):
    with pytest.raises(ValueError): command(tmp_path,'pass',timeout=timeout,max_output_bytes=limit)


IMAGE='sha256:'+'a'*64
HOST='unix:///run/user/1000/docker.sock'


def result(payload='',exit_code=0,stderr='',termination='completed'):
    text=payload if isinstance(payload,str) else json.dumps(payload)
    return ProcessResult(exit_code,text,stderr,termination,1,len(text.encode())+len(stderr.encode()),False)


class FakeDocker:
    """No containers are executed. Used ONLY to test constructed commands/contracts."""
    def __init__(self,*,rootless=True,image_id=IMAGE,volumes=None,termination='completed',owner_mismatch=False):
        self.calls=[];self.owner=None;self.rootless=rootless;self.image_id=image_id
        self.volumes=volumes;self.termination=termination;self.owner_mismatch=owner_mismatch
    def run(self,argv,**kwargs):
        self.calls.append((argv,kwargs))
        if 'info' in argv:
            return result({'SecurityOptions':['name=rootless'] if self.rootless else [],'ServerVersion':'test-only','CgroupVersion':'2','CgroupDriver':'systemd',
                           'MemoryLimit':True,'SwapLimit':True,'PidsLimit':True,'CpuCfsQuota':True,'CpuCfsPeriod':True})
        if 'image' in argv:
            return result({'Id':self.image_id,'Os':'linux','Config':{'Volumes':self.volumes}})
        if 'run' in argv:
            self.owner=next(x.split('=',1)[1] for x in argv if x.startswith('traceforge.owner='))
            return result({'tests_run':4,'failures':[],'errors':[],'skipped':0,'log':'contract-only'},
                          termination=self.termination)
        if 'inspect' in argv:
            return result({'traceforge.owner':'another-owner' if self.owner_mismatch else self.owner})
        if 'rm' in argv: return result('removed')
        raise AssertionError(argv)


def backend(fake,**kwargs):
    return DockerFixtureBackend(kwargs.get('image_id',IMAGE),kwargs.get('host',HOST),runner=fake,binary='/fake/docker')


def test_missing_docker_never_invokes_host_runner(monkeypatch):
    monkeypatch.setattr('traceforge.execution.docker.shutil.which',lambda _:None)
    fake=FakeDocker()
    b=DockerFixtureBackend(IMAGE,HOST,runner=fake)
    with pytest.raises(DomainError) as caught: b.run(ReviewedInput.from_bytes('pagination',FIXTURES['pagination'].fixed.encode()))
    assert caught.value.code=='DOCKER_UNAVAILABLE' and fake.calls==[]


@pytest.mark.parametrize('options,code',[
    ({'image_id':'python:latest'},'UNPINNED_SANDBOX_IMAGE'),
    ({'host':'tcp://remote:2375'},'UNSAFE_DOCKER_HOST'),
])
def test_unsafe_docker_configuration_fails_before_contact(options,code):
    fake=FakeDocker()
    with pytest.raises(DomainError) as caught: backend(fake,**options).preflight()
    assert caught.value.code==code and fake.calls==[]


@pytest.mark.parametrize('fake,code',[(FakeDocker(rootless=False),'ROOTLESS_REQUIRED'),
                                     (FakeDocker(image_id='sha256:'+'b'*64),'SANDBOX_IMAGE_MISMATCH'),
                                     (FakeDocker(volumes={'/danger':{}}),'UNSAFE_IMAGE_VOLUMES')])
def test_docker_daemon_and_image_policy(fake,code):
    with pytest.raises(DomainError) as caught: backend(fake).preflight()
    assert caught.value.code==code
    assert all('run' not in argv for argv,_ in fake.calls)


def test_docker_command_is_restricted_and_has_only_snapshot_mount(monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN','synthetic-canary-never-forward')
    fake=FakeDocker();b=backend(fake)
    output=b.run(ReviewedInput.from_bytes('pagination',FIXTURES['pagination'].fixed.encode()))
    argv=next(a for a,_ in fake.calls if 'run' in a)
    assert output['execution_mode']=='trusted_fixture_docker'
    required={'--network=none','--read-only','--pull=never','--cap-drop=ALL',
              '--security-opt=no-new-privileges=true','--user=65534:65534','--memory=256m',
              '--memory-swap=256m','--pids-limit=64','--cpus=1','--entrypoint=python3'}
    assert required<=set(argv)
    assert argv.count('--mount')==1
    assert 'dst=/input,readonly' in argv[argv.index('--mount')+1]
    assert '--privileged' not in argv and '-v' not in argv and '-p' not in argv
    for _,kwargs in fake.calls:
        assert set(kwargs['env'])=={'PATH','HOME','LANG'}
        assert 'synthetic-canary' not in str(kwargs)
    assert any('rm' in a for a,_ in fake.calls)


def test_docker_timeout_cleans_owned_container_and_does_not_pass():
    fake=FakeDocker(termination='timeout')
    with pytest.raises(DomainError) as caught:
        backend(fake).run(ReviewedInput.from_bytes('pagination',FIXTURES['pagination'].fixed.encode()))
    assert caught.value.code=='EXECUTION_TIMEOUT'
    assert any('rm' in a for a,_ in fake.calls)


def test_docker_cleanup_never_removes_foreign_container():
    fake=FakeDocker(owner_mismatch=True)
    with pytest.raises(DomainError) as caught:
        backend(fake).run(ReviewedInput.from_bytes('pagination',FIXTURES['pagination'].fixed.encode()))
    assert caught.value.code=='SANDBOX_OWNER_MISMATCH'
    assert not any('rm' in a for a,_ in fake.calls)


def test_readiness_does_not_claim_integrated_agent(svc):
    report=readiness_report(svc.settings)
    assert report['coding_agent_ready'] is False and report['arbitrary_repository_enabled'] is False
    assert 'OPENHANDS_EXECUTOR_NOT_INTEGRATED' in report['blocking_reasons']
    assert svc.settings.reviewer_token not in json.dumps(report)


def test_readiness_api_requires_auth(client,headers):
    path='/api/v1/execution/readiness'
    assert client.get(path).status_code==401
    response=client.get(path,headers=headers)
    assert response.status_code==200 and response.json()['coding_agent_ready'] is False


def test_configured_missing_docker_rejects_run_without_queueing(svc,new_run,monkeypatch):
    from sqlalchemy import select,func
    from traceforge.models import Run
    monkeypatch.setattr('traceforge.execution.docker.shutil.which',lambda _:None)
    svc.workspaces.test_backend=DockerFixtureBackend(IMAGE,HOST)
    with pytest.raises(DomainError) as caught: new_run()
    assert caught.value.code=='DOCKER_UNAVAILABLE'
    with svc.db.session() as s: assert s.scalar(select(func.count()).select_from(Run))==0


def test_worker_refuses_silent_backend_change(svc,new_run):
    from traceforge.workflow import Worker
    from traceforge.models import Run
    run=new_run()
    with svc.db.transaction() as s:
        stored=s.get(Run,run.id);stored.data={**stored.data,'execution_backend':'docker_fixture'}
    Worker(svc).execute_one()
    with svc.db.session() as s:
        stored=s.get(Run,run.id)
        assert stored.status=='FAILED' and stored.failure_code=='EXECUTION_BACKEND_CHANGED'


def test_idempotent_read_does_not_require_live_backend(svc,new_run):
    original=new_run(key='stable-read-only-replay')
    class OfflineBackend:
        def preflight(self): raise AssertionError('replay must be read only')
    svc.workspaces.test_backend=OfflineBackend()
    replay=new_run(key='stable-read-only-replay')
    assert replay.id==original.id


def test_worker_cancel_stops_active_process_and_does_not_publish_success(svc,new_run):
    import threading
    from traceforge.workflow import Worker
    from traceforge.models import Run,Approval
    from sqlalchemy import select
    started=threading.Event()
    observed=[]
    class DelayedReviewedBackend:
        """Test-only slow trusted command, not untrusted model-generated code."""
        name='reviewed_subprocess'
        def preflight(self): return {'available':True}
        def run(self,snapshot,*,cancelled=None):
            with snapshot.staged() as root:
                started.set()
                outcome=BoundedProcessRunner().run(
                    [sys.executable,'-I','-c','import time; time.sleep(20)'],cwd=root,
                    env={'PATH':os.defpath,'HOME':str(root)},timeout=10,cancelled=cancelled)
            observed.append(outcome.termination)
            raise DomainError('EXECUTION_CANCELLED','test runner was cancelled')
    svc.workspaces.test_backend=DelayedReviewedBackend()
    run=new_run()
    thread=threading.Thread(target=Worker(svc).execute_one,daemon=True)
    thread.start()
    try:
        assert started.wait(8),'worker did not reach process execution'
        svc.cancel(run.id)
        thread.join(timeout=4)
        assert not thread.is_alive(),'cancelled worker remained running'
        assert observed==['cancelled']
        with svc.db.session() as s:
            assert s.get(Run,run.id).status=='CANCELLED'
            assert s.scalar(select(Approval).where(Approval.run_id==run.id)) is None
    finally:
        thread.join(timeout=12)


@pytest.mark.parametrize('mutation',['fingerprint','truncated','missing_contract','report_environment'])
def test_snapshot_result_tamper_cannot_authorize(svc,complete,mutation):
    from traceforge.artifacts import canonical,digest
    from traceforge.models import Run,Artifact,Approval
    run,approval,request=complete()
    with svc.db.transaction() as session:
        stored=session.get(Run,run.id)
        report=json.loads(svc.store.read(session.get(Artifact,stored.data['validation_artifact_id'])))
        old=session.get(Artifact,stored.data['regression_artifact_id'])
        after=json.loads(svc.store.read(old))
        if mutation=='fingerprint': after['input_fingerprint']='0'*64
        if mutation=='truncated': after['process']['truncated']=True
        if mutation=='missing_contract':
            del after['input_fingerprint'];del after['process']
        if mutation=='report_environment':
            report['environment']['execution_environment']={'backend':'forged'}
            report['environment_fingerprint']=digest(canonical(report['environment']))
        artifact=svc.store.put(session,stored.id,'regression',canonical(after),'application/json')
        report['after']=after
        report['artifacts']=[{'id':artifact.id,'kind':artifact.kind,'sha256':artifact.sha256}
                             if ref['kind']=='regression' else ref for ref in report['artifacts']]
        validation=svc.store.put(session,stored.id,'validation',canonical(report),'application/json')
        stored.data={**stored.data,'regression_artifact_id':artifact.id,
                     'validation_artifact_id':validation.id,'validation_digest':validation.sha256}
        session.get(Approval,approval.id).validation_digest=validation.sha256
        request=request.model_copy(update={'validation_digest':validation.sha256})
    with pytest.raises(DomainError) as caught: svc.decide(approval.id,request,'reviewer')
    assert caught.value.code=='INVALID_EVIDENCE'
