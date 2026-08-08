"""Pydantic contracts for the Two-Lane Dashboard feature (FEAT-005).

These models are the API/engine contracts documented in
``features/F5-two-lane-dashboard/2_tech_spec.md`` §2.1.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class DashboardLane(str, Enum):
    """The two dashboard lanes.

    Assignment follows BR-01 exactly — a ticket belongs to exactly one
    lane, decided by ``auto_resolved``.
    """

    AUTO_RESOLVED = "auto_resolved"
    NEEDS_REVIEW = "needs_review"


class ConfidenceLevel(str, Enum):
    """Display buckets for confidence color-coding (US-02 S1, EC-04).

    Derived ONLY from the persisted decision confidence via
    ``confidence_level()``; the underlying score is never altered (BR-02).
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DashboardTicketCard(BaseModel):
    """Compact summary rendered on a lane card (US-02)."""

    ticket_id: str = Field(..., description="F1 new_tickets.ticket_id, e.g. 'N-002'.")
    description_preview: str = Field(
        ...,
        description="Full description truncated with '…' via truncate_description() (EC-03).",
    )
    action: Optional[str] = Field(
        None,
        description="Canonical action string ('refund' | 'redelivery' | 'coupon') applied (auto) or suggested (review); None when escalated without precedent guidance.",
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Persisted decision confidence, unmodified (BR-02).")
    confidence_level: ConfidenceLevel = Field(
        ...,
        description="Color bucket derived from confidence (high/medium/low).",
    )
    lane: DashboardLane = Field(..., description="Lane assignment per BR-01.")
    auto_resolved: bool = Field(..., description="True iff the ticket was auto-resolved.")
    escalation_reason: Optional[str] = Field(
        None,
        description="Canonical escalation reason string; null for auto-resolved tickets.",
    )
    created_at: str = Field(..., description="ISO-8601 UTC decision timestamp (from decision_log).")


class DashboardLaneSection(BaseModel):
    """One lane with its ticket list and count badge (US-01 S1/S2, EC-01)."""

    label: str = Field(..., description="Human-readable lane label, e.g. 'Auto-Resolved'.")
    count: int = Field(..., ge=0, description="Number of tickets in this lane (badge).")
    tickets: List[DashboardTicketCard] = Field(
        default_factory=list,
        description="Lane tickets, newest decision first (created_at DESC, ticket_id DESC). Empty when the lane is empty (EC-01).",
    )


class DashboardBoard(BaseModel):
    """Full board payload — both lanes, always present (BR-04)."""

    loaded_at: str = Field(..., description="ISO-8601 UTC timestamp of aggregation.")
    auto_resolved: DashboardLaneSection = Field(..., description="Auto-Resolved lane section.")
    needs_review: DashboardLaneSection = Field(..., description="Needs Human Review lane section.")


class SimilarCaseEvidence(BaseModel):
    """One top-3 similar past case with its score, shown in the detail view (US-03)."""

    ticket_id: str = Field(..., description="Resolved past-case id (H-1000 style).")
    description: str = Field(..., description="Full description of the past case.")
    action_taken: str = Field(..., description="Action that was taken for the past case.")
    resolution_note: str = Field(..., description="Resolution note of the past case.")
    similarity_score: float = Field(..., ge=0.0, le=1.0, description="Cosine similarity used at decision time.")


class SimilarCasesStatus(str, Enum):
    """Whether the detail view has evidence to show (US-03 S1/S2, EC-02)."""

    FOUND = "found"
    NONE = "none"  # no similar past cases / no history / cannot match


class ReplySummary(BaseModel):
    """Drafted customer reply surfaced in the detail view (US-03, F4 integration)."""

    final_body: str = Field(..., description="Customer-facing reply text (agent's edit or original draft).")
    variant: str = Field(..., description="F4 ReplyVariant value, e.g. 'action_confirmed'.")
    status: str = Field(..., description="F4 ReplyStatus value, 'draft' or 'sent'.")


class DashboardTicketDetail(BaseModel):
    """Full read-only detail payload for one ticket (US-03)."""

    ticket_id: str = Field(..., description="F1 new_tickets.ticket_id.")
    order_id: str = Field(..., description="F1 orders_context.order_id linked to the ticket.")
    description: str = Field(..., description="Full, untruncated ticket description (EC-03).")
    action: Optional[str] = Field(None, description="Applied (auto) or suggested (review) canonical action.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Persisted decision confidence (BR-02).")
    confidence_level: ConfidenceLevel = Field(..., description="Color bucket for the detail view.")
    lane: DashboardLane = Field(..., description="Lane assignment per BR-01.")
    auto_resolved: bool = Field(..., description="True iff auto-resolved.")
    escalation_reason: Optional[str] = Field(None, description="Canonical escalation reason; null when auto-resolved.")
    reasoning: str = Field(..., description="Plain-language decision reasoning, verbatim from decision_log (BR-03).")
    refund_amount: Optional[float] = Field(None, description="Computed refund amount in INR for refund actions; else null.")
    similar_cases: List[SimilarCaseEvidence] = Field(
        default_factory=list,
        description="Top-3 evidence with scores (US-03 S1). Empty when similar_cases_status is NONE (EC-02).",
    )
    similar_cases_status: SimilarCasesStatus = Field(
        ...,
        description="FOUND when evidence exists, else NONE (US-03 S2, EC-02).",
    )
    reply: Optional[ReplySummary] = Field(
        None,
        description="Drafted customer reply if a reply record exists; None → frontend fallback message.",
    )
    created_at: str = Field(..., description="ISO-8601 UTC decision timestamp.")
