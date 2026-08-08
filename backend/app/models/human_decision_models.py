"""Pydantic contracts for the Human Override Controls feature (FEAT-006).

These models are the API/engine contracts documented in
``features/F6-human-override-controls/2_tech_spec.md`` §2.1 / §3.2.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.resolution_models import ResolutionAction


def _reject_blank(value: str) -> str:
    """Refuse empty / whitespace-only strings (BR 'Agents must be identifiable')."""
    if value is None or not value.strip():
        raise ValueError("must not be blank")
    return value


class HumanAction(str, Enum):
    """The three human decisions an agent can record on an escalated ticket.

    APPROVE  - accept the system's suggested action as final (US-01)
    OVERRIDE - replace the suggested action with a different one (US-02)
    REJECT   - decline the suggestion; never applied (US-03)
    """

    APPROVE = "approve"
    OVERRIDE = "override"
    REJECT = "reject"


class ApproveRequest(BaseModel):
    """Request body for the approve endpoint (US-01)."""

    agent_id: str = Field(
        ...,
        min_length=1,
        examples=["agent-7"],
        description="Identity of the acting agent; required for the audit trail (BR 'Agents must be identifiable').",
    )

    @field_validator("agent_id")
    @classmethod
    def _agent_id_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class OverrideRequest(BaseModel):
    """Request body for the override endpoint (US-02)."""

    agent_id: str = Field(
        ...,
        min_length=1,
        examples=["agent-7"],
        description="Identity of the acting agent (audit requirement).",
    )
    action: ResolutionAction = Field(
        ...,
        description="New final action. Only 'refund' | 'redelivery' | 'coupon' are accepted; 'other' is rejected by the service (ERR_HUM_008).",
    )
    reply_body: Optional[str] = Field(
        None,
        examples=["We are sorry for the trouble — a full refund has been initiated."],
        description="Agent's edited customer reply. When provided (non-blank), it becomes the final reply in reply_log and is stored in final_reply.",
    )

    @field_validator("agent_id")
    @classmethod
    def _agent_id_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class RejectRequest(BaseModel):
    """Request body for the reject endpoint (US-03)."""

    agent_id: str = Field(
        ...,
        min_length=1,
        examples=["agent-7"],
        description="Identity of the acting agent (audit requirement).",
    )
    reason: str = Field(
        ...,
        min_length=1,
        examples=["Customer already contacted via phone; issue resolved manually."],
        description="Mandatory explanation for the rejection. Blank → ERR_HUM_005 (EC-03).",
    )

    @field_validator("agent_id")
    @classmethod
    def _agent_id_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class HumanDecisionRecord(BaseModel):
    """One persisted human decision — the audit-row contract (US-04)."""

    ticket_id: str = Field(..., description="F1 new_tickets.ticket_id; PK of human_decision_log.")
    order_id: str = Field(..., description="F1 orders_context.order_id linked to the ticket.")
    agent_action: HumanAction = Field(..., description="approve | override | reject.")
    original_action: Optional[str] = Field(
        None,
        description="The suggested action from decision_log at action time (US-02 S1 audit of the original suggestion); None when escalated without guidance.",
    )
    final_action: Optional[str] = Field(
        None,
        description="Final applied action for approve/override; None for reject (suggestion never applied — US-03 S1).",
    )
    rejection_reason: Optional[str] = Field(
        None,
        description="Required for reject; null otherwise (US-03 S1).",
    )
    final_reply: Optional[str] = Field(
        None,
        description="Edited reply body persisted during an override (US-02 S1); null when the drafted reply stands.",
    )
    agent_id: str = Field(..., description="Identity of the agent who acted.")
    created_at: str = Field(..., description="ISO-8601 UTC timestamp of the decision.")

    @property
    def handled(self) -> bool:
        """A human decision always means the ticket is final (BR 'One final decision per ticket')."""
        return True


class HumanDecisionListResponse(BaseModel):
    """Offset-paginated human-decision history (matches F1/F3/F4 pagination convention)."""

    total: int = Field(..., ge=0, description="Total number of human decisions recorded.")
    skip: int = Field(..., ge=0, description="Offset used for this page.")
    limit: int = Field(..., ge=1, description="Page size used for this page.")
    items: List[HumanDecisionRecord] = Field(
        default_factory=list,
        description="Newest-first entries (created_at DESC, ticket_id DESC) — US-04 S1, EC-06.",
    )
