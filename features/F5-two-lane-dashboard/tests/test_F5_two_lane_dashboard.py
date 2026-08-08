"""Black-box tests for F5 Two-Lane Dashboard (FEAT-005).

Generated exclusively from:
- `features/F5-two-lane-dashboard/1_spec.md` (user stories, acceptance
  criteria, business rules BR-01..BR-05, edge cases EC-01..EC-06)
- `features/F5-two-lane-dashboard/2_tech_spec.md` (interface contracts:
  Pydantic models §2.1, pure functions §2.2, service errors §2.3,
  route handlers §2.4, error table §5, traceability §6)

No implementation source was read. Every test targets a public contract
and must pass for ANY correct implementation of the spec.
"""

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard_models import (
    ConfidenceLevel,
    DashboardBoard,
    DashboardLane,
    DashboardLaneSection,
    DashboardTicketCard,
    DashboardTicketDetail,
    ReplySummary,
    SimilarCaseEvidence,
    SimilarCasesStatus,
)
from app.services.dashboard_service import (
    confidence_level,
    lane_for,
    truncate_description,
)


# ---------------------------------------------------------------------------
# Seed helpers (data shaped by 2_tech_spec.md §3.1 / §4.1 examples)
# ---------------------------------------------------------------------------

def _base_auto_ticket():
    """Auto-resolved ticket mirroring the §4.1 example (N-002)."""
    return {
        "ticket_id": "N-002",
        "order_id": "ORD-1001",
        "description": "milk packet missing from my order, delivered today at 6pm",
        "action": "redelivery",
        "confidence": 0.93,
        "auto_resolved": True,
        "escalation_reason": None,
        "reasoning": "Auto-resolved: all 3 similar past cases were resolved by "
        "redelivery and confidence 0.93 meets the 0.75 threshold.",
        "similar_ticket_ids": ["H-1000", "H-1001", "H-1002"],
        "created_at": "2026-08-08T09:00:00+00:00",
    }


def _base_review_ticket():
    """Escalated ticket mirroring the §4.1 example (N-003)."""
    return {
        "ticket_id": "N-003",
        "order_id": "ORD-1002",
        "description": "fruits were rotten in the delivered box",
        "action": None,
        "confidence": 0.31,
        "auto_resolved": False,
        "escalation_reason": "low_confidence",
        "reasoning": "Escalated: confidence 0.31 is below the 0.75 auto-resolution threshold.",
        "similar_ticket_ids": None,
        "created_at": "2026-08-08T08:45:00+00:00",
    }


async def _seed_ticket(db: AsyncSession, ticket: dict) -> None:
    """Insert one processed ticket into decision_log + new_tickets (+ reply_log)."""
    await db.execute(
        text(
            "INSERT INTO decision_log "
            "(ticket_id, order_id, action, confidence, auto_resolved, escalation_reason, "
            " similar_ticket_ids, reasoning, refund_amount, created_at) "
            "VALUES (:ticket_id, :order_id, :action, :confidence, :auto_resolved, "
            " :escalation_reason, :similar_ticket_ids, :reasoning, :refund_amount, :created_at)"
        ),
        {
            "ticket_id": ticket["ticket_id"],
            "order_id": ticket.get("order_id", "ORD-1001"),
            "action": ticket.get("action"),
            "confidence": ticket["confidence"],
            "auto_resolved": ticket["auto_resolved"],
            "escalation_reason": ticket.get("escalation_reason"),
            "similar_ticket_ids": (
                json.dumps(ticket["similar_ticket_ids"])
                if ticket.get("similar_ticket_ids") is not None
                else None
            ),
            "reasoning": ticket.get("reasoning", "Reasoning text."),
            "refund_amount": ticket.get("refund_amount"),
            "created_at": ticket["created_at"],
        },
    )
    await db.execute(
        text(
            "INSERT INTO new_tickets (ticket_id, order_id, description) "
            "VALUES (:ticket_id, :order_id, :description)"
        ),
        {
            "ticket_id": ticket["ticket_id"],
            "order_id": ticket.get("order_id", "ORD-1001"),
            "description": ticket["description"],
        },
    )
    reply = ticket.get("reply")
    if reply is not None:
        await db.execute(
            text(
                "INSERT INTO reply_log (ticket_id, variant, final_body, status) "
                "VALUES (:ticket_id, :variant, :final_body, :status)"
            ),
            {
                "ticket_id": ticket["ticket_id"],
                "variant": reply["variant"],
                "final_body": reply["final_body"],
                "status": reply["status"],
            },
        )
    await db.commit()


async def _seed_resolved_case(db: AsyncSession, case: dict) -> None:
    """Insert one past resolved ticket used as similar-case evidence (BR-03)."""
    await db.execute(
        text(
            "INSERT INTO resolved_tickets (ticket_id, description, action_taken, resolution_note) "
            "VALUES (:ticket_id, :description, :action_taken, :resolution_note)"
        ),
        case,
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Feature: Two-Lane Dashboard (FEAT-005)
# ---------------------------------------------------------------------------

class TestTwoLaneDashboard:
    """Tests for the Two-Lane Dashboard feature."""

    # ------------------------------------------------------------------
    # US-01 / BR-01 — lane_for()
    # ------------------------------------------------------------------

    class TestLaneAssignmentFunction:
        """US-01 · BR-01: a ticket belongs to exactly one lane per its resolution outcome."""

        def test_auto_resolved_ticket_maps_to_auto_resolved_lane(self):
            """Given a ticket was auto-resolved, When mapping its lane, Then it is the Auto-Resolved lane."""
            assert lane_for(True) == DashboardLane.AUTO_RESOLVED

        def test_escalated_ticket_maps_to_needs_review_lane(self):
            """Given a ticket was escalated, When mapping its lane, Then it is the Needs Human Review lane."""
            assert lane_for(False) == DashboardLane.NEEDS_REVIEW

        def test_lane_values_match_dashboard_lane_enum(self):
            """The returned lane carries the canonical wire value (US-01 S1)."""
            assert lane_for(True).value == "auto_resolved"
            assert lane_for(False).value == "needs_review"

    # ------------------------------------------------------------------
    # US-02 S1 / EC-04 / ERR_DASH_003 — confidence_level()
    # ------------------------------------------------------------------

    class TestConfidenceLevelFunction:
        """US-02 S1 · EC-04: bucket the decision confidence for color-coding without altering it."""

        def test_score_at_or_above_high_threshold_is_high(self):
            """Given a confidence at or above 0.75, Then it is color-coded high (EC-04 boundary inclusive)."""
            assert confidence_level(0.93) == ConfidenceLevel.HIGH
            assert confidence_level(0.75) == ConfidenceLevel.HIGH
            assert confidence_level(1.0) == ConfidenceLevel.HIGH

        def test_score_between_medium_and_high_thresholds_is_medium(self):
            """Given a confidence between 0.40 and 0.75, Then it is color-coded medium."""
            assert confidence_level(0.55) == ConfidenceLevel.MEDIUM
            assert confidence_level(0.7499) == ConfidenceLevel.MEDIUM

        def test_score_at_medium_threshold_is_medium(self):
            """Given a confidence of exactly 0.40, Then it is color-coded medium (EC-04 boundary inclusive)."""
            assert confidence_level(0.40) == ConfidenceLevel.MEDIUM

        def test_score_below_medium_threshold_is_low(self):
            """Given a confidence below 0.40, Then it is color-coded low."""
            assert confidence_level(0.31) == ConfidenceLevel.LOW
            assert confidence_level(0.0) == ConfidenceLevel.LOW
            assert confidence_level(0.3999) == ConfidenceLevel.LOW

        def test_custom_thresholds_are_respected(self):
            """The high/medium bucket floors are configurable."""
            assert (
                confidence_level(0.8, high_threshold=0.9, medium_threshold=0.5)
                == ConfidenceLevel.MEDIUM
            )
            assert (
                confidence_level(0.9, high_threshold=0.9, medium_threshold=0.5)
                == ConfidenceLevel.HIGH
            )

        def test_score_outside_unit_range_raises_value_error(self):
            """Given a score outside [0,1], Then ValueError is raised (ERR_DASH_003)."""
            with pytest.raises(ValueError):
                confidence_level(-0.01)
            with pytest.raises(ValueError):
                confidence_level(1.01)

        def test_invalid_thresholds_raise_value_error(self):
            """Given thresholds outside [0,1] or high < medium, Then ValueError is raised (ERR_DASH_003)."""
            with pytest.raises(ValueError):
                confidence_level(0.5, high_threshold=0.3, medium_threshold=0.5)
            with pytest.raises(ValueError):
                confidence_level(0.5, high_threshold=1.5, medium_threshold=0.4)
            with pytest.raises(ValueError):
                confidence_level(0.5, high_threshold=0.75, medium_threshold=-0.1)

    # ------------------------------------------------------------------
    # US-02 S2 / EC-03 / ERR_DASH_004 — truncate_description()
    # ------------------------------------------------------------------

    class TestDescriptionTruncationFunction:
        """US-02 S2 · EC-03: shorten long descriptions for cards with an ellipsis."""

        def test_short_description_is_returned_unchanged(self):
            """Given a description at or under max_chars, Then it is returned unchanged."""
            short = "milk packet missing"
            assert truncate_description(short) == short

        def test_description_at_max_chars_is_returned_unchanged(self):
            """Given a description exactly max_chars long, Then it is returned unchanged."""
            text_120 = "a" * 120
            assert truncate_description(text_120) == text_120

        def test_short_description_at_custom_max_chars_is_returned_unchanged(self):
            assert truncate_description("ab", max_chars=2) == "ab"

        def test_long_description_is_truncated_with_ellipsis_within_limit(self):
            """Given a very long description, Then the card preview is <= max_chars and ends with an ellipsis (EC-03)."""
            long_text = "b" * 500
            preview = truncate_description(long_text)
            assert len(preview) <= 120
            assert preview.endswith("…")
            assert long_text.startswith(preview[:-1])

        def test_custom_max_chars_is_respected(self):
            """The preview honors a custom max length."""
            long_text = "c" * 100
            preview = truncate_description(long_text, max_chars=20)
            assert len(preview) <= 20
            assert preview.endswith("…")

        def test_max_chars_of_one_returns_single_ellipsis(self):
            """Given max_chars=1 and a long text, Then the preview is the single ellipsis character."""
            preview = truncate_description("hello world", max_chars=1)
            assert len(preview) <= 1
            assert preview.endswith("…")

        def test_empty_description_is_returned_unchanged(self):
            assert truncate_description("") == ""

        def test_max_chars_below_one_raises_value_error(self):
            """Given max_chars < 1, Then ValueError is raised (ERR_DASH_004)."""
            with pytest.raises(ValueError):
                truncate_description("text", max_chars=0)
            with pytest.raises(ValueError):
                truncate_description("text", max_chars=-5)

    # ------------------------------------------------------------------
    # §2.1 Pydantic model contracts
    # ------------------------------------------------------------------

    class TestDashboardModels:
        """Contract tests for the §2.1 Pydantic models / §3.2 field constraints."""

        def test_lane_enum_values(self):
            assert DashboardLane.AUTO_RESOLVED.value == "auto_resolved"
            assert DashboardLane.NEEDS_REVIEW.value == "needs_review"

        def test_confidence_level_enum_values(self):
            assert ConfidenceLevel.HIGH.value == "high"
            assert ConfidenceLevel.MEDIUM.value == "medium"
            assert ConfidenceLevel.LOW.value == "low"

        def test_similar_cases_status_enum_values(self):
            assert SimilarCasesStatus.FOUND.value == "found"
            assert SimilarCasesStatus.NONE.value == "none"

        def test_ticket_card_accepts_valid_payload(self):
            card = DashboardTicketCard(
                ticket_id="N-002",
                description_preview="milk packet missing…",
                action="redelivery",
                confidence=0.93,
                confidence_level=ConfidenceLevel.HIGH,
                lane=DashboardLane.AUTO_RESOLVED,
                auto_resolved=True,
                escalation_reason=None,
                created_at="2026-08-08T09:00:00+00:00",
            )
            assert card.ticket_id == "N-002"
            assert card.confidence == 0.93
            assert card.confidence_level == ConfidenceLevel.HIGH

        def test_ticket_card_requires_mandatory_fields(self):
            with pytest.raises(ValidationError):
                DashboardTicketCard(
                    description_preview="milk packet missing…",
                    action="redelivery",
                    confidence=0.93,
                    confidence_level=ConfidenceLevel.HIGH,
                    lane=DashboardLane.AUTO_RESOLVED,
                    auto_resolved=True,
                    escalation_reason=None,
                    created_at="2026-08-08T09:00:00+00:00",
                )

        def test_ticket_card_rejects_confidence_outside_unit_range(self):
            """Confidence must stay within [0.0, 1.0] (BR-02, §3.2 constraint)."""
            with pytest.raises(ValidationError):
                DashboardTicketCard(
                    ticket_id="N-002",
                    description_preview="preview",
                    confidence=1.5,
                    confidence_level=ConfidenceLevel.HIGH,
                    lane=DashboardLane.AUTO_RESOLVED,
                    auto_resolved=True,
                    escalation_reason=None,
                    created_at="2026-08-08T09:00:00+00:00",
                )
            with pytest.raises(ValidationError):
                DashboardTicketCard(
                    ticket_id="N-002",
                    description_preview="preview",
                    confidence=-0.1,
                    confidence_level=ConfidenceLevel.HIGH,
                    lane=DashboardLane.AUTO_RESOLVED,
                    auto_resolved=True,
                    escalation_reason=None,
                    created_at="2026-08-08T09:00:00+00:00",
                )

        def test_ticket_card_rejects_unknown_confidence_level(self):
            with pytest.raises(ValidationError):
                DashboardTicketCard(
                    ticket_id="N-002",
                    description_preview="preview",
                    confidence=0.93,
                    confidence_level="very_high",
                    lane=DashboardLane.AUTO_RESOLVED,
                    auto_resolved=True,
                    escalation_reason=None,
                    created_at="2026-08-08T09:00:00+00:00",
                )

        def test_lane_section_defaults_to_empty_ticket_list(self):
            section = DashboardLaneSection(label="Auto-Resolved", count=0)
            assert section.tickets == []

        def test_lane_section_rejects_negative_count(self):
            """The count badge can never be negative (§3.2)."""
            with pytest.raises(ValidationError):
                DashboardLaneSection(label="Auto-Resolved", count=-1)

        def test_board_requires_both_lane_sections(self):
            """BR-04: both lanes are always present in the board payload."""
            with pytest.raises(ValidationError):
                DashboardBoard(
                    loaded_at="2026-08-08T09:00:00+00:00",
                    auto_resolved=DashboardLaneSection(label="Auto-Resolved", count=0),
                )

        def test_board_accepts_both_lane_sections(self):
            board = DashboardBoard(
                loaded_at="2026-08-08T09:00:00+00:00",
                auto_resolved=DashboardLaneSection(label="Auto-Resolved", count=0),
                needs_review=DashboardLaneSection(label="Needs Human Review", count=0),
            )
            assert board.loaded_at
            assert board.auto_resolved.label == "Auto-Resolved"
            assert board.needs_review.label == "Needs Human Review"

        def test_similar_case_evidence_rejects_score_outside_unit_range(self):
            with pytest.raises(ValidationError):
                SimilarCaseEvidence(
                    ticket_id="H-1000",
                    description="d",
                    action_taken="a",
                    resolution_note="r",
                    similarity_score=1.2,
                )

        def test_detail_defaults_similar_cases_to_empty_and_reply_to_none(self):
            detail = DashboardTicketDetail(
                ticket_id="N-002",
                order_id="ORD-1001",
                description="full description",
                action=None,
                confidence=0.9,
                confidence_level=ConfidenceLevel.HIGH,
                lane=DashboardLane.AUTO_RESOLVED,
                auto_resolved=True,
                escalation_reason=None,
                reasoning="reasoning",
                refund_amount=None,
                similar_cases_status=SimilarCasesStatus.NONE,
                reply=None,
                created_at="2026-08-08T09:00:00+00:00",
            )
            assert detail.similar_cases == []
            assert detail.reply is None

        def test_reply_summary_fields(self):
            reply = ReplySummary(
                final_body="customer-facing reply",
                variant="action_confirmed",
                status="draft",
            )
            assert reply.final_body == "customer-facing reply"
            assert reply.variant == "action_confirmed"
            assert reply.status == "draft"

    # ------------------------------------------------------------------
    # US-01 / US-02 / US-04 / EC-01..EC-06 / BR-01..BR-05 —
    # GET /api/v1/dashboard
    # ------------------------------------------------------------------

    class TestDashboardBoardEndpoint:
        """`GET /api/v1/dashboard` — the two-lane board (US-01, US-02, US-04)."""

        @pytest.mark.asyncio
        async def test_board_shows_two_labeled_lanes_with_count_badges(self, client, db_session):
            """US-01 S1: Given tickets in both lanes, When I open the dashboard,
            Then I see two labeled lanes, each ticket in the matching lane, with count badges."""
            await _seed_ticket(db_session, _base_auto_ticket())
            await _seed_ticket(db_session, _base_review_ticket())

            resp = await client.get("/api/v1/dashboard")
            assert resp.status_code == 200
            payload = resp.json()

            assert payload["auto_resolved"]["label"] == "Auto-Resolved"
            assert payload["needs_review"]["label"] == "Needs Human Review"
            assert payload["auto_resolved"]["count"] == 1
            assert payload["needs_review"]["count"] == 1
            assert payload["auto_resolved"]["count"] == len(payload["auto_resolved"]["tickets"])
            assert payload["needs_review"]["count"] == len(payload["needs_review"]["tickets"])
            assert payload["auto_resolved"]["tickets"][0]["ticket_id"] == "N-002"
            assert payload["needs_review"]["tickets"][0]["ticket_id"] == "N-003"
            assert payload["loaded_at"]

        @pytest.mark.asyncio
        async def test_card_lane_matches_resolution_outcome(self, client, db_session):
            """BR-01: each card appears in the lane matching its processing outcome."""
            await _seed_ticket(db_session, _base_auto_ticket())
            await _seed_ticket(db_session, _base_review_ticket())

            payload = (await client.get("/api/v1/dashboard")).json()

            for card in payload["auto_resolved"]["tickets"]:
                assert card["lane"] == "auto_resolved"
                assert card["auto_resolved"] is True
                assert card["escalation_reason"] is None
            for card in payload["needs_review"]["tickets"]:
                assert card["lane"] == "needs_review"
                assert card["auto_resolved"] is False
                assert card["escalation_reason"] == "low_confidence"

        @pytest.mark.asyncio
        async def test_board_with_no_processed_tickets_shows_two_empty_lanes(self, client, db_session):
            """EC-01: Given no tickets have been processed, Then both lanes are present with
            zero count badges and empty ticket lists (BR-04)."""
            resp = await client.get("/api/v1/dashboard")
            assert resp.status_code == 200
            payload = resp.json()

            assert payload["auto_resolved"]["label"] == "Auto-Resolved"
            assert payload["needs_review"]["label"] == "Needs Human Review"
            assert payload["auto_resolved"]["count"] == 0
            assert payload["needs_review"]["count"] == 0
            assert payload["auto_resolved"]["tickets"] == []
            assert payload["needs_review"]["tickets"] == []

        @pytest.mark.asyncio
        async def test_empty_lane_still_present_when_only_auto_resolved_tickets_exist(self, client, db_session):
            """US-01 S2: Given no tickets were escalated, Then the Needs Human Review lane is
            still present with a zero badge and empty list, while Auto-Resolved renders normally."""
            await _seed_ticket(db_session, _base_auto_ticket())

            payload = (await client.get("/api/v1/dashboard")).json()

            assert payload["auto_resolved"]["count"] == 1
            assert len(payload["auto_resolved"]["tickets"]) == 1
            assert payload["needs_review"]["count"] == 0
            assert payload["needs_review"]["tickets"] == []

        @pytest.mark.asyncio
        async def test_newly_processed_tickets_appear_ordered_newest_first(self, client, db_session):
            """US-04 S1: Given the system just processed a new ticket, When I open/refresh the
            dashboard, Then it appears in the correct lane and the count badge is updated.
            Ordering is created_at DESC, ticket_id DESC (§2.3)."""
            older = dict(_base_auto_ticket(), ticket_id="N-002", created_at="2026-08-08T08:00:00+00:00")
            newer = dict(_base_auto_ticket(), ticket_id="N-004", created_at="2026-08-08T10:00:00+00:00")
            await _seed_ticket(db_session, older)
            await _seed_ticket(db_session, newer)

            payload = (await client.get("/api/v1/dashboard")).json()

            ids = [c["ticket_id"] for c in payload["auto_resolved"]["tickets"]]
            assert ids == ["N-004", "N-002"]
            assert payload["auto_resolved"]["count"] == 2

        @pytest.mark.asyncio
        async def test_card_shows_short_description_action_and_color_coded_confidence(self, client, db_session):
            """US-02 S1: the card shows a short description, the action (or review label),
            and a confidence score bucketed for color-coding."""
            await _seed_ticket(db_session, _base_auto_ticket())
            await _seed_ticket(db_session, _base_review_ticket())

            payload = (await client.get("/api/v1/dashboard")).json()
            auto_card = payload["auto_resolved"]["tickets"][0]
            review_card = payload["needs_review"]["tickets"][0]

            assert auto_card["description_preview"] == _base_auto_ticket()["description"]
            assert auto_card["action"] == "redelivery"
            assert auto_card["confidence"] == 0.93  # BR-02: unmodified
            assert auto_card["confidence_level"] == "high"
            assert auto_card["created_at"]

            assert review_card["action"] is None
            assert review_card["confidence"] == 0.31  # BR-02: unmodified
            assert review_card["confidence_level"] == "low"

        @pytest.mark.asyncio
        async def test_long_description_is_truncated_with_ellipsis_on_card(self, client, db_session):
            """EC-03: Given a very long description, Then the card preview is shortened
            with an ellipsis and stays readable (≤ 120 chars)."""
            long_desc = " ".join(["the package arrived damaged and the contents spilled"] * 6)
            assert len(long_desc) > 120
            await _seed_ticket(
                db_session,
                dict(_base_auto_ticket(), ticket_id="N-005", description=long_desc, confidence=0.80),
            )

            payload = (await client.get("/api/v1/dashboard")).json()
            preview = payload["auto_resolved"]["tickets"][0]["description_preview"]

            assert len(preview) <= 120
            assert preview.endswith("…")

        @pytest.mark.asyncio
        async def test_boundary_confidence_scores_are_bucketed_inclusively(self, client, db_session):
            """EC-04: a confidence of exactly 0.75 is high and exactly 0.40 is medium,
            with the score itself displayed unmodified (BR-02)."""
            await _seed_ticket(db_session, dict(_base_auto_ticket(), ticket_id="N-006", confidence=0.75))
            await _seed_ticket(db_session, dict(_base_auto_ticket(), ticket_id="N-007", confidence=0.40))

            payload = (await client.get("/api/v1/dashboard")).json()
            by_id = {c["ticket_id"]: c for c in payload["auto_resolved"]["tickets"]}

            assert by_id["N-006"]["confidence"] == 0.75
            assert by_id["N-006"]["confidence_level"] == "high"
            assert by_id["N-007"]["confidence"] == 0.40
            assert by_id["N-007"]["confidence_level"] == "medium"

        @pytest.mark.asyncio
        async def test_high_volume_board_reports_accurate_counts(self, client, db_session):
            """EC-05: Given a very high volume of processed tickets, Then cards remain compact
            and each lane reports a running count badge."""
            for i in range(5):
                await _seed_ticket(
                    db_session,
                    dict(
                        _base_auto_ticket(),
                        ticket_id=f"N-0{i + 10}",
                        created_at=f"2026-08-08T0{i + 1}:00:00+00:00",
                    ),
                )

            payload = (await client.get("/api/v1/dashboard")).json()

            assert payload["auto_resolved"]["count"] == 5
            assert len(payload["auto_resolved"]["tickets"]) == 5
            assert payload["needs_review"]["count"] == 0

        @pytest.mark.asyncio
        async def test_board_is_read_only_and_rejects_mutation_methods(self, client, db_session):
            """BR-05: the dashboard exposes GET-only endpoints and never mutates state."""
            await _seed_ticket(db_session, _base_auto_ticket())

            assert (await client.post("/api/v1/dashboard")).status_code == 405
            assert (await client.delete("/api/v1/dashboard/tickets/N-002")).status_code == 405
            assert (await client.put("/api/v1/dashboard/tickets/N-002", json={})).status_code == 405

        @pytest.mark.asyncio
        async def test_board_returns_500_with_clear_message_when_data_unavailable(self, client, db_engine):
            """EC-06 / US-04 S2 / ERR_DASH_001: Given the data source is unavailable,
            Then the dashboard returns 500 with a clear message instead of a partial board."""
            await db_engine.dispose()

            resp = await client.get("/api/v1/dashboard")
            assert resp.status_code == 500
            assert "unavailable" in resp.json()["detail"].lower()

    # ------------------------------------------------------------------
    # US-03 / EC-02 / ERR_DASH_002 / ERR_DASH_005 —
    # GET /api/v1/dashboard/tickets/{ticket_id}
    # ------------------------------------------------------------------

    class TestTicketDetailEndpoint:
        """`GET /api/v1/dashboard/tickets/{ticket_id}` — full read-only detail (US-03)."""

        @pytest.mark.asyncio
        async def test_detail_shows_full_description_similar_cases_action_reasoning_and_reply(
            self, client, db_session
        ):
            """US-03 S1: Given a processed ticket with similar past cases, When I open its
            detail, Then I see the full description, top-3 similar cases with scores, the
            action, the plain-language reasoning, and the drafted reply."""
            ticket = _base_auto_ticket()
            ticket["reply"] = {
                "variant": "action_confirmed",
                "final_body": "Thank you for reaching out. We are sorry the milk packet was "
                "missing — we have arranged a redelivery, matching how similar issues were "
                "resolved in the past.",
                "status": "draft",
            }
            await _seed_ticket(db_session, ticket)
            await _seed_resolved_case(
                db_session,
                {
                    "ticket_id": "H-1000",
                    "description": "milk packet missing from my order",
                    "action_taken": "redelivery",
                    "resolution_note": "missing item re-sent",
                },
            )
            await _seed_resolved_case(
                db_session,
                {
                    "ticket_id": "H-1001",
                    "description": "delivery arrived without the milk packet",
                    "action_taken": "redelivery",
                    "resolution_note": "item re-sent",
                },
            )
            await _seed_resolved_case(
                db_session,
                {
                    "ticket_id": "H-1002",
                    "description": "milk packet was not included in the order",
                    "action_taken": "redelivery",
                    "resolution_note": "redelivered",
                },
            )

            resp = await client.get("/api/v1/dashboard/tickets/N-002")
            assert resp.status_code == 200
            detail = resp.json()

            assert detail["ticket_id"] == "N-002"
            assert detail["order_id"] == "ORD-1001"
            # EC-03: the detail view shows the full, untruncated description
            assert detail["description"] == _base_auto_ticket()["description"]
            assert detail["action"] == "redelivery"
            assert detail["confidence"] == 0.93  # BR-02: unmodified
            assert detail["confidence_level"] == "high"
            assert detail["lane"] == "auto_resolved"
            assert detail["auto_resolved"] is True
            assert detail["escalation_reason"] is None
            # BR-03: reasoning is verbatim from decision_log
            assert detail["reasoning"] == ticket["reasoning"]
            assert detail["refund_amount"] is None
            assert detail["similar_cases_status"] == "found"
            assert 1 <= len(detail["similar_cases"]) <= 3
            for case in detail["similar_cases"]:
                assert case["ticket_id"]
                assert case["description"]
                assert case["action_taken"]
                assert case["resolution_note"]
                assert 0.0 <= case["similarity_score"] <= 1.0
            assert detail["reply"]["variant"] == "action_confirmed"
            assert detail["reply"]["status"] == "draft"
            assert detail["reply"]["final_body"] == ticket["reply"]["final_body"]
            assert detail["created_at"]

        @pytest.mark.asyncio
        async def test_detail_with_no_similar_past_cases_states_none_and_still_shows_decision(
            self, client, db_session
        ):
            """US-03 S2 / EC-02: Given a ticket with no similar past cases, Then the detail
            states 'none' while still showing the action, reasoning, and drafted reply."""
            ticket = _base_review_ticket()
            ticket["reply"] = {
                "variant": "no_precedent",
                "final_body": "We are reviewing this novel issue and will get back to you shortly.",
                "status": "draft",
            }
            await _seed_ticket(db_session, ticket)

            resp = await client.get("/api/v1/dashboard/tickets/N-003")
            assert resp.status_code == 200
            detail = resp.json()

            assert detail["similar_cases_status"] == "none"
            assert detail["similar_cases"] == []
            assert detail["action"] is None
            assert detail["reasoning"]
            assert detail["reply"] is not None
            assert detail["reply"]["final_body"]

        @pytest.mark.asyncio
        async def test_detail_for_unknown_ticket_returns_404(self, client, db_session):
            """ERR_DASH_002: Given no decision record exists for the ticket, Then the detail
            endpoint returns 404 with a clear message."""
            resp = await client.get("/api/v1/dashboard/tickets/N-999")
            assert resp.status_code == 404
            assert "no decision record" in resp.json()["detail"]

        @pytest.mark.asyncio
        async def test_detail_returns_500_when_data_unavailable(self, client, db_engine):
            """EC-06: Given the data source is unavailable, Then the detail endpoint returns 500."""
            await db_engine.dispose()

            resp = await client.get("/api/v1/dashboard/tickets/N-002")
            assert resp.status_code == 500
            assert "unavailable" in resp.json()["detail"].lower()

        @pytest.mark.asyncio
        async def test_detail_without_reply_record_returns_null_reply(self, client, db_session):
            """ERR_DASH_005: Given a processed ticket without a drafted reply, Then the reply
            field is null so the frontend can show a fallback message."""
            await _seed_ticket(db_session, _base_auto_ticket())

            detail = (await client.get("/api/v1/dashboard/tickets/N-002")).json()
            assert detail["reply"] is None

        @pytest.mark.asyncio
        async def test_refund_action_includes_refund_amount_and_other_actions_do_not(self, client, db_session):
            """The detail surfaces the computed refund amount for refund actions, and null
            for other actions (§3.2)."""
            await _seed_ticket(
                db_session,
                dict(
                    _base_auto_ticket(),
                    ticket_id="N-020",
                    description="charged twice for my order",
                    action="refund",
                    refund_amount=250.0,
                    created_at="2026-08-08T11:00:00+00:00",
                ),
            )
            await _seed_ticket(
                db_session,
                dict(
                    _base_auto_ticket(),
                    ticket_id="N-021",
                    description="package never arrived",
                    action="redelivery",
                    refund_amount=None,
                    created_at="2026-08-08T11:05:00+00:00",
                ),
            )

            refund = (await client.get("/api/v1/dashboard/tickets/N-020")).json()
            redelivery = (await client.get("/api/v1/dashboard/tickets/N-021")).json()
            assert refund["refund_amount"] == 250.0
            assert redelivery["refund_amount"] is None

        @pytest.mark.asyncio
        async def test_detail_lane_matches_resolution_outcome(self, client, db_session):
            """BR-01: the detail view's lane and escalation reason follow the resolution outcome."""
            await _seed_ticket(db_session, _base_review_ticket())

            detail = (await client.get("/api/v1/dashboard/tickets/N-003")).json()
            assert detail["lane"] == "needs_review"
            assert detail["auto_resolved"] is False
            assert detail["escalation_reason"] == "low_confidence"
