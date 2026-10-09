#!/usr/bin/env python3
"""Independent Docker environment probe; never imports or runs TraceForge code."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import uuid

PAYLOAD = r'''
import errno, json, os
from pathlib import Path
s = dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
cg = Path('/sys/fs/cgroup')
quota, period = (cg/'cpu.max').read_text().split()
result = {
    'uid': os.getuid(), 'cap_eff': int(s['CapEff'].strip(),16),
    'no_new_privileges': s['NoNewPrivs'].strip() == '1',
    'memory_max': (cg/'memory.max').read_text().strip(),
    'swap_max': (cg/'memory.swap.max').read_text().strip(),
    'pids_max': (cg/'pids.max').read_text().strip(),
    'cpu_quota': quota, 'cpu_period': period,
    'network_interfaces': sorted(p.name for p in Path('/sys/class/net').iterdir()),
    'docker_socket_visible': Path('/var/run/docker.sock').exists(),
}
try:
    Path('/var/tmp/traceforge-environment-probe').write_text('must fail')
    result['readonly_write_errno'] = None
except OSError as error:
    result['readonly_write_errno'] = error.errno
Path('/tmp/traceforge-probe').write_text('ephemeral')
result['tmpfs_write_ok'] = Path('/tmp/traceforge-probe').read_text() == 'ephemeral'
print(json.dumps(result,sort_keys=True))
assert result['uid'] == 65534
assert result['cap_eff'] == 0 and result['no_new_privileges']
assert result['memory_max'] == '134217728' and result['swap_max'] == '0'
assert result['pids_max'] == '64'
assert quota != 'max' and int(quota) * 2 == int(period)
assert result['network_interfaces'] == ['lo']
assert not result['docker_socket_visible']
assert result['readonly_write_errno'] == errno.EROFS
assert result['tmpfs_write_ok']
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--allow-image-pull', action='store_true')
    args = parser.parse_args()
    args.out.mkdir(mode=0o700, parents=False, exist_ok=False)
    result = {'schema': 'tf-docker-environment/v1', 'status': 'BLOCKED',
              'environment_only': True, 'product_code_tested': False,
              'provider_calls': 0, 'container_created': False,
              'container_started': False, 'cleanup_confirmed': None}
    owner = uuid.uuid4().hex
    name = 'tf-env-' + owner
    stage = 'preflight'
    created_id = None
    try:
        if os.getuid() == 0:
            raise RuntimeError('RUN_AS_NORMAL_USER')
        if not shutil.which('docker'):
            raise RuntimeError('DOCKER_CLI_MISSING')
        runtime_dir = Path('/run/user') / str(os.getuid())
        endpoint = 'unix://' + str(runtime_dir / 'docker.sock')
        info = (runtime_dir / 'docker.sock').lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError('ROOTLESS_SOCKET_OWNERSHIP_INVALID')
        with tempfile.TemporaryDirectory(prefix='tf-env-client-') as config:
            def docker(*command: str, seconds: int = 40) -> str:
                completed = subprocess.run(
                    ['docker', '--host', endpoint, '--config', config, *command],
                    env={'PATH': os.environ['PATH'], 'HOME': config, 'LANG': 'C.UTF-8'},
                    text=True, capture_output=True, timeout=seconds, check=False)
                if completed.returncode != 0:
                    raise RuntimeError('DOCKER_COMMAND_FAILED:' + command[0])
                return completed.stdout.strip()

            daemon = json.loads(docker('info', '--format', '{{json .}}'))
            flags = ('MemoryLimit','SwapLimit','PidsLimit','CpuCfsQuota','CpuCfsPeriod')
            if ('name=rootless' not in daemon.get('SecurityOptions', [])
                    or daemon.get('CgroupVersion') != '2'
                    or daemon.get('CgroupDriver') != 'systemd'
                    or any(daemon.get(key) is not True for key in flags)):
                raise RuntimeError('ROOTLESS_RESOURCE_CONTROLS_UNAVAILABLE')
            result['daemon'] = {key: daemon.get(key) for key in
                ('ServerVersion','CgroupVersion','CgroupDriver','SecurityOptions',*flags)}
            result['host'] = endpoint
            result['compose_version'] = docker('compose', 'version', '--short')
            stage = 'image'
            if args.allow_image_pull:
                docker('pull', 'python:3.13-slim', seconds=240)
            image = json.loads(docker('image', 'inspect', 'python:3.13-slim'))[0]
            image_id = image['Id']
            if not re.fullmatch(r'sha256:[a-f0-9]{64}', image_id) or image['Os'] != 'linux':
                raise RuntimeError('IMAGE_ID_INVALID')
            if image.get('Config', {}).get('Volumes'):
                raise RuntimeError('IMPLICIT_IMAGE_VOLUMES_FORBIDDEN')
            result['image_id'] = image_id
            result['repo_digests'] = image.get('RepoDigests', [])
            stage = 'create'
            try:
                created_id = docker('create', '--name', name, '--pull=never',
                    '--label', 'traceforge.environment.probe=' + owner,
                    '--label', 'traceforge.role=environment-probe',
                    '--network=none', '--read-only', '--cap-drop=ALL',
                    '--security-opt=no-new-privileges=true', '--user=65534:65534',
                    '--ipc=private', '--cpus=0.5', '--memory=128m', '--memory-swap=128m',
                    '--pids-limit=64', '--ulimit=core=0:0',
                    '--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777',
                    '--env=HOME=/tmp', '--env=LANG=C.UTF-8',
                    '--entrypoint=python3', image_id, '-I', '-B', '-c', PAYLOAD)
                if not re.fullmatch(r'[a-f0-9]{64}', created_id):
                    raise RuntimeError('CONTAINER_ID_INVALID')
                result.update(container_created=True, container_id=created_id)
                stage = 'execute'
                result['container_start_attempted'] = True
                output = docker('start', '--attach', created_id, seconds=35)
                observation = json.loads(output)
                state = json.loads(docker('inspect', '--format', '{{json .State}}', created_id))
                result['observation'] = observation
                result['container_started'] = True
                if state.get('ExitCode') != 0 or state.get('Running') is not False:
                    raise RuntimeError('CONTAINER_PROBE_FAILED')
                expected = {'uid':65534,'cap_eff':0,'no_new_privileges':True,
                    'memory_max':'134217728','swap_max':'0','pids_max':'64',
                    'network_interfaces':['lo'],'docker_socket_visible':False,
                    'readonly_write_errno':30,'tmpfs_write_ok':True}
                if any(observation.get(k) != v for k,v in expected.items()):
                    raise RuntimeError('OBSERVATION_MISMATCH')
                if observation['cpu_quota'] == 'max' or int(observation['cpu_quota'])*2 != int(observation['cpu_period']):
                    raise RuntimeError('CPU_LIMIT_NOT_ENFORCED')
                result['checks_passed'] = list(expected) + ['cpu_limit','rootless_daemon','compose_cli']
                result['status'] = 'PASS'
            finally:
                # Only this probe's randomly named, labelled container can be removed.
                stage_before_cleanup = stage
                stage = 'cleanup'
                matches = docker('ps','--all','--no-trunc','--filter','name=^/'+name+'$',
                                 '--format','{{.ID}}').splitlines()
                if matches:
                    if len(matches) != 1 or (created_id is not None and matches[0] != created_id):
                        raise RuntimeError('CLEANUP_IDENTITY_MISMATCH')
                    record = json.loads(docker('inspect', matches[0]))[0]
                    if (record['Name'] != '/' + name or
                        record.get('Config',{}).get('Labels',{}).get('traceforge.environment.probe') != owner):
                        raise RuntimeError('CLEANUP_OWNER_MISMATCH')
                    docker('rm', '--force', matches[0])
                remaining = docker('ps','--all','--no-trunc','--filter','name=^/'+name+'$',
                                   '--format','{{.ID}}')
                result['cleanup_confirmed'] = remaining == ''
                if remaining:
                    raise RuntimeError('CLEANUP_UNCONFIRMED')
                stage = stage_before_cleanup
            if result['status'] == 'PASS':
                (args.out / 'traceforge-docker.env').write_text(
                    'export TF_SANDBOX_DOCKER_HOST=' + endpoint + '\n' +
                    'export TF_SANDBOX_IMAGE_ID=' + image_id + '\n', encoding='utf-8')
    except Exception as error:
        result.update(status='FAIL' if result['container_created'] else 'BLOCKED',
                      failure_stage=stage, error_type=type(error).__name__,
                      error_code=str(error) if isinstance(error, RuntimeError) else type(error).__name__)
    finally:
        (args.out / 'environment-result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
