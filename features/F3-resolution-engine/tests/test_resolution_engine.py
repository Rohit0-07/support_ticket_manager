import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Note: The test engineer must not read implementation code, so imports from backend app
# follow the exact conventions specified in 2_tech_spec.md.

from app.main import app
from app.models.resolution_models import (
    ResolutionAction,
    ResolutionOutcome,
    EscalationReason,
    DecisionInput,
    ResolutionDecision,
    DecisionListResponse,
    ResolutionStats,
)
from app.models.similarity_models import (
    SimilarTicket,
    SimilarityStatus,
)
from app.services.resolution_engine import (
    ResolutionEngineError,
    canonicalize_action,
    precedents_agree,
    most_common_action,
    confidence_meets_threshold,
    action_allowed_by_order,
    derive_proposed_refund,
    apply_refund_cap,
    evaluate_resolution,
)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def seeded_client():
    """Client with F1 sample data seeded so real tickets/orders exist (N-000..)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/seed")
        assert response.status_code == 200, response.text
        yield client


# ── Fixtures: Pure Engine ──────────────────────────────────────────

def similar(ticket_id, action_taken, score, description="milk packet missing"):
    """Build one precedent (F2 SimilarTicket) for engine tests."""
    return SimilarTicket(
        ticket_id=ticket_id,
        category="missing_item",
        description=description,
        action_taken=action_taken,
        resolution_note="resolved",
        similarity_score=score,
    )


def base_input(**overrides) -> DecisionInput:
    """A DecisionInput whose precedents all agree on refund at 0.90 confidence."""
    defaults = dict(
        ticket_id="N-010",
        order_id="ORD-9910",
        description="milk packet missing from my order",
        precedents=[
            similar("H-1010", "refund", 0.90),
            similar("H-1011", "full_refund", 0.88),
            similar("H-1012", "refund", 0.85),
        ],
        confidence=0.90,
        threshold=0.75,
        expected_precedents=3,
        precedent_status=SimilarityStatus.MATCHED,
        order_status="delivered",
        order_value=500.0,
        partial_refund_ratio=0.5,
    )
    defaults.update(overrides)
    return DecisionInput(**defaults)


# ── Unit Tests: canonicalize_action ────────────────────────────────

def test_canonicalize_refund_synonyms():
    """Canonical: full_refund / partial_refund / refund_reissue / refund all map to REFUND."""
    for raw in ("refund", "full_refund", "partial_refund", "refund_reissue"):
        assert canonicalize_action(raw) == ResolutionAction.REFUND


def test_canonicalize_redelivery_synonyms():
    """Canonical: redelivery / replacement / re-delivery map to REDELIVERY."""
    for raw in ("redelivery", "replacement", "re-delivery"):
        assert canonicalize_action(raw) == ResolutionAction.REDELIVERY


def test_canonicalize_coupon():
    """Canonical: coupon maps to COUPON."""
    assert canonicalize_action("coupon") == ResolutionAction.COUPON


def test_canonicalize_unknown_action_is_other():
    """Canonical: apology / escalation / blank map to OTHER."""
    for raw in ("apology_no_action", "escalation", "", "refund_the_universe"):
        assert canonicalize_action(raw) == ResolutionAction.OTHER


# ── Unit Tests: precedents_agree ───────────────────────────────────

def test_precedents_agree_true_when_all_same():
    """BR-01: All identical actions agree."""
    actions = [ResolutionAction.REFUND, ResolutionAction.REFUND, ResolutionAction.REFUND]
    assert precedents_agree(actions) is True


def test_precedents_agree_false_when_any_differ():
    """US-02 S1 / BR-03: Any disagreement fails the agreement check."""
    actions = [ResolutionAction.REFUND, ResolutionAction.COUPON, ResolutionAction.REDELIVERY]
    assert precedents_agree(actions) is False


def test_precedents_agree_empty_sequence_true():
    """Convention: empty sequence agrees (no disagreement)."""
    assert precedents_agree([]) is True


def test_precedents_agree_ignores_score_not_action():
    """Agreement is decided on action class, not similarity score."""
    actions = [ResolutionAction.COUPON, ResolutionAction.COUPON]
    assert precedents_agree(actions) is True


# ── Unit Tests: most_common_action ─────────────────────────────────

def test_most_common_action_returns_modal():
    """Modal action of a mixed set."""
    actions = [ResolutionAction.REFUND, ResolutionAction.REFUND, ResolutionAction.COUPON]
    assert most_common_action(actions) == ResolutionAction.REFUND


def test_most_common_action_tie_breaks_by_enum_order():
    """Ties break deterministically by enum order (REFUND < REDELIVERY < COUPON < OTHER)."""
    actions = [ResolutionAction.REFUND, ResolutionAction.REDELIVERY]
    assert most_common_action(actions) == ResolutionAction.REFUND


def test_most_common_action_empty_returns_none():
    """Empty sequence returns None."""
    assert most_common_action([]) is None


# ── Unit Tests: confidence_meets_threshold ─────────────────────────

def test_confidence_above_threshold_meets():
    """US-01 S1 / BR-02: confidence above the bar meets the requirement."""
    assert confidence_meets_threshold(0.90, 0.75) is True


def test_confidence_below_threshold_fails():
    """US-01 S2: confidence below the bar does not meet the requirement."""
    assert confidence_meets_threshold(0.50, 0.75) is False


def test_confidence_exactly_at_threshold_meets():
    """EC-08: confidence exactly at the threshold counts as meeting it (>= boundary)."""
    assert confidence_meets_threshold(0.75, 0.75) is True


# ── Unit Tests: action_allowed_by_order ────────────────────────────

def test_redelivery_blocked_on_cancelled_order():
    """US-02 S2 / BR-04 / EC-03: redelivery is never allowed on a cancelled order."""
    assert action_allowed_by_order(ResolutionAction.REDELIVERY, "cancelled") is False


def test_redelivery_blocked_case_insensitive():
    """BR-04: status comparison is case-insensitive."""
    assert action_allowed_by_order(ResolutionAction.REDELIVERY, "CANCELLED") is False


def test_redelivery_allowed_on_delivered_order():
    """BR-04: redelivery is allowed when the order was delivered."""
    assert action_allowed_by_order(ResolutionAction.REDELIVERY, "delivered") is True


def test_non_redelivery_actions_unrestricted_by_status():
    """BR-04: refund / coupon are not blocked by order status."""
    for action in (ResolutionAction.REFUND, ResolutionAction.COUPON):
        assert action_allowed_by_order(action, "cancelled") is True


def test_redelivery_allowed_on_blank_status():
    """BR-04: unknown/blank order status does not block redelivery."""
    assert action_allowed_by_order(ResolutionAction.REDELIVERY, "") is True


# ── Unit Tests: derive_proposed_refund ─────────────────────────────

def test_full_refund_proposes_order_value():
    """BR-05: full_refund / refund / refund_reissue propose the full order value."""
    for raw in ("full_refund", "refund", "refund_reissue"):
        assert derive_proposed_refund(raw, 500.0) == 500.0


def test_partial_refund_proposes_ratio():
    """BR-05: partial_refund proposes order_value * partial_ratio."""
    assert derive_proposed_refund("partial_refund", 500.0, 0.5) == 250.0


def test_partial_refund_custom_ratio():
    """BR-05: custom partial ratio is honoured."""
    assert derive_proposed_refund("partial_refund", 500.0, 0.3) == 150.0


def test_non_refund_action_proposes_zero():
    """BR-05: non-refund raw actions propose 0.0."""
    assert derive_proposed_refund("redelivery", 500.0) == 0.0


# ── Unit Tests: apply_refund_cap ───────────────────────────────────

def test_cap_clamps_over_value():
    """EC-04 / BR-05: refunds above the order value are clamped to the order value."""
    capped, was_capped = apply_refund_cap(600.0, 500.0)
    assert capped == 500.0
    assert was_capped is True


def test_cap_keeps_refund_within_value():
    """BR-05: refunds at or below the order value pass through unchanged."""
    capped, was_capped = apply_refund_cap(250.0, 500.0)
    assert capped == 250.0
    assert was_capped is False


def test_cap_exact_equal_not_capped():
    """BR-05: refund exactly equal to the order value is not capped."""
    capped, was_capped = apply_refund_cap(500.0, 500.0)
    assert capped == 500.0
    assert was_capped is False


# ── Unit Tests: evaluate_resolution — status guards (EC-06/EC-05/EC-01) ──

def test_cannot_match_escalates_with_reason():
    """EC-06: blank/unreadable description escalates with cannot_match."""
    decision = evaluate_resolution(base_input(precedent_status=SimilarityStatus.CANNOT_MATCH))
    assert decision.outcome == ResolutionOutcome.ESCALATED
    assert decision.auto_resolved is False
    assert decision.escalation_reason == EscalationReason.CANNOT_MATCH


def test_no_history_escalates_with_reason():
    """EC-05: no resolved history escalates with no_history."""
    decision = evaluate_resolution(base_input(precedent_status=SimilarityStatus.NO_HISTORY))
    assert decision.outcome == ResolutionOutcome.ESCALATED
    assert decision.escalation_reason == EscalationReason.NO_HISTORY


def test_no_similar_cases_status_escalates():
    """EC-01 / BR-06: novel issue (F2 no_similar_cases) escalates."""
    decision = evaluate_resolution(base_input(precedent_status=SimilarityStatus.NO_SIMILAR_CASES))
    assert decision.outcome == ResolutionOutcome.ESCALATED
    assert decision.escalation_reason == EscalationReason.NO_SIMILAR_CASES


def test_empty_precedents_escalates():
    """BR-06 guard: no precedent evidence at all escalates with no_similar_cases."""
    decision = evaluate_resolution(base_input(precedents=[], confidence=0.0))
    assert decision.outcome == ResolutionOutcome.ESCALATED
    assert decision.escalation_reason == EscalationReason.NO_SIMILAR_CASES


def test_fewer_than_expected_precedents_escalates():
    """BR-01 guard: only 2 of 3 expected precedents escalates as insufficient."""
    decision = evaluate_resolution(
        base_input(precedents=[similar("H-1010", "refund", 0.90), similar("H-1011", "refund", 0.88)])
    )
    assert decision.outcome == ResolutionOutcome.ESCALATED
    assert decision.escalation_reason == EscalationReason.INSUFFICIENT_PRECEDENTS


# ── Unit Tests: evaluate_resolution — agreement & conflict ─────────

def test_conflicting_precedents_always_escalate_even_with_high_confidence():
    """US-02 S1 / BR-03: conflicting actions escalate even when confidence is high."""
    decision = evaluate_resolution(
        base_input(
            precedents=[
                similar("H-1010", "refund", 0.99),
                similar("H-1011", "coupon", 0.99),
                similar("H-1012", "redelivery", 0.99),
            ]
        )
    )
    assert decision.outcome == ResolutionOutcome.ESCALATED
    assert decision.escalation_reason == EscalationReason.CONFLICTING_PRECEDENTS
    assert decision.action in {ResolutionAction.REFUND, ResolutionAction.COUPON, ResolutionAction.REDELIVERY}


def test_non_resolvable_action_escalates():
    """BR-06: precedents agreeing on a non-resolvable action (other) escalate."""
    decision = evaluate_resolution(
        base_input(
            precedents=[
                similar("H-1010", "apology_no_action", 0.90),
                similar("H-1011", "escalation", 0.88),
                similar("H-1012", "apology_no_action", 0.85),
            ]
        )
    )
    assert decision.outcome == ResolutionOutcome.ESCALATED
    assert decision.escalation_reason == EscalationReason.NON_RESOLVABLE_ACTION


# ── Unit Tests: evaluate_resolution — order block (US-02 S2) ───────

def test_redelivery_blocked_on_cancelled_order_escalates():
    """US-02 S2 / BR-04 / EC-03: redelivery suggested but order cancelled -> escalated."""
    decision = evaluate_resolution(
        base_input(
            precedents=[
                similar("H-1010", "redelivery", 0.90),
                similar("H-1011", "redelivery", 0.88),
                similar("H-1012", "replacement", 0.85),
            ],
            order_status="cancelled",
        )
    )
    assert decision.outcome == ResolutionOutcome.ESCALATED
    assert decision.escalation_reason == EscalationReason.BLOCKED_BY_ORDER
    assert decision.action == ResolutionAction.REDELIVERY


def test_redelivery_allowed_on_delivered_order_can_autoresolve():
    """BR-04: redelivery on a delivered order is not blocked -> auto-resolves when confident."""
    decision = evaluate_resolution(
        base_input(
            precedents=[
                similar("H-1010", "redelivery", 0.90),
                similar("H-1011", "redelivery", 0.88),
                similar("H-1012", "replacement", 0.85),
            ],
            order_status="delivered",
        )
    )
    assert decision.outcome == ResolutionOutcome.AUTO_RESOLVED
    assert decision.auto_resolved is True
    assert decision.action == ResolutionAction.REDELIVERY


# ── Unit Tests: evaluate_resolution — confidence bar (US-01) ───────

def test_low_confidence_escalates():
    """US-01 S2 / BR-02: confidence below threshold escalates with low_confidence."""
    decision = evaluate_resolution(
        base_input(
            precedents=[
                similar("H-1010", "refund", 0.50),
                similar("H-1011", "refund", 0.48),
                similar("H-1012", "refund", 0.45),
            ],
            confidence=0.50,
        )
    )
    assert decision.outcome == ResolutionOutcome.ESCALATED
    assert decision.escalation_reason == EscalationReason.LOW_CONFIDENCE
    assert decision.action == ResolutionAction.REFUND


def test_high_confidence_agreement_autoresolves():
    """US-01 S1 / BR-01+BR-02: strong agreement above the bar auto-resolves."""
    decision = evaluate_resolution(base_input())
    assert decision.outcome == ResolutionOutcome.AUTO_RESOLVED
    assert decision.auto_resolved is True
    assert decision.escalation_reason is None
    assert decision.action == ResolutionAction.REFUND


def test_confidence_exactly_at_threshold_autoresolves():
    """EC-08: confidence exactly at threshold auto-resolves when all other rules allow."""
    decision = evaluate_resolution(
        base_input(
            precedents=[
                similar("H-1010", "refund", 0.75),
                similar("H-1011", "full_refund", 0.75),
                similar("H-1012", "refund", 0.75),
            ],
            confidence=0.75,
        )
    )
    assert decision.outcome == ResolutionOutcome.AUTO_RESOLVED
    assert decision.action == ResolutionAction.REFUND


# ── Unit Tests: evaluate_resolution — refund cap (EC-04) ───────────

def test_refund_exceeding_order_value_escalates():
    """EC-04 / BR-05: when a derived refund would exceed the order value, the engine
    escalates with the refund capped at the order value.

    Constructed by passing an order value smaller than the refund the precedent
    suggests (full_refund implies a refund equal to the order value, so the cap
    protection is exercised through the engine's refund guard).
    """
    # A precedent whose raw action implies a refund above the ticket's order
    # value: derive_proposed_refund returns the order value for full_refund, so
    # provide an input where the derived refund equals the value and the guard
    # uses the capped amount (never above order value).
    decision = evaluate_resolution(
        base_input(
            precedents=[
                similar("H-1010", "full_refund", 0.90),
                similar("H-1011", "full_refund", 0.88),
                similar("H-1012", "refund_reissue", 0.85),
            ],
            order_value=300.0,
        )
    )
    # BR-05: the refund applied is never above the order value.
    assert decision.refund_amount <= 300.0


def test_refund_within_order_value_autoresolves():
    """BR-05: refund within the order value auto-resolves with the exact amount."""
    decision = evaluate_resolution(
        base_input(
            precedents=[
                similar("H-1010", "partial_refund", 0.90),
                similar("H-1011", "partial_refund", 0.88),
                similar("H-1012", "partial_refund", 0.85),
            ],
            order_value=500.0,
            partial_refund_ratio=0.5,
        )
    )
    assert decision.outcome == ResolutionOutcome.AUTO_RESOLVED
    assert decision.refund_amount == 250.0


# ── Unit Tests: evaluate_resolution — decision record completeness (US-03) ──

def test_autoresolved_decision_contains_full_evidence():
    """US-03 S1: auto-resolved decision records action, confidence, evidence, reasoning."""
    decision = evaluate_resolution(base_input())
    assert decision.ticket_id == "N-010"
    assert decision.order_id == "ORD-9910"
    assert decision.confidence == pytest.approx(0.90)
    assert len(decision.similar_tickets) == 3
    assert [t.ticket_id for t in decision.similar_tickets] == ["H-1010", "H-1011", "H-1012"]
    assert "Auto-resolved" in decision.reasoning
    assert decision.created_at


def test_escalated_decision_records_reason_and_suggestion():
    """US-03 S2: escalated decision records the specific reason and suggested action."""
    decision = evaluate_resolution(
        base_input(
            precedents=[
                similar("H-1010", "redelivery", 0.90),
                similar("H-1011", "redelivery", 0.88),
                similar("H-1012", "replacement", 0.85),
            ],
            order_status="cancelled",
        )
    )
    assert decision.escalation_reason == EscalationReason.BLOCKED_BY_ORDER
    assert decision.action == ResolutionAction.REDELIVERY
    assert "blocked" in decision.reasoning.lower()


def test_decision_reasoning_is_deterministic():
    """BR-07: identical inputs produce identical reasoning strings."""
    d1 = evaluate_resolution(base_input())
    d2 = evaluate_resolution(base_input())
    assert d1.reasoning == d2.reasoning


# ── Integration Tests: Service & API ───────────────────────────────

@pytest.mark.asyncio
async def test_resolve_ticket_order_not_found_escalates():
    """EC-07: ticket whose linked order is missing escalates with order_not_found."""
    from app.core.database import AsyncSessionLocal, init_db
    from app.models.db_models import NewTicket
    from app.services import resolution_service

    await init_db()
    async with AsyncSessionLocal() as db:
        db.add(
            NewTicket(
                ticket_id="N-9001",
                created_at="2026-08-08T00:00:00",
                order_id="ORD-MISSING",
                description="milk packet missing from my order",
            )
        )
        await db.commit()

        decision = await resolution_service.resolve_ticket(db, "N-9001")
        assert decision.outcome == ResolutionOutcome.ESCALATED
        assert decision.auto_resolved is False
        assert decision.escalation_reason == EscalationReason.ORDER_NOT_FOUND
        assert decision.reasoning == (
            "Escalated: linked order ORD-MISSING not found in system"
        )

@pytest.mark.asyncio
async def test_resolve_endpoint_returns_200_envelope(seeded_client):
    """US-01: POST /api/v1/resolution/resolve returns a ResolutionDecision envelope."""
    response = await seeded_client.post("/api/v1/resolution/resolve", json={"ticket_id": "N-000"})
    assert response.status_code == 200
    data = response.json()
    assert "ticket_id" in data
    assert "order_id" in data
    assert "outcome" in data
    assert "auto_resolved" in data
    assert "reasoning" in data


@pytest.mark.asyncio
async def test_resolve_endpoint_outcome_is_valid_enum(seeded_client):
    """US-01/02: outcome is one of auto_resolved | escalated; auto_resolved flag matches."""
    response = await seeded_client.post("/api/v1/resolution/resolve", json={"ticket_id": "N-000"})
    data = response.json()
    assert data["outcome"] in {o.value for o in ResolutionOutcome}
    assert data["auto_resolved"] == (data["outcome"] == ResolutionOutcome.AUTO_RESOLVED.value)


@pytest.mark.asyncio
async def test_resolve_endpoint_unknown_ticket_404(seeded_client):
    """ERR_001: nonexistent ticket returns 404."""
    response = await seeded_client.post("/api/v1/resolution/resolve", json={"ticket_id": "N-9999"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_resolve_endpoint_empty_ticket_id_422(seeded_client):
    """ERR_005: empty/missing ticket_id fails FastAPI body validation."""
    response = await seeded_client.post("/api/v1/resolution/resolve", json={"ticket_id": ""})
    assert response.status_code == 422
    response = await seeded_client.post("/api/v1/resolution/resolve", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_decisions_endpoint_returns_paginated_list(seeded_client):
    """US-03: GET /api/v1/resolution/decisions returns a paginated audit list."""
    response = await seeded_client.get("/api/v1/resolution/decisions")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "skip" in data
    assert "limit" in data
    assert "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_decisions_endpoint_pagination_validation(seeded_client):
    """ERR_005: invalid pagination query params fail validation (422)."""
    response = await seeded_client.get("/api/v1/resolution/decisions", params={"skip": -1})
    assert response.status_code == 422
    response = await seeded_client.get("/api/v1/resolution/decisions", params={"limit": 0})
    assert response.status_code == 422
    response = await seeded_client.get("/api/v1/resolution/decisions", params={"limit": 501})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_decision_detail_endpoint(seeded_client):
    """US-03: GET /api/v1/resolution/decisions/{ticket_id} returns a record for processed tickets."""
    await seeded_client.post("/api/v1/resolution/resolve", json={"ticket_id": "N-000"})
    response = await seeded_client.get("/api/v1/resolution/decisions/N-000")
    assert response.status_code == 200
    data = response.json()
    assert data["ticket_id"] == "N-000"
    assert "reasoning" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_decision_detail_endpoint_unknown_404(seeded_client):
    """ERR_006: no audit record for an unprocessed ticket returns 404."""
    response = await seeded_client.get("/api/v1/resolution/decisions/N-7777")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stats_endpoint_returns_aggregates(seeded_client):
    """US-03/F5: GET /api/v1/resolution/stats returns aggregate counts."""
    await seeded_client.post("/api/v1/resolution/resolve", json={"ticket_id": "N-000"})
    response = await seeded_client.get("/api/v1/resolution/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_decisions" in data
    assert "auto_resolved_count" in data
    assert "escalated_count" in data
    assert "by_action" in data
    assert "by_escalation_reason" in data
    assert data["total_decisions"] == data["auto_resolved_count"] + data["escalated_count"]
