"""Fail-closed Docker runner for reviewed fixtures only.

Requires an already-installed LOCAL rootless Docker daemon and a cached exact
image ID. No image pull/build, remote daemon, host fallback, credential mount,
control DB mount or Docker socket mount occurs here. Contract tests do not
establish live container isolation: run the explicit live smoke on a Docker host.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from .inputs import ReviewedInput
from .process import BoundedProcessRunner, ProcessResult
from .reviewed import decode_result
from ..domain import DomainError

IMAGE_PATTERN = r'^sha256:[a-f0-9]{64}$'


class DockerAttemptError(DomainError):
    """Preserve observed lifecycle even if validation or cleanup subsequently fails."""
    def __init__(self, error: DomainError, attempt: dict):
        super().__init__(error.code, error.message, error.status)
        self.attempt = dict(attempt)



class DockerFixtureBackend:
    name = 'docker_fixture'
    def __init__(self, image_id: str, docker_host: str, *, runner=None, binary: str | None = None):
        self.image_id, self.docker_host = image_id, docker_host
        self.runner = runner or BoundedProcessRunner()
        self.binary = binary if binary is not None else shutil.which('docker')

    def _call(self, args: list[str], *, timeout: float = 5, cancelled=None) -> ProcessResult:
        if not self.binary:
            raise DomainError('DOCKER_UNAVAILABLE', 'Docker CLI is not installed; host fallback is forbidden', 503)
        with tempfile.TemporaryDirectory(prefix='traceforge-docker-client-') as tmp:
            root = Path(tmp)
            # Explicit empty client config: no registry credentials or ambient context.
            argv = [self.binary,'--host',self.docker_host,'--config',tmp,*args]
            return self.runner.run(argv,cwd=root,env={'PATH':os.defpath,'HOME':tmp,'LANG':'C.UTF-8'},
                                   timeout=timeout,max_output_bytes=262144,cancelled=cancelled)

    def preflight(self) -> dict:
        if os.name != 'posix':
            raise DomainError('PLATFORM_UNSUPPORTED', 'This runner currently requires Linux/WSL', 503)
        if not self.binary:
            raise DomainError('DOCKER_UNAVAILABLE', 'Docker CLI is not installed; host fallback is forbidden', 503)
        if not re.fullmatch(IMAGE_PATTERN,self.image_id):
            raise DomainError('UNPINNED_SANDBOX_IMAGE','Use a cached exact sha256 image ID, never a floating tag',503)
        if (not self.docker_host.startswith('unix:///') or any(x in self.docker_host for x in ('\n','\r','\0','..'))):
            raise DomainError('UNSAFE_DOCKER_HOST','Only an explicitly configured local Unix socket is accepted',503)
        response = self._call(['info','--format','{{json .}}'])
        if response.termination != 'completed' or response.exit_code != 0:
            raise DomainError('DOCKER_UNAVAILABLE','Local Docker daemon could not be inspected',503)
        try:
            info = json.loads(response.stdout)
            options = info.get('SecurityOptions',[])
            if not isinstance(options,list) or 'name=rootless' not in options:
                raise DomainError('ROOTLESS_REQUIRED','This execution slice requires rootless Docker',503)
            # Rootless alone does not guarantee that resource flags are enforced.
            # Docker can silently ignore them when cgroup delegation is unavailable.
            limits = ('MemoryLimit', 'SwapLimit', 'PidsLimit', 'CpuCfsQuota', 'CpuCfsPeriod')
            if (info.get('CgroupVersion') != '2' or info.get('CgroupDriver') != 'systemd'
                    or any(info.get(flag) is not True for flag in limits)):
                raise DomainError('CGROUP_LIMITS_UNAVAILABLE',
                    'Rootless cgroup v2/systemd with CPU, memory, swap and PID limits is required',503)
            image_response = self._call(['image','inspect','--format','{{json .}}',self.image_id])
            if image_response.termination != 'completed' or image_response.exit_code != 0:
                raise DomainError('SANDBOX_IMAGE_MISSING','Pinned image is not cached; automatic pulling is disabled',503)
            image = json.loads(image_response.stdout)
            if image.get('Id') != self.image_id or image.get('Os') != 'linux':
                raise DomainError('SANDBOX_IMAGE_MISMATCH','Only the exact cached Linux image is accepted',503)
            config = image.get('Config')
            if not isinstance(config,dict) or config.get('Volumes'):
                raise DomainError('UNSAFE_IMAGE_VOLUMES','Images declaring implicit volumes are not allowed',503)
        except (ValueError,AttributeError,TypeError) as error:
            raise DomainError('DOCKER_INSPECTION_INVALID','Docker inspection did not return the required fields',503) from error
        return {'backend':self.name,'available':True,'image_id':self.image_id,
                'server_version':str(info.get('ServerVersion','unknown')),'rootless':True,
                'network':'none','read_only_root':True,'host_fallback':False,
                'cgroup_version':'2','resource_controls_reported':True,'live_isolation_verified':False,
                'scope':'reviewed fixtures only; preflight is not a live isolation proof'}

    def launch_args(self, staged: Path, name: str, owner: str) -> list[str]:
        if not re.fullmatch(r'tf-fixture-[a-f0-9]{32}',name) or not re.fullmatch(r'[a-f0-9]{32}',owner):
            raise ValueError('Invalid internally generated container identity')
        if not staged.is_absolute() or any(c in str(staged) for c in (',','\n','\r','\0')):
            raise DomainError('UNSAFE_MOUNT_PATH','Input staging path cannot be represented safely')
        return ['run','--rm','--pull=never','--name',name,
                '--label',f'traceforge.owner={owner}','--label','traceforge.role=reviewed-fixture',
                '--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges=true',
                '--user=65534:65534','--ipc=private','--pids-limit=64','--cpus=1',
                '--memory=256m','--memory-swap=256m','--ulimit=nofile=128:128','--ulimit=core=0:0',
                '--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777',
                '--mount',f'type=bind,src={staged},dst=/input,readonly',
                '--workdir=/tmp','--env=HOME=/tmp','--env=LANG=C.UTF-8','--entrypoint=python3',
                self.image_id,'-I','/input/runner.py','/input/module.py']

    def _cleanup(self,name: str,owner: str,completed: bool) -> None:
        check = self._call(['inspect','--format','{{json .Config.Labels}}',name])
        if check.termination != 'completed':
            raise DomainError('SANDBOX_CLEANUP_UNCONFIRMED','Container cleanup could not be verified',503)
        if check.exit_code != 0:
            # Docker versions differ in casing. Accept only an exact daemon
            # absence message for THIS container; substring matches can confuse
            # a different object or a transport failure with confirmed cleanup.
            missing_messages = {
                f'{prefix} no such {kind}: {name}'.casefold()
                for prefix in ('error:', 'error response from daemon:')
                for kind in ('object', 'container')
            }
            missing = check.stderr.strip().casefold() in missing_messages
            if completed and missing:
                return  # Completed --rm invocation, then confirmed missing by the daemon.
            raise DomainError('SANDBOX_CLEANUP_UNCONFIRMED','Do not retry until a possible orphan is reconciled',503)
        try:
            labels = json.loads(check.stdout)
        except ValueError as error:
            raise DomainError('SANDBOX_CLEANUP_UNCONFIRMED','Malformed ownership lookup',503) from error
        if not isinstance(labels,dict) or labels.get('traceforge.owner') != owner:
            raise DomainError('SANDBOX_OWNER_MISMATCH','Refusing to remove a container not owned by this attempt',503)
        removal = self._call(['rm','--force',name])
        if removal.termination != 'completed' or removal.exit_code != 0:
            raise DomainError('SANDBOX_CLEANUP_UNCONFIRMED','Container removal not confirmed',503)

    def run(self,snapshot: ReviewedInput,*,cancelled=None) -> dict:
        owner = uuid.uuid4().hex
        name = 'tf-fixture-'+owner
        attempt = {'schema_version':'tf-execution-attempt/v1', 'attempt_id':owner,
                   'container_name':name, 'container_id':None,
                   'launch_attempted':False, 'invocation_completed':None,
                   'execution_completed':None, 'validation_passed':None,
                   'cleanup_confirmed':None, 'failure_stage':None,
                   'execution_error':None, 'cleanup_error':None,
                   'observation_scope':'CLI invocation and validated reviewed-fixture output; '
                       'null means unknown, not false. Not a persisted orphan ledger.'}
        stage, result, decoded, failure = 'input', None, None, None
        try:
            snapshot.validate()
            stage = 'preflight'
            readiness = self.preflight()
            environment = {'backend':self.name,'snapshot_staged':True,'image_id':self.image_id,
                           'server_version':readiness['server_version'],'rootless':True,'network':'none',
                           'read_only_input':True,'read_only_root':True,'host_fallback':False}
            stage = 'staging'
            with snapshot.staged() as root:
                try:
                    args = self.launch_args(root,name,owner)
                    stage = 'launch'
                    # This marks a requested invocation, NOT proof a container started.
                    attempt['launch_attempted'] = True
                    result = self._call(args,timeout=10,cancelled=cancelled)
                    attempt['invocation_completed'] = result.termination == 'completed'
                    stage = 'decode' if result.termination == 'completed' else 'execution'
                    decoded = decode_result(result,snapshot,'trusted_fixture_docker',environment)
                    # A completed CLI alone is insufficient; require a valid grader result.
                    attempt['execution_completed'] = True
                    attempt['validation_passed'] = decoded['exit_code'] == 0
                except DomainError as error:
                    failure = error
                    attempt['failure_stage'] = stage
                    attempt['execution_error'] = error.code
                finally:
                    if attempt['launch_attempted']:
                        try:
                            self._cleanup(name,owner,result is not None and result.termination == 'completed'
                                          and result.exit_code in (0,1))
                            attempt['cleanup_confirmed'] = True
                        except DomainError as error:
                            attempt['cleanup_error'] = error.code
                            attempt['failure_stage'] = 'cleanup'
                            failure = error  # Preserve execution_error as well; never hide unsafe cleanup.
            if failure is not None:
                raise failure
        except DomainError as error:
            attempt['failure_stage'] = attempt['failure_stage'] or stage
            raise DockerAttemptError(error,attempt) from error
        except Exception as error:
            attempt['failure_stage'] = attempt['failure_stage'] or stage
            wrapped = DomainError('DOCKER_DRIVER_ERROR','Unexpected driver failure; inspect the recorded attempt',503)
            raise DockerAttemptError(wrapped,attempt) from error
        return {**decoded, 'execution_attempt':attempt}
