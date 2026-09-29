"""Explicit LIVE Docker gate with conservative lifecycle accounting.

containers_executed is a lower bound backed by completed, decoded fixture output.
An attempted invocation with an unknown result is never reported as zero attempts.
"""
from __future__ import annotations
from .docker import DockerFixtureBackend
from .inputs import ReviewedInput
from ..domain import DomainError


def docker_smoke(settings) -> dict:
    from ..fixtures import FIXTURES
    report={'schema_version':'tf-live-docker-smoke/v2','status':'BLOCKED','checks':[],
            'attempts':[], 'launch_attempts':0, 'containers_executed':0,
            'unknown_execution_outcomes':0, 'validations_passed':0,
            'counter_scope':'containers_executed is confirmed completed fixture output, not all starts; '
                'launch_attempts counts requested CLI invocations, not confirmed container creation',
            'real_model_called':False,'arbitrary_repository_tested':False}
    backend=DockerFixtureBackend(settings.sandbox_image_id,settings.sandbox_docker_host)
    def append_attempt(attempt, fid, label):
        report['attempts'].append({**attempt,'fixture':fid,'stage':label})
        report['launch_attempts']+=int(attempt.get('launch_attempted') is True)
        report['containers_executed']+=int(attempt.get('execution_completed') is True)
        report['unknown_execution_outcomes']+=int(attempt.get('launch_attempted') is True
                                                   and attempt.get('execution_completed') is None)
        report['validations_passed']+=int(attempt.get('validation_passed') is True)
    try:
        report['preflight']=backend.preflight()
        for fid,spec in FIXTURES.items():
            for label,source,expected in [('before',spec.original,1),('after',spec.fixed,0)]:
                try:
                    result=backend.run(ReviewedInput.from_bytes(fid,source.encode()))
                except DomainError as error:
                    attempt=getattr(error,'attempt',None)
                    if attempt is not None: append_attempt(attempt,fid,label)
                    raise
                append_attempt(result['execution_attempt'],fid,label)
                expected_failures=[spec.expected_failure] if label=='before' else []
                if (result['exit_code']!=expected or result['tests_run']!=4 or result['errors']
                        or result['skipped'] or result['failures']!=expected_failures):
                    raise DomainError('LIVE_DOCKER_SMOKE_FAILED','Fixture did not reach its expected result')
                report['checks'].append({'fixture':fid,'stage':label,'passed':True,
                                         'input_fingerprint':result['input_fingerprint'],
                                         'execution_environment':result['execution_environment']})
        report['status']='PASS'
    except DomainError as error:
        report.update(status='FAIL' if report['launch_attempts'] else 'BLOCKED',
                      error_code=error.code,message=error.message)
    return report
