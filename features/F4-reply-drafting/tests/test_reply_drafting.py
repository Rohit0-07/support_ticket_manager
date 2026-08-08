import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Note: The test engineer must not read implementation code, so imports from backend app
# follow the exact conventions specified in 2_tech_spec.md.

from app.core.config import settings
from app.main import app
from app.models.reply_models import ReplyStatus, ReplyVariant
from app.models.resolution_models import (
    EscalationReason,
    ResolutionAction,
    ResolutionDecision,
    ResolutionOutcome,
)
from app.models.similarity_models import SimilarTicket
from app.services.reply_engine import (
    ReplyEngineError,
    ReplyTemplateError,
    build_action_statement,
    build_evidence_sentence,
    build_refund_clause,
    draft_reply,
    select_reply_variant,
    truncate_quote,
)
from app.services.reply_service import (
    InvalidReplyBodyError,
    ReplyAlreadySentError,
    ReplyNotFoundError,
    compute_reply_stats,
    edit_reply,
    generate_reply,
    get_reply,
    list_replies,
    send_reply,
)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(autouse=True)
async def _clean_reply_log():
    """Isolate each test: start with an empty reply_log (shared tickets.db)."""
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal, init_db
    from app.models.db_models import ReplyLog

    await init_db()
    async with AsyncSessionLocal() as db:
        await db.execute(delete(ReplyLog))
        await db.commit()
    yield


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


def decision(**overrides) -> ResolutionDecision:
    """An auto-resolved REFUND decision with 3 agreeing precedents (US-01 S1)."""
    defaults = dict(
        ticket_id="N-010",
        order_id="ORD-9910",
        description="milk packet missing from my order",
        outcome=ResolutionOutcome.AUTO_RESOLVED,
        auto_resolved=True,
        action=ResolutionAction.REFUND,
        escalation_reason=None,
        confidence=0.90,
        similar_tickets=[
            similar("H-1010", "refund", 0.90),
            similar("H-1011", "full_refund", 0.88),
            similar("H-1012", "refund", 0.85),
        ],
        reasoning="Auto-resolved based on 3 agreeing precedents.",
        refund_amount=249.50,
        created_at="2026-08-08T10:00:00",
    )
    defaults.update(overrides)
    return ResolutionDecision(**defaults)


def escalated_decision(**overrides) -> ResolutionDecision:
    """An escalated decision with no action finalized (US-01 S2 / EC-01/02)."""
    defaults = dict(
        ticket_id="N-011",
        order_id="ORD-9911",
        description="fruits were rotten",
        outcome=ResolutionOutcome.ESCALATED,
        auto_resolved=False,
        action=None,
        escalation_reason=EscalationReason.NO_SIMILAR_CASES,
        confidence=0.0,
        similar_tickets=[],
        reasoning="Escalated: no similar past cases found",
        refund_amount=None,
        created_at="2026-08-08T10:00:00",
    )
    defaults.update(overrides)
    return ResolutionDecision(**defaults)


# ── Unit Tests: select_reply_variant ───────────────────────────────

def test_auto_resolved_selects_action_confirmed():
    """US-01 S1 / US-03 S1: auto-resolved decisions render the action-confirmed template."""
    assert select_reply_variant(decision()) == ReplyVariant.ACTION_CONFIRMED


def test_escalated_selects_review_in_progress():
    """US-01 S2: any escalated decision renders the review-in-progress template."""
    for reason in (
        EscalationReason.NO_SIMILAR_CASES,
        EscalationReason.CONFLICTING_PRECEDENTS,
        EscalationReason.LOW_CONFIDENCE,
        EscalationReason.BLOCKED_BY_ORDER,
        EscalationReason.ORDER_NOT_FOUND,
        EscalationReason.REFUND_EXCEEDS_ORDER_VALUE,
    ):
        assert select_reply_variant(escalated_decision(escalation_reason=reason)) == ReplyVariant.REVIEW_IN_PROGRESS


def test_blank_description_selects_acknowledgment():
    """EC-03: a blank/whitespace description renders the acknowledgment template."""
    assert select_reply_variant(escalated_decision(description="   ")) == ReplyVariant.ACKNOWLEDGMENT


def test_too_short_description_selects_acknowledgment():
    """EC-03: a description shorter than STM_REPLY_MIN_QUOTE_CHARS is not referenced."""
    short = "a" * (settings.REPLY_MIN_QUOTE_CHARS - 1)
    assert select_reply_variant(decision(description=short)) == ReplyVariant.ACKNOWLEDGMENT


def test_minimum_quote_length_still_action_confirmed():
    """EC-03 boundary: a description at exactly STM_REPLY_MIN_QUOTE_CHARS is quotable."""
    boundary = "a" * settings.REPLY_MIN_QUOTE_CHARS
    assert select_reply_variant(decision(description=boundary)) == ReplyVariant.ACTION_CONFIRMED


# ── Unit Tests: truncate_quote ─────────────────────────────────────

def test_truncate_quote_blank_returns_empty():
    """EC-03: blank input yields no quote at all."""
    assert truncate_quote("") == ""
    assert truncate_quote("   ") == ""


def test_truncate_quote_short_text_unchanged():
    """Short descriptions pass through trimmed and unchanged."""
    assert truncate_quote("  milk packet missing  ") == "milk packet missing"


def test_truncate_quote_long_text_truncated_with_ellipsis():
    """EC-06: descriptions over STM_REPLY_MAX_QUOTE_CHARS are cut with an ellipsis."""
    long_text = "milk " * 60  # 240 chars
    result = truncate_quote(long_text, settings.REPLY_MAX_QUOTE_CHARS)
    assert result.endswith("…")
    assert len(result) <= settings.REPLY_MAX_QUOTE_CHARS + 1
    assert result[:-1] == result[:-1].rstrip()


def test_truncate_quote_at_max_length_unchanged():
    """EC-06 boundary: text exactly at the cap is not truncated."""
    text = "x" * settings.REPLY_MAX_QUOTE_CHARS
    assert truncate_quote(text, settings.REPLY_MAX_QUOTE_CHARS) == text


# ── Unit Tests: build_action_statement ─────────────────────────────

def test_refund_action_statement():
    """US-01 S1: refund maps to the exact customer phrase."""
    assert build_action_statement(ResolutionAction.REFUND) == "your order has been refunded"


def test_redelivery_action_statement():
    """US-01 S1: redelivery maps to the exact customer phrase."""
    assert build_action_statement(ResolutionAction.REDELIVERY) == "a replacement delivery has been arranged for your order"


def test_coupon_action_statement():
    """US-01 S1: coupon maps to the exact customer phrase."""
    assert build_action_statement(ResolutionAction.COUPON) == "a discount coupon has been added to your account"


def test_none_action_raises_template_error():
    """BR-02/BR-03 guard: no action may be stated for a confirmed-reply template."""
    with pytest.raises(ReplyTemplateError):
        build_action_statement(None)


def test_other_action_raises_template_error():
    """BR-02/BR-03 guard: OTHER is never rendered as a confirmed action."""
    with pytest.raises(ReplyTemplateError):
        build_action_statement(ResolutionAction.OTHER)


# ── Unit Tests: build_refund_clause ────────────────────────────────

def test_refund_clause_formats_amount():
    """EC-05: a confirmed amount renders with INR and two decimals."""
    assert build_refund_clause(249.50) == (
        " The amount of ₹249.50 has been returned to your original payment method."
    )


def test_refund_clause_missing_amount_omitted():
    """EC-05: no confirmed amount means no refund clause (never invent order facts)."""
    assert build_refund_clause(None) == ""


# ── Unit Tests: build_evidence_sentence ────────────────────────────

def test_evidence_sentence_lists_ids():
    """US-03 S1: real precedent ids are cited in the evidence sentence."""
    assert build_evidence_sentence(["H-1010", "H-1011", "H-1012"]) == (
        "This action follows how we have handled similar past cases (reference: H-1010, H-1011, H-1012)."
    )


def test_evidence_sentence_empty_omitted():
    """BR-03 / EC-01: no evidence means no evidence sentence."""
    assert build_evidence_sentence([]) == ""


# ── Unit Tests: draft_reply — ACTION_CONFIRMED ─────────────────────

def test_action_confirmed_reply_exact_string():
    """US-01 S1: auto-resolved refund renders greeting + action + refund + evidence + closing."""
    reply = draft_reply(decision())
    assert reply.variant == ReplyVariant.ACTION_CONFIRMED
    assert reply.reply_text == (
        'Thank you for contacting us about "milk packet missing from my order".\n\n'
        "We have resolved your issue: your order has been refunded. "
        "The amount of ₹249.50 has been returned to your original payment method.\n\n"
        "This action follows how we have handled similar past cases (reference: H-1010, H-1011, H-1012).\n\n"
        "We apologize for any inconvenience and appreciate your patience."
    )
    assert reply.cited_ticket_ids == ["H-1010", "H-1011", "H-1012"]


def test_action_confirmed_redelivery_exact_string():
    """US-01 S1: a redelivery decision renders the redelivery statement with no refund clause."""
    reply = draft_reply(decision(action=ResolutionAction.REDELIVERY, refund_amount=None))
    assert "a replacement delivery has been arranged for your order" in reply.reply_text
    assert "returned to your original payment method" not in reply.reply_text


def test_action_confirmed_without_evidence_omits_evidence():
    """BR-03: no precedent ids → the evidence sentence is omitted entirely."""
    reply = draft_reply(decision(similar_tickets=[], refund_amount=None))
    assert "similar past cases" not in reply.reply_text
    assert reply.cited_ticket_ids == []


def test_action_confirmed_cites_at_most_three_precedents():
    """Evidence cites are limited to STM_REPLY_MAX_EVIDENCE_CITES (default 3)."""
    precedents = [similar(f"H-{1000 + i}", "refund", 0.9 - i * 0.01) for i in range(5)]
    reply = draft_reply(decision(similar_tickets=precedents))
    assert len(reply.cited_ticket_ids) == settings.REPLY_MAX_EVIDENCE_CITES
    assert reply.cited_ticket_ids == ["H-1000", "H-1001", "H-1002"]
    assert "H-1003" not in reply.reply_text


def test_action_confirmed_long_quote_truncated():
    """EC-06: a very long description is truncated inside the greeting quote."""
    reply = draft_reply(decision(description="milk " * 60))
    assert "…" in reply.reply_text
    assert reply.variant == ReplyVariant.ACTION_CONFIRMED


def test_draft_reply_is_deterministic():
    """BR-04: identical decisions always produce the identical reply string."""
    assert draft_reply(decision()).reply_text == draft_reply(decision()).reply_text


# ── Unit Tests: draft_reply — REVIEW_IN_PROGRESS ───────────────────

def test_review_in_progress_reply_exact_string():
    """US-01 S2: escalated ticket reply never promises an action."""
    reply = draft_reply(escalated_decision())
    assert reply.variant == ReplyVariant.REVIEW_IN_PROGRESS
    assert reply.reply_text == (
        'Thank you for contacting us about "fruits were rotten".\n\n'
        "We are currently reviewing your issue, and a support specialist will follow up with you shortly. "
        "No action has been finalized yet.\n\n"
        "We appreciate your patience while we look into this."
    )
    assert reply.cited_ticket_ids == []


def test_review_in_progress_never_promises_or_cites():
    """BR-02/BR-03 / EC-01/EC-02: escalated replies cite no cases and promise no action."""
    reply = draft_reply(
        escalated_decision(
            escalation_reason=EscalationReason.CONFLICTING_PRECEDENTS,
            similar_tickets=[similar("H-1010", "refund", 0.9)],
        )
    )
    assert "No action has been finalized yet" in reply.reply_text
    assert "similar past cases" not in reply.reply_text
    assert "resolved" not in reply.reply_text.lower()
    assert reply.cited_ticket_ids == []


def test_review_in_progress_conflict_no_action_stated():
    """EC-02: conflicting precedents never yield an action statement."""
    reply = draft_reply(
        escalated_decision(
            escalation_reason=EscalationReason.CONFLICTING_PRECEDENTS,
            action=ResolutionAction.REFUND,
        )
    )
    assert "refund" not in reply.reply_text.lower()


# ── Unit Tests: draft_reply — ACKNOWLEDGMENT ───────────────────────

def test_acknowledgment_reply_exact_string():
    """EC-03: a blank description yields a polite acknowledgment with no invented specifics."""
    reply = draft_reply(escalated_decision(description="   "))
    assert reply.variant == ReplyVariant.ACKNOWLEDGMENT
    assert reply.reply_text == (
        "Thank you for contacting us.\n\n"
        "We have received your ticket, and a support specialist is reviewing it. "
        "We will get back to you as soon as we have an update.\n\n"
        "We appreciate your patience."
    )
    assert reply.cited_ticket_ids == []
    assert "milk packet" not in reply.reply_text


# ── Service Tests ──────────────────────────────────────────────────

@pytest_asyncio.fixture
async def reply_db(monkeypatch):
    """In-memory DB session with resolution_service.resolve_ticket stubbed."""
    from app.core.database import AsyncSessionLocal, init_db
    from app.services import resolution_service as resolution_service_module

    await init_db()
    async with AsyncSessionLocal() as db:
        calls = {"resolve": []}

        async def fake_resolve(session, ticket_id):
            calls["resolve"].append(ticket_id)
            if ticket_id == "N-MISSING":
                raise _import_ticket_not_found()(f"ticket not found: {ticket_id}")
            return decision(ticket_id=ticket_id)

        monkeypatch.setattr(resolution_service_module, "resolve_ticket", fake_resolve)
        yield db, calls


def _import_ticket_not_found():
    from app.services.resolution_engine import TicketNotFoundError

    return TicketNotFoundError


@pytest.mark.asyncio
async def test_generate_reply_creates_draft(reply_db):
    """US-01: generate_reply drafts and persists a reply for an auto-resolved ticket."""
    db, calls = reply_db
    record = await generate_reply(db, "N-010")
    assert record.ticket_id == "N-010"
    assert record.variant == ReplyVariant.ACTION_CONFIRMED
    assert record.status == ReplyStatus.DRAFT
    assert record.original_draft == record.final_body
    assert record.cited_ticket_ids == ["H-1010", "H-1011", "H-1012"]
    assert record.draft_history == []
    assert record.edited_by is None
    assert record.sent_at is None


@pytest.mark.asyncio
async def test_generate_reply_unknown_ticket_propagates(reply_db):
    """ERR_001: an unknown ticket propagates TicketNotFoundError."""
    db, calls = reply_db
    from app.services.resolution_engine import TicketNotFoundError

    with pytest.raises(TicketNotFoundError):
        await generate_reply(db, "N-MISSING")


@pytest.mark.asyncio
async def test_generate_reply_is_idempotent_upsert(reply_db):
    """BR-05: regenerating a never-edited draft refreshes final_body without duplication."""
    db, calls = reply_db
    first = await generate_reply(db, "N-010")
    second = await generate_reply(db, "N-010")
    assert second.ticket_id == first.ticket_id
    items, total = await list_replies(db, skip=0, limit=500)
    assert total == 1
    assert items[0].ticket_id == "N-010"


@pytest.mark.asyncio
async def test_generate_reply_preserves_agent_edit_on_regenerate(reply_db):
    """EC-04: regenerating a draft that an agent edited keeps the agent's final_body."""
    db, calls = reply_db
    await generate_reply(db, "N-010")
    edited = await edit_reply(db, "N-010", "Thank you for your patience — your replacement is on its way.", "agent-7")
    assert edited.final_body == "Thank you for your patience — your replacement is on its way."

    regenerated = await generate_reply(db, "N-010")
    assert regenerated.final_body == "Thank you for your patience — your replacement is on its way."
    assert regenerated.edited_by == "agent-7"
    assert len(regenerated.draft_history) == 1
    assert regenerated.original_draft != "Thank you for your patience — your replacement is on its way."


@pytest.mark.asyncio
async def test_generate_reply_never_overwrites_sent_reply(reply_db):
    """EC-04: a sent reply is returned unchanged by regeneration."""
    db, calls = reply_db
    await generate_reply(db, "N-010")
    await send_reply(db, "N-010")
    regenerated = await generate_reply(db, "N-010")
    assert regenerated.status == ReplyStatus.SENT
    assert regenerated.draft_history == []


@pytest.mark.asyncio
async def test_get_reply_returns_none_when_missing(reply_db):
    """ERR_002: no record for an unprocessed ticket returns None."""
    db, calls = reply_db
    assert await get_reply(db, "N-NEVER") is None


@pytest.mark.asyncio
async def test_get_reply_returns_record_after_generation(reply_db):
    """US-02: a generated reply is retrievable by ticket id."""
    db, calls = reply_db
    await generate_reply(db, "N-010")
    record = await get_reply(db, "N-010")
    assert record is not None
    assert record.ticket_id == "N-010"


@pytest.mark.asyncio
async def test_edit_reply_missing_record_404(reply_db):
    """ERR_002: editing a non-existent reply raises ReplyNotFoundError."""
    db, calls = reply_db
    with pytest.raises(ReplyNotFoundError):
        await edit_reply(db, "N-NEVER", "body")


@pytest.mark.asyncio
async def test_edit_reply_empty_body_rejected(reply_db):
    """ERR_007: an empty or whitespace body is rejected with 422 semantics."""
    db, calls = reply_db
    await generate_reply(db, "N-010")
    with pytest.raises(InvalidReplyBodyError):
        await edit_reply(db, "N-010", "   ")


@pytest.mark.asyncio
async def test_edit_reply_preserves_original_draft(reply_db):
    """BR-05 / US-02 S1: editing replaces final_body only; original_draft is immutable."""
    db, calls = reply_db
    original = await generate_reply(db, "N-010")
    edited = await edit_reply(db, "N-010", "Edited wording.", "agent-7")
    assert edited.final_body == "Edited wording."
    assert edited.original_draft == original.original_draft
    assert edited.edited_by == "agent-7"
    assert edited.edited_at is not None
    assert edited.status == ReplyStatus.DRAFT


@pytest.mark.asyncio
async def test_edit_reply_sent_reply_rejected(reply_db):
    """ERR_003: editing an already-sent reply raises ReplyAlreadySentError (409)."""
    db, calls = reply_db
    await generate_reply(db, "N-010")
    await send_reply(db, "N-010")
    with pytest.raises(ReplyAlreadySentError):
        await edit_reply(db, "N-010", "too late")


@pytest.mark.asyncio
async def test_send_reply_sends_draft_as_is(reply_db):
    """US-02 S1: sending with no body sends the current final_body."""
    db, calls = reply_db
    record = await generate_reply(db, "N-010")
    sent = await send_reply(db, "N-010")
    assert sent.status == ReplyStatus.SENT
    assert sent.sent_at is not None
    assert sent.final_body == record.final_body
    assert sent.original_draft == record.original_draft


@pytest.mark.asyncio
async def test_send_reply_with_final_edit(reply_db):
    """US-02 S1: sending with a body applies the final edit in one step."""
    db, calls = reply_db
    await generate_reply(db, "N-010")
    sent = await send_reply(db, "N-010", body="Final agent wording.", edited_by="agent-7")
    assert sent.status == ReplyStatus.SENT
    assert sent.final_body == "Final agent wording."
    assert sent.edited_by == "agent-7"
    assert sent.original_draft != "Final agent wording."


@pytest.mark.asyncio
async def test_send_reply_idempotent_on_already_sent(reply_db):
    """send_reply never raises for an already-sent reply (idempotent)."""
    db, calls = reply_db
    await generate_reply(db, "N-010")
    first = await send_reply(db, "N-010")
    second = await send_reply(db, "N-010")
    assert second.status == ReplyStatus.SENT
    assert second.sent_at == first.sent_at


@pytest.mark.asyncio
async def test_send_reply_missing_record_404(reply_db):
    """ERR_002: sending a non-existent reply raises ReplyNotFoundError."""
    db, calls = reply_db
    with pytest.raises(ReplyNotFoundError):
        await send_reply(db, "N-NEVER")


@pytest.mark.asyncio
async def test_list_replies_pagination(reply_db):
    """US-02: list_replies returns (items, total) with skip/limit pagination."""
    db, calls = reply_db
    await generate_reply(db, "N-010")
    await generate_reply(db, "N-011")
    items, total = await list_replies(db, skip=0, limit=1)
    assert total == 2
    assert len(items) == 1
    items2, total2 = await list_replies(db, skip=1, limit=1)
    assert len(items2) == 1
    assert items2[0].ticket_id != items[0].ticket_id


@pytest.mark.asyncio
async def test_compute_reply_stats_aggregates(reply_db):
    """US-03/F5: stats count drafts, sent, and per-variant totals."""
    db, calls = reply_db
    await generate_reply(db, "N-010")  # action_confirmed
    await generate_reply(db, "N-011")  # action_confirmed (default decision)
    await generate_reply(db, "N-012")
    await send_reply(db, "N-010")
    stats = await compute_reply_stats(db)
    assert stats.total_replies == 3
    assert stats.draft_count == 2
    assert stats.sent_count == 1
    assert stats.by_variant.get(ReplyVariant.ACTION_CONFIRMED.value) == 3


# ── API Integration Tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_endpoint_returns_200(seeded_client, monkeypatch):
    """US-01: POST /api/v1/replies/generate returns a ReplyRecord."""
    await _stub_resolve(monkeypatch)
    response = await seeded_client.post("/api/v1/replies/generate", json={"ticket_id": "N-010"})
    assert response.status_code == 200
    data = response.json()
    assert data["ticket_id"] == "N-010"
    assert data["variant"] in {v.value for v in ReplyVariant}
    assert data["status"] in {s.value for s in ReplyStatus}
    assert "reply_text" not in data  # ReplyRecord shape, not DraftedReply
    assert "original_draft" in data
    assert "final_body" in data
    assert "draft_history" in data


@pytest.mark.asyncio
async def test_generate_endpoint_unknown_ticket_404(seeded_client, monkeypatch):
    """ERR_001: unknown ticket returns 404."""
    await _stub_resolve(monkeypatch)
    response = await seeded_client.post("/api/v1/replies/generate", json={"ticket_id": "N-MISSING"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_generate_endpoint_empty_ticket_id_422(seeded_client, monkeypatch):
    """ERR_008: empty/missing ticket_id fails FastAPI body validation."""
    await _stub_resolve(monkeypatch)
    response = await seeded_client.post("/api/v1/replies/generate", json={"ticket_id": ""})
    assert response.status_code == 422
    response = await seeded_client.post("/api/v1/replies/generate", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_endpoint_returns_paginated(seeded_client, monkeypatch):
    """US-02: GET /api/v1/replies returns the paginated reply log."""
    await _stub_resolve(monkeypatch)
    await seeded_client.post("/api/v1/replies/generate", json={"ticket_id": "N-010"})
    response = await seeded_client.get("/api/v1/replies")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "skip" in data
    assert "limit" in data
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_list_endpoint_pagination_validation(seeded_client, monkeypatch):
    """ERR_008: invalid pagination query params fail validation (422)."""
    await _stub_resolve(monkeypatch)
    response = await seeded_client.get("/api/v1/replies", params={"skip": -1})
    assert response.status_code == 422
    response = await seeded_client.get("/api/v1/replies", params={"limit": 0})
    assert response.status_code == 422
    response = await seeded_client.get("/api/v1/replies", params={"limit": 501})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_stats_endpoint_not_captured_by_ticket_id(seeded_client, monkeypatch):
    """Route ordering: GET /api/v1/replies/stats must not be captured by {ticket_id}."""
    await _stub_resolve(monkeypatch)
    response = await seeded_client.get("/api/v1/replies/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_replies" in data
    assert "draft_count" in data
    assert "sent_count" in data
    assert "by_variant" in data


@pytest.mark.asyncio
async def test_detail_endpoint_returns_record(seeded_client, monkeypatch):
    """US-02: GET /api/v1/replies/{ticket_id} returns the record after generation."""
    await _stub_resolve(monkeypatch)
    await seeded_client.post("/api/v1/replies/generate", json={"ticket_id": "N-010"})
    response = await seeded_client.get("/api/v1/replies/N-010")
    assert response.status_code == 200
    assert response.json()["ticket_id"] == "N-010"


@pytest.mark.asyncio
async def test_detail_endpoint_unknown_404(seeded_client, monkeypatch):
    """ERR_002: no record for an unprocessed ticket returns 404."""
    await _stub_resolve(monkeypatch)
    response = await seeded_client.get("/api/v1/replies/N-7777")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_edit_endpoint_updates_final_body(seeded_client, monkeypatch):
    """US-02 S1: PUT /api/v1/replies/{ticket_id} edits an unsent draft."""
    await _stub_resolve(monkeypatch)
    await seeded_client.post("/api/v1/replies/generate", json={"ticket_id": "N-010"})
    response = await seeded_client.put(
        "/api/v1/replies/N-010",
        json={"body": "Edited by agent.", "edited_by": "agent-7"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["final_body"] == "Edited by agent."
    assert data["edited_by"] == "agent-7"
    assert data["status"] == ReplyStatus.DRAFT.value


@pytest.mark.asyncio
async def test_edit_endpoint_sent_reply_409(seeded_client, monkeypatch):
    """ERR_003: editing a sent reply returns 409."""
    await _stub_resolve(monkeypatch)
    await seeded_client.post("/api/v1/replies/generate", json={"ticket_id": "N-010"})
    await seeded_client.post("/api/v1/replies/N-010/send", json={})
    response = await seeded_client.put("/api/v1/replies/N-010", json={"body": "too late"})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_edit_endpoint_empty_body_422(seeded_client, monkeypatch):
    """ERR_007: an empty edit body returns 422."""
    await _stub_resolve(monkeypatch)
    await seeded_client.post("/api/v1/replies/generate", json={"ticket_id": "N-010"})
    response = await seeded_client.put("/api/v1/replies/N-010", json={"body": "   "})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_send_endpoint_marks_sent(seeded_client, monkeypatch):
    """US-02 S1: POST /api/v1/replies/{ticket_id}/send marks the reply sent."""
    await _stub_resolve(monkeypatch)
    await seeded_client.post("/api/v1/replies/generate", json={"ticket_id": "N-010"})
    response = await seeded_client.post("/api/v1/replies/N-010/send", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == ReplyStatus.SENT.value
    assert data["sent_at"] is not None


@pytest.mark.asyncio
async def test_send_endpoint_unknown_404(seeded_client, monkeypatch):
    """ERR_002: sending a reply for an unprocessed ticket returns 404."""
    await _stub_resolve(monkeypatch)
    response = await seeded_client.post("/api/v1/replies/N-7777/send", json={})
    assert response.status_code == 404


async def _stub_resolve(monkeypatch):
    """Stub resolution_service.resolve_ticket so API tests are deterministic."""
    from app.services import resolution_service as resolution_service_module

    async def fake_resolve(session, ticket_id):
        if ticket_id == "N-MISSING":
            from app.services.resolution_engine import TicketNotFoundError

            raise TicketNotFoundError(f"ticket not found: {ticket_id}")
        return decision(ticket_id=ticket_id)

    monkeypatch.setattr(resolution_service_module, "resolve_ticket", fake_resolve)
