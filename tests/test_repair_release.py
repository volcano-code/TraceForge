"""Regression probes for issues found while preparing the GitHub publication."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from traceforge.domain import DomainError
from traceforge.execution.docker import DockerFixtureBackend
from traceforge.execution.process import BoundedProcessRunner, ProcessResult

IMAGE = 'sha256:' + 'a' * 64
HOST = 'unix:///run/user/1000/docker.sock'

@pytest.mark.parametrize('broken', [False, True])
def test_revocation_is_checked_before_process_creation(tmp_path, broken):
    def revoked():
        if broken:
            raise RuntimeError('authorization store unavailable')
        return True
    with patch('traceforge.execution.process.subprocess.Popen') as spawn:
        result = BoundedProcessRunner().run([sys.executable, '-I', '-c', 'pass'], cwd=tmp_path,
                    env={'PATH': os.defpath}, cancelled=revoked)
        spawn.assert_not_called()
    assert result.termination == ('authority_check_failed' if broken else 'cancelled')
    assert result.observed_output_bytes == 0

class InspectionRunner:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.calls = []
    def run(self, argv, **kwargs):
        self.calls.append(argv)
        if 'info' in argv:
            data = {'SecurityOptions': ['name=rootless'], 'ServerVersion': 'contract-only',
                    'CgroupVersion': '2', 'CgroupDriver': 'systemd', 'MemoryLimit': True,
                    'SwapLimit': True, 'PidsLimit': True, 'CpuCfsQuota': True, 'CpuCfsPeriod': True}
            data.update(self.overrides)
        else:
            data = {'Id': IMAGE, 'Os': 'linux', 'Config': {'Volumes': None}}
        return ProcessResult(0, json.dumps(data), '', 'completed', 0, 0, False)

@pytest.mark.parametrize('override', [
    {'CgroupVersion': '1'}, {'CgroupDriver': 'none'}, {'MemoryLimit': False},
    {'PidsLimit': False}, {'CpuCfsQuota': False}, {'SwapLimit': False},
    {'MemoryLimit': None}, {'CpuCfsPeriod': False},
])
def test_rootless_without_enforced_resource_controls_is_rejected(override):
    runner = InspectionRunner(override)
    with pytest.raises(DomainError) as caught:
        DockerFixtureBackend(IMAGE, HOST, runner=runner, binary='/fake/docker').preflight()
    assert caught.value.code == 'CGROUP_LIMITS_UNAVAILABLE'
    assert len(runner.calls) == 1


def test_supported_resource_controls_remain_contract_only():
    report = DockerFixtureBackend(IMAGE, HOST, runner=InspectionRunner(), binary='/fake/docker').preflight()
    assert report['cgroup_version'] == '2'
    assert report['resource_controls_reported'] is True
    assert report['live_isolation_verified'] is False


def test_readiness_does_not_confuse_preflight_with_live_gate(svc, monkeypatch):
    from traceforge.execution.readiness import readiness_report
    monkeypatch.setattr(DockerFixtureBackend, 'preflight', lambda self: {'available': True})
    report = readiness_report(svc.settings, probe_docker=True)
    assert report['docker']['available'] is True
    assert 'LIVE_DOCKER_GATE_NOT_PASSED' in report['blocking_reasons']


def test_expired_claim_cannot_renew_itself_and_execute(svc, new_run, monkeypatch):
    from traceforge.workflow import Worker
    from traceforge.models import Outbox, now
    run = new_run()
    worker = Worker(svc)
    job_id, token = worker.claim()
    with svc.db.transaction() as session:
        session.get(Outbox, job_id).lease_until = now() - 1
    monkeypatch.setattr(worker, 'claim', lambda: (job_id, token))
    with patch.object(worker, 'step') as execute:
        assert worker.execute_one() is True
        execute.assert_not_called()
    with svc.db.session() as session:
        assert session.get(Outbox, job_id).lease_until < now()


def test_concurrent_workers_have_one_claim(svc, new_run):
    from concurrent.futures import ThreadPoolExecutor
    from traceforge.workflow import Worker
    new_run()
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: Worker(svc).claim(), range(4)))
    assert len([claim for claim in claims if claim is not None]) == 1
