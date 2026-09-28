"""Independent persistent external-system simulator, NOT the GitHub API.

Its transactionally unique operation keys and atomic base comparison are stronger
than assumptions one may make about GitHub PR creation. Results from this fixture
cannot establish real GitHub exactly-once guarantees. No network or tokens used.
"""
from __future__ import annotations
import json
import sqlite3
import uuid
from pathlib import Path
from contextlib import contextmanager
from typing import Literal
from ..artifacts import canonical, digest
from .contracts import BoundAction, DefinitiveRejection, Observation, OutcomeUnknown

Fault = Literal['none', 'response_lost', 'request_not_observed', 'lookup_unknown', 'receipt_mismatch']


class SQLiteDeliverySimulator:
    def __init__(self, path: Path, fault: Fault = 'none'):
        self.path, self.fault = path, fault
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS targets (repository TEXT PRIMARY KEY, head TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS applied_actions (
                    operation_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, receipt TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, operation_key TEXT NOT NULL);
            ''')

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(str(self.path), timeout=15)
        conn.execute('PRAGMA journal_mode=WAL')
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def submit(self, action: BoundAction, operation_key: str) -> dict:
        # Persist receipt of invocation separately from the external side effect.
        with self._connection() as connection:
            connection.execute('INSERT INTO requests(operation_key) VALUES (?)', (operation_key,))
        if self.fault == 'request_not_observed':
            raise OutcomeUnknown('Injected response loss without an observed committed action')
        request_hash = digest(canonical(action.model_dump()))
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            existing = connection.execute('SELECT request_hash,receipt FROM applied_actions WHERE operation_key=?', (operation_key,)).fetchone()
            if existing:
                if existing[0] != request_hash:
                    raise DefinitiveRejection('OPERATION_KEY_CONFLICT')
                receipt = json.loads(existing[1])
            else:
                connection.execute('INSERT OR IGNORE INTO targets(repository,head) VALUES (?,?)', (action.repository, action.base_commit))
                head = connection.execute('SELECT head FROM targets WHERE repository=?', (action.repository,)).fetchone()[0]
                if head != action.base_commit:
                    raise DefinitiveRejection('TARGET_BASE_CHANGED')
                receipt = {
                    'schema_version': 'tf-simulator-receipt/v1', 'provider': 'independent_sqlite_simulator',
                    'operation_key': operation_key, 'request_hash': request_hash,
                    'bound_action': action.model_dump(), 'external_ref': 'simulated-pr:' + str(uuid.uuid4()),
                    'real_github_pr_created': False,
                }
                connection.execute('INSERT INTO applied_actions VALUES (?,?,?)',
                                   (operation_key, request_hash, canonical(receipt).decode()))
        if self.fault == 'response_lost':
            raise OutcomeUnknown('Injected lost response AFTER independent external commit')
        if self.fault == 'receipt_mismatch':
            return {**receipt, 'request_hash': '0' * 64}
        return receipt

    def lookup(self, operation_key: str) -> Observation:
        if self.fault == 'lookup_unknown':
            return Observation('UNKNOWN')
        with self._connection() as connection:
            row = connection.execute('SELECT receipt FROM applied_actions WHERE operation_key=?', (operation_key,)).fetchone()
        return Observation('PRESENT', json.loads(row[0])) if row else Observation('NOT_OBSERVED')

    def set_head(self, repository: str, head: str) -> None:
        """Trusted test setup only; deliberately not an agent tool or public API."""
        with self._connection() as connection:
            connection.execute('INSERT INTO targets VALUES (?,?) ON CONFLICT(repository) DO UPDATE SET head=excluded.head', (repository, head))

    def metrics(self) -> dict[str, int]:
        with self._connection() as connection:
            return {
                'submit_invocations': connection.execute('SELECT count(*) FROM requests').fetchone()[0],
                'committed_actions': connection.execute('SELECT count(*) FROM applied_actions').fetchone()[0],
            }
