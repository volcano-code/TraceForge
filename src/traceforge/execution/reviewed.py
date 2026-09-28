"""Reviewed fixture backends; neither permits arbitrary repository code."""
from __future__ import annotations
import json
import sys
from .inputs import ReviewedInput
from .process import BoundedProcessRunner, ProcessResult
from ..domain import DomainError


def decode_result(result: ProcessResult, snapshot: ReviewedInput, mode: str,
                  environment: dict) -> dict:
    if result.termination != 'completed':
        raise DomainError('EXECUTION_' + result.termination.upper(), 'Execution stopped by a runtime boundary')
    try:
        record = json.loads(result.stdout)
    except (ValueError, TypeError) as error:
        raise DomainError('INVALID_TEST_OUTPUT', 'Runner did not produce a valid test result') from error
    if not isinstance(record, dict) or type(record.get('tests_run')) is not int or record['tests_run'] != 4:
        raise DomainError('INVALID_TEST_OUTPUT', 'All four reviewed tests must have executed')
    if type(record.get('skipped')) is not int or record['skipped'] != 0:
        raise DomainError('INVALID_TEST_OUTPUT', 'Skipped tests are not a valid fixture result')
    for key in ('failures','errors'):
        if not isinstance(record.get(key), list) or any(not isinstance(x, str) for x in record[key]):
            raise DomainError('INVALID_TEST_OUTPUT', 'Malformed test outcome')
    expected_exit = 1 if record['failures'] or record['errors'] else 0
    if result.exit_code != expected_exit:
        raise DomainError('INVALID_TEST_OUTPUT', 'Process status contradicts its test result')
    return {**record, 'exit_code':result.exit_code, 'source_sha256':snapshot.manifest['source_sha256'],
            'grader_sha256':snapshot.manifest['grader_sha256'], 'execution_mode':mode,
            'input_fingerprint':snapshot.fingerprint, 'execution_environment':environment,
            'process':{'termination':result.termination,'elapsed_ms':result.elapsed_ms,
                       'output_bytes':result.observed_output_bytes,'truncated':result.truncated}}


class ReviewedSubprocessBackend:
    name = 'reviewed_subprocess'
    def __init__(self, runner=None):
        self.runner = runner or BoundedProcessRunner()

    def preflight(self) -> dict:
        import os
        if os.name != 'posix':
            raise DomainError('PLATFORM_UNSUPPORTED','Use Linux or WSL for the bounded local runner',503)
        return {'backend':self.name,'available':True,'security_isolation':False}

    def run(self, snapshot: ReviewedInput, *, cancelled=None) -> dict:
        from ..fixtures import safe_env
        self.preflight()
        with snapshot.staged() as root:
            result = self.runner.run([sys.executable,'-I',str(root/'runner.py'),str(root/'module.py')],
                                     cwd=root,env=safe_env(root),timeout=10,max_output_bytes=262144,
                                     cancelled=cancelled)
        return decode_result(result,snapshot,'trusted_fixture_subprocess',
                             {'backend':self.name,'snapshot_staged':True,'security_isolation':False})
