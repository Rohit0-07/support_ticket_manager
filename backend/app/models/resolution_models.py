from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.similarity_models import SimilarTicket, SimilarityStatus


class ResolutionAction(str, Enum):
    """Canonical action vocabulary the engine may apply or suggest.

    REFUND     - money returned to the customer (covers full/partial/reissue)
    REDELIVERY - replacement shipped for the order
    COUPON     - discount coupon issued to the customer
    OTHER      - history action the system cannot apply (e.g. apology, manual escalation)
    """

    REFUND = "refund"
    REDELIVERY = "redelivery"
    COUPON = "coupon"
    OTHER = "other"


class ResolutionOutcome(str, Enum):
    """Final lane assignment for the ticket."""

    AUTO_RESOLVED = "auto_resolved"
    ESCALATED = "escalated"


class EscalationReason(str, Enum):
    """Machine-readable reason a ticket was sent to the human review lane."""

    LOW_CONFIDENCE = "low_confidence"                     # US-01 S2, BR-02
    CONFLICTING_PRECEDENTS = "conflicting_precedents"     # US-02 S1, BR-03
    BLOCKED_BY_ORDER = "blocked_by_order"                 # US-02 S2, BR-04, EC-03
    REFUND_EXCEEDS_ORDER_VALUE = "refund_exceeds_order_value"  # EC-04, BR-05
    NO_SIMILAR_CASES = "no_similar_cases"                 # EC-01, BR-06
    INSUFFICIENT_PRECEDENTS = "insufficient_precedents"   # BR-01 guard (fewer than 3 matches)
    NON_RESOLVABLE_ACTION = "non_resolvable_action"       # precedents agree on `other`
    CANNOT_MATCH = "cannot_match"                         # EC-06
    NO_HISTORY = "no_history"                             # EC-05
    ORDER_NOT_FOUND = "order_not_found"                   # EC-07


class ResolutionRequest(BaseModel):
    """Request body for the resolve endpoint."""

    ticket_id: str = Field(
        ...,
        min_length=1,
        examples=["N-002"],
        description="Id of the new/incoming ticket to resolve (F1 new_tickets.ticket_id).",
    )


class DecisionInput(BaseModel):
    """All inputs required to reach a resolution decision (pure, no I/O).

    Built by ``resolution_service.resolve_ticket`` from F1 ticket/order rows
    and the F2 ``SimilarityResponse``.
    """

    ticket_id: str
    order_id: str
    description: str
    precedents: List[SimilarTicket] = Field(
        default_factory=list,
        description="Top-N similar past cases from F2 (SimilarityResponse.matches).",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Representative match confidence = precedents[0].similarity_score, or 0.0 when empty.",
    )
    threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Auto-resolve confidence bar (RESOLUTION_CONFIDENCE_THRESHOLD).",
    )
    expected_precedents: int = Field(
        default=3,
        ge=1,
        description="Required precedent count for auto-resolve (RESOLUTION_TOP_N_PRECEDENTS).",
    )
    precedent_status: SimilarityStatus = Field(
        default=SimilarityStatus.MATCHED,
        description="F2 SimilarityResponse.status — drives cannot_match/no_history/no_similar_cases escalation.",
    )
    order_status: str = Field(
        default="",
        description="Raw F1 orders_context.status (e.g. 'cancelled', 'delivered').",
    )
    order_value: float = Field(
        default=0.0,
        ge=0.0,
        description="Raw F1 orders_context.value in INR — refund cap ceiling (BR-05).",
    )
    partial_refund_ratio: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Fraction of order value used for partial_refund suggestions (RESOLUTION_PARTIAL_REFUND_RATIO).",
    )
    created_at: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC decision timestamp; defaults to now when None.",
    )


class ResolutionDecision(BaseModel):
    """Full outcome of the resolution engine for one ticket (API response + record)."""

    ticket_id: str
    order_id: str
    description: str
    outcome: ResolutionOutcome
    auto_resolved: bool
    action: Optional[ResolutionAction] = Field(
        ...,
        description="Action applied (auto-resolve) or suggested (escalate); None when no precedent guidance exists.",
    )
    escalation_reason: Optional[EscalationReason] = Field(
        None,
        description="Present iff outcome is ESCALATED; explains why a human is needed.",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    similar_tickets: List[SimilarTicket] = Field(
        default_factory=list,
        description="Top-N precedents used as evidence (US-03 S1/S2).",
    )
    reasoning: str = Field(..., description="Deterministic human-readable explanation (BR-07).")
    refund_amount: Optional[float] = Field(
        None,
        description="Computed refund amount for refund actions, capped at order value (BR-05).",
    )
    created_at: str = Field(..., description="ISO-8601 UTC decision timestamp.")


class DecisionLogEntry(BaseModel):
    """Audit-log row exposed by the decisions endpoints (US-03)."""

    ticket_id: str
    order_id: str
    action: Optional[str] = Field(None, description="Canonical action string or null.")
    confidence: float
    auto_resolved: bool
    escalation_reason: Optional[str] = Field(None, description="Canonical reason string or null.")
    similar_ticket_ids: List[str] = Field(
        default_factory=list,
        description="Evidence past-case ids (H-1000 style).",
    )
    reasoning: str
    refund_amount: Optional[float] = None
    created_at: str


class DecisionListResponse(BaseModel):
    """Offset-paginated audit log (matches F1 pagination convention)."""

    total: int
    skip: int
    limit: int
    items: List[DecisionLogEntry]


class ResolutionStats(BaseModel):
    """Aggregate counts for the dashboard/audit view."""

    total_decisions: int
    auto_resolved_count: int
    escalated_count: int
    by_action: Dict[str, int] = Field(default_factory=dict)
    by_escalation_reason: Dict[str, int] = Field(default_factory=dict)
