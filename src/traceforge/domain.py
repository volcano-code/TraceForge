from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .models import Run, RunEvent, now

class Status(StrEnum):
    QUEUED="QUEUED"
    PREPARING="PREPARING"
    REPRODUCING="REPRODUCING"
    PATCHING="PATCHING"
    VERIFYING="VERIFYING"
    WAITING_APPROVAL="WAITING_APPROVAL"
    APPROVED="APPROVED"
    DELIVERED_LOCAL="DELIVERED_LOCAL"
    DELIVERING="DELIVERING"
    DELIVERY_IN_DOUBT="DELIVERY_IN_DOUBT"
    DELIVERED_SIMULATED="DELIVERED_SIMULATED"
    DELIVERY_BLOCKED="DELIVERY_BLOCKED"
    REJECTED="REJECTED"
    FAILED="FAILED"
    CANCELLED="CANCELLED"

EXECUTION_STEPS = [Status.QUEUED,Status.PREPARING,Status.REPRODUCING,Status.PATCHING,Status.VERIFYING]
STOP_STATES = {Status.WAITING_APPROVAL,Status.APPROVED,Status.DELIVERED_LOCAL,
               Status.REJECTED,Status.FAILED,Status.CANCELLED,Status.DELIVERING,
               Status.DELIVERY_IN_DOUBT,Status.DELIVERED_SIMULATED,Status.DELIVERY_BLOCKED}
ALLOWED = {
    Status.QUEUED:{Status.PREPARING}, Status.PREPARING:{Status.REPRODUCING},
    Status.REPRODUCING:{Status.PATCHING}, Status.PATCHING:{Status.VERIFYING},
    Status.VERIFYING:{Status.WAITING_APPROVAL},
    Status.WAITING_APPROVAL:{Status.APPROVED,Status.REJECTED},
    Status.APPROVED:{Status.DELIVERED_LOCAL,Status.DELIVERING},
    Status.DELIVERING:{Status.DELIVERY_IN_DOUBT,Status.DELIVERED_SIMULATED,Status.DELIVERY_BLOCKED},
    Status.DELIVERY_IN_DOUBT:{Status.DELIVERED_SIMULATED},
}

class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status

class StrictModel(BaseModel):
    model_config=ConfigDict(extra="forbid")

class RunCreate(StrictModel):
    project_id: str = Field(min_length=1,max_length=36)
    objective: str = Field(min_length=5,max_length=4000)
    runtime: Literal["fixture"]="fixture"

class ApprovalDecision(StrictModel):
    decision: Literal["APPROVED","REJECTED"]
    base_commit: str = Field(pattern=r"^[a-f0-9]{40,64}$")
    patch_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    validation_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    delivery_kind: Literal["LOCAL_RECEIPT","SIMULATED_PR"]="LOCAL_RECEIPT"
    comment: str=Field(default="",max_length=2000)

class DeliveryRequest(StrictModel):
    approval_id: str = Field(min_length=1,max_length=36)


def emit(session, run: Run, kind: str, payload: dict | None = None, actor: str="control") -> None:
    run.event_seq += 1
    session.add(RunEvent(run_id=run.id, sequence=run.event_seq, state_version=run.version,
                         event_type=kind, actor=actor, payload=payload or {}))


def transition(session, run: Run, target: Status, payload: dict | None = None) -> None:
    source=Status(run.status)
    exceptional=target in {Status.FAILED,Status.CANCELLED} and source not in {
        Status.DELIVERED_LOCAL,Status.DELIVERED_SIMULATED,Status.DELIVERY_BLOCKED,
        Status.DELIVERING,Status.DELIVERY_IN_DOUBT,Status.CANCELLED,Status.REJECTED,Status.FAILED}
    if target not in ALLOWED.get(source,set()) and not exceptional:
        raise DomainError("INVALID_TRANSITION",f"{source} -> {target} is forbidden")
    run.status=target.value; run.version+=1; run.updated_at=now()
    emit(session,run,"PHASE_CHANGED",{"from":source.value,"to":target.value,**(payload or {})})
