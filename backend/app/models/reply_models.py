"""Pydantic contracts for the Reply Drafting feature (FEAT-004).

These models are the API/engine contracts documented in
``features/F4-reply-drafting/2_tech_spec.md`` §2.1.
"""

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ReplyVariant(str, Enum):
    """Deterministic template family selected from a resolution decision.

    ACTION_CONFIRMED  - auto-resolved ticket: reply states the action taken and,
                        when evidence exists, that it matches similar past cases (US-01 S1, US-03 S1)
    REVIEW_IN_PROGRESS - escalated ticket: reply states a specialist is reviewing and
                        does not promise/imply an action (US-01 S2, US-02 S2, US-03 S2,
                        EC-01, EC-02, EC-05)
    ACKNOWLEDGMENT    - ticket text missing or too short to reference: polite, complete
                        acknowledgment without pretending to know details (EC-03)
    """

    ACTION_CONFIRMED = "action_confirmed"
    REVIEW_IN_PROGRESS = "review_in_progress"
    ACKNOWLEDGMENT = "acknowledgment"


class ReplyStatus(str, Enum):
    """Lifecycle of a reply record in ``reply_log``."""

    DRAFT = "draft"   # not yet sent to the customer; agent may edit
    SENT = "sent"     # customer-facing version finalized (agent's edit or the draft as-is)


class GenerateReplyRequest(BaseModel):
    """Request body for the generate-reply endpoint."""

    ticket_id: str = Field(
        ...,
        min_length=1,
        examples=["N-002"],
        description="Id of the new/incoming ticket to draft a reply for (F1 new_tickets.ticket_id).",
    )


class EditReplyRequest(BaseModel):
    """Request body for editing an unsent reply draft (US-02 S1)."""

    body: str = Field(
        ...,
        min_length=1,
        examples=["Thank you for your patience — your replacement is on its way."],
        description="Agent's replacement reply wording. Must be non-empty.",
    )
    edited_by: Optional[str] = Field(
        None,
        examples=["agent-7"],
        description="Optional agent identifier recorded for audit (edited_at set alongside).",
    )


class SendReplyRequest(BaseModel):
    """Request body for sending a reply to the customer (US-02 S1)."""

    body: Optional[str] = Field(
        None,
        min_length=1,
        examples=["Thank you for your patience — your replacement is on its way."],
        description="Optional final wording. When provided, the reply is edited then sent in one step.",
    )
    edited_by: Optional[str] = Field(
        None,
        examples=["agent-7"],
        description="Optional agent identifier recorded for audit when a final edit is applied.",
    )


class DraftedReply(BaseModel):
    """Pure-engine output: the deterministic reply plus template metadata (no DB fields)."""

    variant: ReplyVariant = Field(..., description="Template family selected for this decision.")
    reply_text: str = Field(..., description="Full customer-facing reply string (exact template rendering).")
    cited_ticket_ids: List[str] = Field(
        default_factory=list,
        description="Evidence past-case ids actually referenced inside reply_text (empty for escalated/acknowledgment).",
    )


class ReplyRecord(BaseModel):
    """Full reply-log record exposed by the API (US-02 S1 audit trail)."""

    ticket_id: str = Field(..., description="FK to new_tickets.ticket_id; one reply per ticket.")
    variant: ReplyVariant
    original_draft: str = Field(
        ...,
        description="Immutable deterministic draft from the last generation (audit trail — EC-04).",
    )
    final_body: str = Field(
        ...,
        description="Customer-facing version: the agent's edit if edited, otherwise the original draft.",
    )
    status: ReplyStatus
    cited_ticket_ids: List[str] = Field(
        default_factory=list,
        description="Evidence ids referenced by the current original_draft.",
    )
    draft_history: List[str] = Field(
        default_factory=list,
        description="Chronological list of prior original_draft values superseded by re-generation (EC-04 audit).",
    )
    edited_by: Optional[str] = Field(None, description="Agent id that last edited final_body.")
    edited_at: Optional[str] = Field(None, description="ISO-8601 UTC timestamp of the last edit.")
    sent_at: Optional[str] = Field(None, description="ISO-8601 UTC timestamp when status became SENT.")
    created_at: str = Field(..., description="ISO-8601 UTC timestamp of record creation / last generation.")


class ReplyListResponse(BaseModel):
    """Offset-paginated reply log (matches F1/F3 pagination convention)."""

    total: int
    skip: int
    limit: int
    items: List[ReplyRecord]


class ReplyStats(BaseModel):
    """Aggregate counts for the dashboard / audit view."""

    total_replies: int
    draft_count: int
    sent_count: int
    by_variant: Dict[str, int] = Field(default_factory=dict, description="Counts keyed by ReplyVariant value.")
