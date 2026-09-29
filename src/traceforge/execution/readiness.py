"""Honest local readiness report. Never emits environment credential values."""
from __future__ import annotations
import importlib.metadata
import os
import shutil
from ..domain import DomainError


def _version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def make_backend(settings):
    from .reviewed import ReviewedSubprocessBackend
    from .docker import DockerFixtureBackend
    if settings.execution_backend == 'reviewed_subprocess':
        return ReviewedSubprocessBackend()
    if settings.execution_backend == 'docker_fixture':
        return DockerFixtureBackend(settings.sandbox_image_id,settings.sandbox_docker_host)
    raise DomainError('UNSUPPORTED_EXECUTION_BACKEND','Unknown execution backend; no fallback is allowed',503)


def readiness_report(settings, *, probe_docker: bool = False) -> dict:
    versions={name:_version(name) for name in ('openhands-sdk','openhands-tools','openhands-workspace','langgraph')}
    matched = bool(versions['openhands-sdk'] and versions['openhands-sdk']==versions['openhands-tools'])
    docker={'cli_present':shutil.which('docker') is not None,'probe_executed':False,'available':False}
    if probe_docker:
        from .docker import DockerFixtureBackend
        docker['probe_executed']=True
        try:
            docker.update(DockerFixtureBackend(settings.sandbox_image_id,settings.sandbox_docker_host).preflight())
        except DomainError as error:
            docker.update(error_code=error.code,message=error.message)
    # Capability inspection never attests that the separate live gate has run.
    docker['live_gate_verified'] = False
    reasons=['LIVE_DOCKER_GATE_NOT_PASSED']
    if not matched: reasons.append('OPENHANDS_MATCHED_PACKAGES_MISSING')
    reasons.extend(['OPENHANDS_EXECUTOR_NOT_INTEGRATED','LIVE_MODEL_TOOL_LOOP_NOT_VALIDATED',
                    'ARBITRARY_REPOSITORY_VALIDATOR_NOT_IMPLEMENTED'])
    return {'schema_version':'tf-readiness/v1','execution_backend':settings.execution_backend,
            'local_reviewed_fixture_available':os.name=='posix','docker':docker,'sdk_packages':versions,
            'openhands_packages_matched':matched,'coding_agent_ready':False,
            'arbitrary_repository_enabled':False,'real_github_delivery_enabled':False,
            'blocking_reasons':reasons,'scope':'Capability preflight, not a benchmark or a security certification'}
