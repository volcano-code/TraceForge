from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field


class BoundAction(BaseModel):
    """Constructed by the trusted service, never accepted directly from an agent."""
    model_config = ConfigDict(extra='forbid', frozen=True)
    schema_version: Literal['tf-action/v1'] = 'tf-action/v1'
    kind: Literal['SIMULATED_PR'] = 'SIMULATED_PR'
    destination: Literal['independent_sqlite_simulator'] = 'independent_sqlite_simulator'
    repository: str = Field(pattern=r'^fixture:[a-z0-9-]+$')
    run_id: str
    approval_id: str
    base_commit: str = Field(pattern=r'^[a-f0-9]{40,64}$')
    patch_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    validation_digest: str = Field(pattern=r'^[a-f0-9]{64}$')


@dataclass(frozen=True)
class Observation:
    state: Literal['PRESENT', 'NOT_OBSERVED', 'UNKNOWN']
    receipt: dict[str, Any] | None = None


class OutcomeUnknown(Exception):
    """The request may have taken effect. Never blindly resubmit."""


class DefinitiveRejection(Exception):
    """Provider contract explicitly guarantees the requested write did NOT occur."""


class DeliveryCrash(BaseException):
    """Test-only crash at the exact external-commit/local-commit boundary."""


class DeliveryProvider(Protocol):
    def submit(self, action: BoundAction, operation_key: str) -> dict[str, Any]: ...
    def lookup(self, operation_key: str) -> Observation: ...
