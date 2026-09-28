"""Explicit LIVE Docker gate. Missing environment is BLOCKED, never PASS/skip."""
from __future__ import annotations
from .docker import DockerFixtureBackend
from .inputs import ReviewedInput
from ..domain import DomainError


def docker_smoke(settings) -> dict:
    from ..fixtures import FIXTURES
    report={'schema_version':'tf-live-docker-smoke/v1','status':'BLOCKED','checks':[],
            'containers_executed':0,'real_model_called':False,'arbitrary_repository_tested':False}
    backend=DockerFixtureBackend(settings.sandbox_image_id,settings.sandbox_docker_host)
    try:
        report['preflight']=backend.preflight()
        for fid,spec in FIXTURES.items():
            for label,source,expected in [('before',spec.original,1),('after',spec.fixed,0)]:
                result=backend.run(ReviewedInput.from_bytes(fid,source.encode()))
                report['containers_executed']+=1
                expected_failures=[spec.expected_failure] if label=='before' else []
                if (result['exit_code']!=expected or result['tests_run']!=4 or result['errors']
                        or result['skipped'] or result['failures']!=expected_failures):
                    raise DomainError('LIVE_DOCKER_SMOKE_FAILED','Fixture did not reach its expected result')
                report['checks'].append({'fixture':fid,'stage':label,'passed':True,
                                         'input_fingerprint':result['input_fingerprint'],
                                         'execution_environment':result['execution_environment']})
        report['status']='PASS'
    except DomainError as error:
        report.update(status='BLOCKED' if report['containers_executed']==0 else 'FAIL',
                      error_code=error.code,message=error.message)
    return report
