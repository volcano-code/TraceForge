"""Regression for real Docker 29 lowercase 'no such object' and strict identity."""
import pytest
from traceforge.domain import DomainError
from traceforge.execution.docker import DockerFixtureBackend
from traceforge.execution.process import ProcessResult

OWNER = 'a' * 32
NAME = 'tf-fixture-' + OWNER

class MissingContainer:
    def __init__(self, stderr):
        self.stderr = stderr
        self.calls = []
    def run(self, argv, **kwargs):
        self.calls.append(argv)
        assert 'inspect' in argv, 'A missing container must never trigger removal'
        return ProcessResult(1, '', self.stderr, 'completed', 1, len(self.stderr), False)

@pytest.mark.parametrize('message', [
    f'Error: No such object: {NAME}',
    f'error: no such object: {NAME}\n',
    f'Error: No such container: {NAME}',
    f'error: no such container: {NAME}',
    f'Error response from daemon: No such container: {NAME}',
    f'ERROR RESPONSE FROM DAEMON: NO SUCH OBJECT: {NAME}\n',
])
def test_completed_rm_confirms_exact_missing_container(message):
    fake = MissingContainer(message)
    backend = DockerFixtureBackend('sha256:'+'b'*64, 'unix:///run/user/1000/docker.sock',
                                   runner=fake, binary='/fake/docker')
    backend._cleanup(NAME, OWNER, True)
    assert len(fake.calls) == 1

@pytest.mark.parametrize('message', [
    'error: no such object: tf-fixture-'+'c'*32,
    f'Error: No such object: {NAME}-different',
    f'connection lost; Error: No such object: {NAME}',
    f'error: no such object: {NAME}\nconnection lost',
])
def test_ambiguous_or_wrong_identity_never_confirms_cleanup(message):
    fake = MissingContainer(message)
    backend = DockerFixtureBackend('sha256:'+'b'*64, 'unix:///run/user/1000/docker.sock',
                                   runner=fake, binary='/fake/docker')
    with pytest.raises(DomainError) as exc:
        backend._cleanup(NAME, OWNER, True)
    assert exc.value.code == 'SANDBOX_CLEANUP_UNCONFIRMED'
    assert len(fake.calls) == 1

@pytest.mark.parametrize('message', [f'Error: No such object: {NAME}', f'error: no such object: {NAME}'])
def test_unknown_invocation_still_requires_reconciliation(message):
    fake = MissingContainer(message)
    backend = DockerFixtureBackend('sha256:'+'b'*64, 'unix:///run/user/1000/docker.sock',
                                   runner=fake, binary='/fake/docker')
    with pytest.raises(DomainError) as exc:
        backend._cleanup(NAME, OWNER, False)
    assert exc.value.code == 'SANDBOX_CLEANUP_UNCONFIRMED'
