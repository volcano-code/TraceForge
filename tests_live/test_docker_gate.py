"""Explicit integration gate: no Docker => FAIL, never silent skip.
Run only on an authorized Linux/WSL host with reviewed cached image configured.
"""
import json
from pathlib import Path
from traceforge.config import Settings
from traceforge.execution.docker import DockerFixtureBackend
from traceforge.execution.smoke import docker_smoke


def test_live_rootless_docker_reviewed_fixtures(monkeypatch):
    # Diagnostic-only wrapper: same backend, same limits, same assertions. No
    # credentials are passed by the trusted builder. Only bounded CLI failures
    # enter this explicit integration artifact; grader stdout is not exposed.
    failures = []
    original = DockerFixtureBackend._call
    def traced(self, args, **kwargs):
        result = original(self, args, **kwargs)
        if result.exit_code != 0 or result.termination != 'completed':
            failures.append({'command': args[0], 'exit_code': result.exit_code,
                             'termination': result.termination,
                             'stderr': result.stderr[:8192]})
        return result
    monkeypatch.setattr(DockerFixtureBackend, '_call', traced)
    report = docker_smoke(Settings())
    record = {'report': report, 'cli_failures': failures}
    target = Path('reports/ci/live-docker-diagnostics.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2) + '\n')
    assert report['status'] == 'PASS', json.dumps(record, indent=2)
    assert report['containers_executed'] == 6, report
    assert len(report['checks']) == 6 and all(item['passed'] for item in report['checks'])

    assert report['launch_attempts'] == 6 and report['unknown_execution_outcomes'] == 0
    assert report['validations_passed'] == 3
    assert all(a['cleanup_confirmed'] is True and a['execution_completed'] is True for a in report['attempts'])
