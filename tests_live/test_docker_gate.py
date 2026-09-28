"""Explicit integration gate: no Docker => FAIL, never silent skip.
Run only on an authorized Linux/WSL host with reviewed cached image configured.
"""
from traceforge.config import Settings
from traceforge.execution.smoke import docker_smoke


def test_live_rootless_docker_reviewed_fixtures():
    report = docker_smoke(Settings())
    assert report['status'] == 'PASS', report
    assert report['containers_executed'] == 6, report
    assert len(report['checks']) == 6 and all(item['passed'] for item in report['checks'])
