"""Fail-closed evidence inspection. Hashes prove integrity, not authorship.

This module checks recorded results and bindings. It does NOT execute tests and
cannot certify arbitrary patches. Live repair verification remains the worker's
separate, clean-checkout runner. M0 reports are accepted only under the explicit
reviewed-fixture policy; no general-purpose agent trust is inferred.
"""
from __future__ import annotations

import json
from typing import Any
from sqlalchemy.orm import Session
from .artifacts import ArtifactStore, canonical, digest
from .domain import DomainError
from .fixtures import fixture, grader_source
from .models import Approval, Artifact, Project, Run
from .patches import verify_reviewed_patch

POLICY_VERSION = 'reviewed-fixture-integrity-v3'
SUPPORTED_RECORDED_POLICIES = {'reviewed-fixture-integrity-v2', POLICY_VERSION}
REQUIRED_KINDS = ('patch', 'reproduction', 'regression', 'validation')


def invalid(message: str) -> None:
    raise DomainError('INVALID_EVIDENCE', message)


class EvidenceInspector:
    def __init__(self, store: ArtifactStore):
        self.store = store

    def inspect(self, session: Session, run: Run, approval: Approval | None) -> dict[str, Any]:
        if not approval or approval.run_id != run.id:
            raise DomainError('MISSING_EVIDENCE', 'A run-bound validation and approval proposal are required')
        records: dict[str, Artifact] = {}
        raw: dict[str, bytes] = {}
        for kind in REQUIRED_KINDS:
            artifact = session.get(Artifact, run.data.get(kind + '_artifact_id'))
            if not artifact:
                raise DomainError('MISSING_EVIDENCE', f'Missing {kind} artifact')
            if artifact.run_id != run.id or artifact.kind != kind:
                invalid('Artifact belongs to a different run or kind')
            records[kind] = artifact
            raw[kind] = self.store.read(artifact)
        if len({a.id for a in records.values()}) != len(REQUIRED_KINDS):
            invalid('Duplicate artifact identities')
        if approval.base_commit != run.base_commit:
            raise DomainError('STALE_APPROVAL', 'Approval base differs from the run')
        if records['patch'].sha256 != approval.patch_hash or records['validation'].sha256 != approval.validation_digest:
            raise DomainError('STALE_APPROVAL', 'Patch or validation differs from the approval')
        try:
            report = json.loads(raw['validation'])
            before = json.loads(raw['reproduction'])
            after = json.loads(raw['regression'])
        except (ValueError, UnicodeError) as error:
            raise DomainError('INVALID_EVIDENCE', 'Evidence must be valid UTF-8 JSON') from error
        if not all(isinstance(x, dict) for x in (report, before, after)):
            invalid('Evidence records must be objects')
        project = session.get(Project, run.project_id)
        if not project:
            invalid('Missing project')
        spec = fixture(project.fixture_id)
        if run.runtime != 'fixture':
            invalid('Run runtime differs from the reviewed fixture evidence')
        verify_reviewed_patch(raw['patch'], spec.original.encode(), spec.fixed.encode())
        expected = {
            'run_id': run.id, 'fixture_id': spec.id, 'objective': run.objective,
            'base_commit': run.base_commit, 'patch_hash': approval.patch_hash,
            'runtime': 'fixture', 'synthetic_fixture': True, 'verified': True,
        }
        for key, value in expected.items():
            if type(report.get(key)) is not type(value) or report.get(key) != value:
                invalid(f'Validation binding mismatch: {key}')
        if report.get('schema_version') not in ('1', '2'):
            invalid('Unsupported validation schema')
        expected_refs = {k: {'id': records[k].id, 'sha256': records[k].sha256, 'kind': k}
                         for k in ('patch', 'reproduction', 'regression')}
        refs = report.get('artifacts')
        if not isinstance(refs, list) or len(refs) != 3 or any(not isinstance(x, dict) for x in refs):
            invalid('Exactly patch, reproduction and regression references are required')
        if any(not isinstance(x.get('kind'), str) for x in refs):
            invalid('Evidence kinds must be strings')
        if len({x.get('kind') for x in refs}) != 3 or any(x != expected_refs.get(x.get('kind')) for x in refs):
            invalid('Evidence reference set is missing, duplicated or mismatched')
        if canonical(report.get('before')) != canonical(before) or canonical(report.get('after')) != canonical(after):
            invalid('Embedded test results differ from referenced result artifacts')
        mode = before.get('execution_mode')
        if mode not in {'trusted_fixture_subprocess', 'trusted_fixture_docker'} or after.get('execution_mode') != mode:
            invalid('Before/after execution backends differ')
        recorded_backend = run.data.get('execution_backend', 'reviewed_subprocess')
        if {'trusted_fixture_subprocess':'reviewed_subprocess','trusted_fixture_docker':'docker_fixture'}[mode] != recorded_backend:
            invalid('Executed backend differs from the run configuration')
        for result in (before, after):
            if type(result.get('tests_run')) is not int or result['tests_run'] != 4:
                invalid('Recorded fixture must run exactly four tests')
            if type(result.get('skipped')) is not int or result['skipped'] != 0 or result.get('errors') != []:
                invalid('Skipped tests or execution errors are not accepted')
            if type(result.get('exit_code')) is not int:
                invalid('Invalid test exit code')
            if result.get('execution_mode') != mode:
                invalid('Unexpected execution mode')
            if ('input_fingerprint' in result or mode == 'trusted_fixture_docker'
                    or run.data.get('execution_contract') == 'tf-reviewed-input/v1'):
                fingerprint = digest(canonical({'schema_version':'tf-reviewed-input/v1',
                    'fixture_id':spec.id,'source_sha256':result.get('source_sha256'),
                    'grader_sha256':result.get('grader_sha256')}))
                if result.get('input_fingerprint') != fingerprint:
                    invalid('Captured input fingerprint differs')
                process = result.get('process')
                if not isinstance(process,dict) or process.get('termination') != 'completed' or process.get('truncated') is not False:
                    invalid('Unfinished or truncated execution is not valid evidence')
        if before['exit_code'] != 1 or before.get('failures') != [spec.expected_failure]:
            invalid('Before result must contain the specific reproduced bug')
        if after['exit_code'] != 0 or after.get('failures') != []:
            invalid('After result has not passed')
        if before.get('source_sha256') != digest(spec.original.encode()) or after.get('source_sha256') != digest(spec.fixed.encode()):
            invalid('Source fingerprints are not the reviewed fixture versions')
        if before.get('grader_sha256') != after.get('grader_sha256') or before.get('grader_sha256') != digest(grader_source(spec.id).encode()):
            invalid('Grader changed between reproduction and verification')
        environment = report.get('environment')
        if not isinstance(environment, dict) or environment.get('executor') != mode:
            invalid('Missing environment binding')
        if before.get('execution_environment') != after.get('execution_environment'):
            invalid('Before/after executor configuration changed')
        if (run.data.get('execution_contract') == 'tf-reviewed-input/v1'
                and environment.get('execution_environment') != after.get('execution_environment')):
            invalid('Execution environment differs from its bound report')
        if mode == 'trusted_fixture_docker':
            config = after.get('execution_environment')
            import re
            if (not isinstance(config, dict) or config.get('rootless') is not True
                    or config.get('network') != 'none' or config.get('host_fallback') is not False
                    or config.get('read_only_input') is not True or config.get('read_only_root') is not True
                    or not re.fullmatch(r'sha256:[a-f0-9]{64}',str(config.get('image_id','')))
                    or environment.get('execution_environment') != config):
                invalid('Docker evidence does not bind the restrictive runtime configuration')
        environment_fingerprint = digest(canonical(environment))
        if report.get('schema_version') == '2':
            if report.get('environment_fingerprint') != environment_fingerprint:
                invalid('Environment fingerprint mismatch')
            if report.get('validator_policy_version') not in SUPPORTED_RECORDED_POLICIES:
                invalid('Unknown verifier policy version')
        return {
            'schema_version': 'tf-evidence-audit/v1', 'run_id': run.id,
            'integrity_and_fixture_policy_passed': True,
            'independent_tests_rerun_by_this_endpoint': False,
            'approval_authorization_checked': False,
            'policy_version': POLICY_VERSION, 'base_commit': run.base_commit,
            'patch_hash': approval.patch_hash, 'validation_digest': approval.validation_digest,
            'environment_fingerprint': environment_fingerprint,
            'artifacts': [{
                'id': a.id, 'kind': a.kind, 'sha256': a.sha256, 'byte_count': a.byte_count,
            } for a in records.values()],
            'checks': ['run_and_kind_binding', 'required_reference_set', 'artifact_hashes_and_sizes',
                       'embedded_result_binding', 'specific_failure_before', 'four_tests_pass_after',
                       'no_skips_or_errors', 'source_fingerprints', 'same_grader', 'environment_binding',
                       'patch_to_source_binding', 'runtime_binding'],
            'trust_scope': 'Recorded reviewed-fixture evidence only; hashes are not signatures or proof of arbitrary-code correctness.',
        }

    def export(self, session: Session, run: Run, approval: Approval | None) -> dict[str, Any]:
        audit = self.inspect(session, run, approval)
        content = []
        for ref in audit['artifacts']:
            artifact = session.get(Artifact, ref['id'])
            content.append({**ref, 'content': self.store.read(artifact).decode('utf-8')})
        payload = {'schema_version': 'tf-evidence-bundle/v1', 'audit': audit, 'artifacts': content}
        return {**payload, 'bundle_digest': digest(canonical(payload))}


def _verify_export_integrity(bundle: dict[str, Any]) -> dict[str, Any]:
    """Offline, read-only integrity check. No network, filesystem writes or code execution."""
    if not isinstance(bundle, dict) or bundle.get('schema_version') != 'tf-evidence-bundle/v1':
        invalid('Unsupported export format')
    if set(bundle) != {'schema_version', 'audit', 'artifacts', 'bundle_digest'}:
        invalid('Unexpected export fields')
    payload = {k: v for k, v in bundle.items() if k != 'bundle_digest'}
    if digest(canonical(payload)) != bundle['bundle_digest']:
        invalid('Export digest mismatch')
    artifacts = bundle.get('artifacts')
    audit = bundle.get('audit')
    if not isinstance(artifacts, list) or not isinstance(audit, dict) or len(artifacts) != 4:
        invalid('Incomplete export')
    refs = audit.get('artifacts')
    if not isinstance(refs, list) or len(refs) != 4:
        invalid('Incomplete exported references')
    if any(not isinstance(x, dict) or not isinstance(x.get('kind'), str) for x in [*refs, *artifacts]):
        invalid('Malformed exported artifact records')
    if {x.get('kind') for x in artifacts} != set(REQUIRED_KINDS) or {x.get('kind') for x in refs} != set(REQUIRED_KINDS):
        invalid('Incomplete exported artifact kinds')
    if len({x.get('id') for x in refs}) != 4 or len({x.get('id') for x in artifacts}) != 4:
        invalid('Duplicate exported artifact identities')
    expected = {x['kind']: x for x in refs}
    for record in artifacts:
        if not isinstance(record.get('content'), str):
            invalid('Artifact must contain UTF-8 text')
        raw = record['content'].encode('utf-8')
        ref = {k: v for k, v in record.items() if k != 'content'}
        if ref != expected.get(record['kind']) or digest(raw) != record['sha256'] or len(raw) != record['byte_count']:
            invalid('Exported artifact integrity mismatch')
    # The outer checksum alone cannot detect an internally inconsistent audit.
    by_kind = {x['kind']: x for x in artifacts}
    report = json.loads(by_kind['validation']['content'])
    if not isinstance(report, dict):
        invalid('Exported validation must be an object')
    if audit.get('schema_version') != 'tf-evidence-audit/v1':
        invalid('Unknown exported audit schema')
    for field in ('run_id', 'base_commit', 'patch_hash'):
        if audit.get(field) != report.get(field) or not isinstance(audit.get(field), str):
            invalid('Exported audit and validation bindings differ')
    if audit.get('patch_hash') != by_kind['patch']['sha256'] or audit.get('validation_digest') != by_kind['validation']['sha256']:
        invalid('Exported audit hash does not bind its content')
    expected_report_refs = [{k: by_kind[kind][k] for k in ('id', 'kind', 'sha256')}
                            for kind in ('patch', 'reproduction', 'regression')]
    report_refs = report.get('artifacts')
    if not isinstance(report_refs, list) or len(report_refs) != 3 or any(x not in expected_report_refs for x in report_refs):
        invalid('Exported report references differ')
    if len({x['kind'] for x in report_refs}) != 3:
        invalid('Duplicate exported report references')
    for field, kind in (('before', 'reproduction'), ('after', 'regression')):
        if canonical(report.get(field)) != canonical(json.loads(by_kind[kind]['content'])):
            invalid('Exported test result binding differs')
    fingerprint = digest(canonical(report.get('environment')))
    if audit.get('environment_fingerprint') != fingerprint:
        invalid('Exported environment binding differs')
    if report.get('schema_version') == '2' and report.get('environment_fingerprint') != fingerprint:
        invalid('Exported validation environment fingerprint differs')
    return {'integrity_passed': True, 'authenticity_proven': False, 'tests_rerun': False,
            'run_id': audit.get('run_id'), 'bundle_digest': bundle['bundle_digest'], 'artifact_count': 4}


def verify_export_integrity(bundle: dict[str, Any]) -> dict[str, Any]:
    """Read-only hash and internal-binding checks, never an authenticity claim."""
    try:
        return _verify_export_integrity(bundle)
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise DomainError('INVALID_EVIDENCE', 'Malformed or noncanonical evidence export') from error
