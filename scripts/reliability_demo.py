"""Run real, offline state/side-effect experiments in disposable fixture systems.

No LLM, GitHub or user repositories are contacted. The external simulator has its
own SQLite commit boundary. The crash case terminates a distinct Python process.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sqlalchemy import select
from traceforge.config import Settings
from traceforge.db import Database
from traceforge.delivery.contracts import DeliveryCrash
from traceforge.delivery.service import DeliveryService
from traceforge.delivery.simulator import SQLiteDeliverySimulator
from traceforge.domain import ApprovalDecision, RunCreate
from traceforge.evidence import EvidenceInspector, verify_export_integrity
from traceforge.models import Approval, Base, Operation, Project, Run, RunEvent, now
from traceforge.services import Services
from traceforge.workflow import Worker


def settings_for(path: Path) -> Settings:
    return Settings(_env_file=None, database_url='sqlite:///' + str(path / 'control.sqlite'), data_dir=path)


def make_run(svc: Services):
    with svc.db.session() as session:
        project = session.scalar(select(Project).where(Project.fixture_id == 'pagination'))
    run = svc.create_run(RunCreate(project_id=project.id, objective='受控故障实验：验证分页补丁并检查交付恢复，不调用真实模型。'), secrets.token_hex(16))
    Worker(svc).execute_one()
    with svc.db.session() as session:
        run = session.get(Run, run.id)
        assert run.status == 'WAITING_APPROVAL', run.failure_code
        approval = session.scalar(select(Approval).where(Approval.run_id == run.id))
    svc.decide(approval.id, ApprovalDecision(decision='APPROVED', base_commit=approval.base_commit,
               patch_hash=approval.patch_hash, validation_digest=approval.validation_digest,
               delivery_kind='SIMULATED_PR'), 'reviewer')
    return run, approval


def run_experiments(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix='traceforge-reliability-') as temp:
        root = Path(temp)
        settings = settings_for(root)
        database = Database(settings)
        Base.metadata.create_all(database.engine)
        svc = Services(settings, database)
        svc.seed()
        for scenario in ('normal', 'response_lost', 'process_crash', 'not_observed', 'target_changed', 'lookup_unknown'):
            run, approval = make_run(svc)
            fault = {'response_lost': 'response_lost', 'not_observed': 'request_not_observed',
                     'lookup_unknown': 'response_lost'}.get(scenario, 'none')
            external_path = root / 'providers' / (scenario + '.sqlite')
            provider = SQLiteDeliverySimulator(external_path, fault)
            delivery = DeliveryService(svc, provider)
            if scenario == 'target_changed': provider.set_head('fixture:pagination', 'f' * 40)
            if scenario == 'process_crash':
                child = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child-submit',
                                        str(root), run.id, approval.id, str(external_path)],
                                       capture_output=True, timeout=30)
                assert child.returncode == 86, child.stderr.decode()
                with database.transaction() as session:
                    operation = session.scalar(select(Operation).where(Operation.run_id == run.id))
                    assert operation.status == 'EXECUTING'
                    operation.lease_until = now() - 1  # explicit, deterministic test clock boundary
                first_status = operation.status
            else:
                operation = delivery.submit(run.id, approval.id, 'reviewer')
                first_status = operation.status
            if scenario in ('response_lost', 'process_crash', 'not_observed', 'lookup_unknown'):
                # Recreate both service and provider from persisted state.
                observer = SQLiteDeliverySimulator(external_path, 'lookup_unknown' if scenario == 'lookup_unknown' else 'none')
                restarted = DeliveryService(Services(settings, database), observer)
                operation = restarted.reconcile(run.id, operation.id, 'reviewer')
                assert restarted.submit(run.id, approval.id, 'reviewer').id == operation.id
            expected = {'not_observed': 'IN_DOUBT', 'lookup_unknown': 'IN_DOUBT', 'target_changed': 'BLOCKED'}.get(scenario, 'SUCCEEDED')
            assert operation.status == expected
            metrics = provider.metrics()
            assert metrics['submit_invocations'] == 1
            assert metrics['committed_actions'] == (0 if scenario in ('not_observed', 'target_changed') else 1)
            results.append({'scenario': scenario, 'first_status': first_status, 'final_status': operation.status,
                            'external_submit_invocations': metrics['submit_invocations'],
                            'external_committed_actions': metrics['committed_actions'],
                            'real_process_terminated': scenario == 'process_crash',
                            'lease_expiry_injected_for_test': scenario == 'process_crash',
                            'passed': True, 'real_github_pr_created': False})
            with database.session() as session:
                stored = session.get(Run, run.id)
                events = [{'sequence': e.sequence, 'event_type': e.event_type, 'payload': e.payload}
                          for e in session.scalars(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.sequence))]
                if scenario == 'response_lost':
                    bundle = EvidenceInspector(svc.store).export(session, stored, session.get(Approval, approval.id))
                    assert verify_export_integrity(bundle)['integrity_passed']
                    (output / 'evidence-bundle.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2))
                    (output / 'response-lost-events.json').write_text(json.dumps(events, ensure_ascii=False, indent=2))
        database.close()
    report = {'mode': 'independent_sqlite_simulator', 'real_llm_called': False,
              'real_github_pr_created': False, 'scenario_count': len(results), 'all_passed': True,
              'scope': 'No real-provider exactly-once guarantee; NOT_OBSERVED never resends automatically.', 'results': results}
    (output / 'reliability-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports' / 'local')
    parser.add_argument('--child-submit', nargs=4, metavar=('ROOT', 'RUN', 'APPROVAL', 'PROVIDER'))
    args = parser.parse_args()
    if args.child_submit:
        directory, run_id, approval_id, provider_path = args.child_submit
        settings = settings_for(Path(directory))
        database = Database(settings)
        svc = Services(settings, database)
        try:
            DeliveryService(svc, SQLiteDeliverySimulator(Path(provider_path))).submit(
                run_id, approval_id, 'reviewer', crash_after_external_commit=True)
        except DeliveryCrash:
            os._exit(86)  # deliberate abrupt process termination, not just a failed test assertion
        raise SystemExit('Expected crash did not occur')
    run_experiments(args.output)


if __name__ == '__main__': main()
