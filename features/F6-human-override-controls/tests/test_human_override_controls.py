"""Black-box tests for F6 Human Override Controls (FEAT-006).

Generated exclusively from:
- `features/F6-human-override-controls/1_spec.md` (user stories US-01..US-04,
  business rules, edge cases EC-01..EC-06)
- `features/F6-human-override-controls/2_tech_spec.md` (interface contracts:
  Pydantic models §2.1, pure engine functions §2.2, service errors §2.3,
  route handlers §2.4, API contracts §4, error table §5, traceability §6)

No implementation source was read. Every test targets a public contract
and must pass for ANY correct implementation of the spec.
"""

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.human_decision_models import (
    ApproveRequest,
    HumanAction,
    HumanDecisionListResponse,
    HumanDecisionRecord,
    OverrideRequest,
    RejectRequest,
)
from app.models.resolution_models import ResolutionAction
from app.services.human_decision_engine import (
    HumanDecisionEngineError,
    HumanDecisionInvalidActionError,
    HumanDecisionInvalidReasonError,
    HumanDecisionPolicyBlockedError,
    final_refund_for,
    normalize_override_action,
    validate_override_policy,
    validate_rejection_reason,
)
from app.services.human_decision_service import (
    HumanDecisionAlreadyHandledError,
    HumanDecisionInvalidAgentError,
    HumanDecisionNoSuggestionError,
    HumanDecisionNotActionableError,
    HumanDecisionTicketNotFoundError,
    approve_ticket,
    get_human_decision,
    list_human_decisions,
    override_ticket,
    reject_ticket,
)


# ---------------------------------------------------------------------------
# Seed helpers (data shaped by 2_tech_spec.md §4.1..§4.3 examples)
# ---------------------------------------------------------------------------

def _base_escalated_ticket(**overrides):
    """An escalated ticket (Needs Human Review) with a suggested action."""
    defaults = {
        "ticket_id": "N-003",
        "order_id": "ORD-1002",
        "description": "fruits were rotten in the delivered box",
        "action": "refund",                      # suggested action (US-01 S1)
        "confidence": 0.31,
        "auto_resolved": False,
        "escalation_reason": "low_confidence",
        "similar_ticket_ids": None,
        "reasoning": "Escalated: confidence 0.31 is below the auto-resolution threshold.",
        "refund_amount": None,
        "created_at": "2026-08-08T08:45:00+00:00",
    }
    defaults.update(overrides)
    return defaults


def _base_auto_resolved_ticket(**overrides):
    """An auto-resolved ticket (read-only; never actionable by a human)."""
    defaults = {
        "ticket_id": "N-002",
        "order_id": "ORD-1001",
        "description": "milk packet missing from my order",
        "action": "redelivery",
        "confidence": 0.93,
        "auto_resolved": True,
        "escalation_reason": None,
        "similar_ticket_ids": json.dumps(["H-1000", "H-1001", "H-1002"]),
        "reasoning": "Auto-resolved by the engine.",
        "refund_amount": None,
        "created_at": "2026-08-08T09:00:00+00:00",
    }
    defaults.update(overrides)
    return defaults


async def _seed_ticket(db: AsyncSession, **overrides) -> None:
    """Insert one processed ticket into decision_log + new_tickets (+ reply_log)."""
    row = _base_escalated_ticket(**overrides)
    await db.execute(
        text(
            "INSERT INTO decision_log "
            "(ticket_id, order_id, action, confidence, auto_resolved, escalation_reason, "
            " similar_ticket_ids, reasoning, refund_amount, created_at) "
            "VALUES (:ticket_id, :order_id, :action, :confidence, :auto_resolved, "
            " :escalation_reason, :similar_ticket_ids, :reasoning, :refund_amount, :created_at)"
        ),
        {
            "ticket_id": row["ticket_id"],
            "order_id": row["order_id"],
            "action": row.get("action"),
            "confidence": row["confidence"],
            "auto_resolved": row["auto_resolved"],
            "escalation_reason": row.get("escalation_reason"),
            "similar_ticket_ids": row.get("similar_ticket_ids"),
            "reasoning": row.get("reasoning", "Reasoning text."),
            "refund_amount": row.get("refund_amount"),
            "created_at": row["created_at"],
        },
    )
    await db.execute(
        text(
            "INSERT INTO new_tickets (ticket_id, order_id, description) "
            "VALUES (:ticket_id, :order_id, :description)"
        ),
        {
            "ticket_id": row["ticket_id"],
            "order_id": row["order_id"],
            "description": row["description"],
        },
    )
    await db.commit()


async def _seed_order(db: AsyncSession, order_id: str, status: str, value: float) -> None:
    """Insert one F1 orders_context row (used by the override policy gate)."""
    await db.execute(
        text(
            "INSERT INTO orders_context (order_id, status, value) "
            "VALUES (:order_id, :status, :value)"
        ),
        {"order_id": order_id, "status": status, "value": value},
    )
    await db.commit()


async def _seed_human_decision(db: AsyncSession, **overrides) -> None:
    """Insert one pre-existing human decision (for already-handled scenarios)."""
    defaults = {
        "ticket_id": "N-003",
        "order_id": "ORD-1002",
        "agent_action": "approve",
        "original_action": "refund",
        "final_action": "refund",
        "rejection_reason": None,
        "final_reply": None,
        "agent_id": "agent-7",
        "created_at": "2026-08-08T08:00:00+00:00",
    }
    defaults.update(overrides)
    await db.execute(
        text(
            "INSERT INTO human_decision_log "
            "(ticket_id, order_id, agent_action, original_action, final_action, "
            " rejection_reason, final_reply, agent_id, created_at) "
            "VALUES (:ticket_id, :order_id, :agent_action, :original_action, :final_action, "
            " :rejection_reason, :final_reply, :agent_id, :created_at)"
        ),
        defaults,
    )
    await db.commit()


async def _read_decision_log(db: AsyncSession, ticket_id: str) -> dict:
    """Read the current decision_log row (asserting lane/action mutations)."""
    result = await db.execute(
        text("SELECT * FROM decision_log WHERE ticket_id = :ticket_id"),
        {"ticket_id": ticket_id},
    )
    row = result.mappings().first()
    return dict(row) if row else {}


# ---------------------------------------------------------------------------
# Feature: Human Override Controls (FEAT-006)
# ---------------------------------------------------------------------------

class TestHumanOverrideControls:
    """Tests for the Human Override Controls feature."""

    # ------------------------------------------------------------------
    # §2.1 Pydantic model contracts
    # ------------------------------------------------------------------

    class TestHumanDecisionModels:
        """Contract tests for the §2.1 Pydantic models / §3.2 field constraints."""

        def test_human_action_enum_values(self):
            """US-01..US-03: the three human decisions carry canonical wire values."""
            assert HumanAction.APPROVE.value == "approve"
            assert HumanAction.OVERRIDE.value == "override"
            assert HumanAction.REJECT.value == "reject"

        def test_approve_request_accepts_valid_agent_id(self):
            """US-01: ApproveRequest requires a non-blank agent_id."""
            request = ApproveRequest(agent_id="agent-7")
            assert request.agent_id == "agent-7"

        def test_approve_request_rejects_blank_agent_id(self):
            """BR 'Agents must be identifiable': blank agent_id fails validation (ERR_HUM_006)."""
            with pytest.raises(ValidationError):
                ApproveRequest(agent_id="")
            with pytest.raises(ValidationError):
                ApproveRequest(agent_id="   ")
            with pytest.raises(ValidationError):
                ApproveRequest()

        def test_override_request_accepts_valid_action_and_reply(self):
            """US-02 S1: OverrideRequest accepts a valid action and optional edited reply."""
            request = OverrideRequest(
                agent_id="agent-7",
                action=ResolutionAction.REFUND,
                reply_body="A full refund has been initiated.",
            )
            assert request.action == ResolutionAction.REFUND
            assert request.reply_body == "A full refund has been initiated."

        def test_override_request_reply_body_optional(self):
            """US-02: reply_body defaults to None when omitted (drafted reply stands)."""
            request = OverrideRequest(agent_id="agent-7", action=ResolutionAction.COUPON)
            assert request.reply_body is None

        def test_override_request_rejects_blank_agent_id(self):
            """BR 'Agents must be identifiable' applies to overrides too."""
            with pytest.raises(ValidationError):
                OverrideRequest(agent_id="", action=ResolutionAction.REFUND)

        def test_override_request_rejects_unknown_action_string(self):
            """ERR_HUM_008: a string that is not a ResolutionAction fails model validation."""
            with pytest.raises(ValidationError):
                OverrideRequest(agent_id="agent-7", action="garbage")

        def test_override_request_accepts_other_enum_then_service_rejects(self):
            """ERR_HUM_008: 'other' parses as the enum member but is a service-level reject."""
            request = OverrideRequest(agent_id="agent-7", action=ResolutionAction.OTHER)
            assert request.action == ResolutionAction.OTHER

        def test_reject_request_accepts_valid_reason(self):
            """US-03 S1: RejectRequest requires an agent_id and a non-blank reason."""
            request = RejectRequest(agent_id="agent-7", reason="Customer contacted by phone.")
            assert request.reason == "Customer contacted by phone."

        def test_reject_request_rejects_blank_reason(self):
            """US-03 S2 / EC-03: blank reason fails model validation (ERR_HUM_005)."""
            with pytest.raises(ValidationError):
                RejectRequest(agent_id="agent-7", reason="")
            with pytest.raises(ValidationError):
                RejectRequest(agent_id="agent-7", reason="   ")
            with pytest.raises(ValidationError):
                RejectRequest(agent_id="agent-7")

        def test_reject_request_rejects_blank_agent_id(self):
            """BR 'Agents must be identifiable' applies to rejections too."""
            with pytest.raises(ValidationError):
                RejectRequest(agent_id="", reason="a reason")

        def test_human_decision_record_accepts_valid_payload(self):
            """US-04: the audit record carries ticket, action, agent, and timestamp."""
            record = HumanDecisionRecord(
                ticket_id="N-003",
                order_id="ORD-1002",
                agent_action=HumanAction.APPROVE,
                original_action="refund",
                final_action="refund",
                rejection_reason=None,
                final_reply=None,
                agent_id="agent-7",
                created_at="2026-08-08T15:30:00+00:00",
            )
            assert record.ticket_id == "N-003"
            assert record.agent_action == HumanAction.APPROVE
            assert record.handled is True  # one final decision per ticket

        def test_human_decision_record_rejects_missing_required_fields(self):
            """§3.2: ticket_id, order_id, agent_action, agent_id, created_at are mandatory."""
            with pytest.raises(ValidationError):
                HumanDecisionRecord(
                    order_id="ORD-1002",
                    agent_action=HumanAction.APPROVE,
                    agent_id="agent-7",
                    created_at="2026-08-08T15:30:00+00:00",
                )

        def test_human_decision_record_reject_shape(self):
            """US-03 S1: a rejection records final_action=None and a reason."""
            record = HumanDecisionRecord(
                ticket_id="N-003",
                order_id="ORD-1002",
                agent_action=HumanAction.REJECT,
                original_action="coupon",
                final_action=None,
                rejection_reason="Customer already resolved manually.",
                final_reply=None,
                agent_id="agent-7",
                created_at="2026-08-08T15:32:00+00:00",
            )
            assert record.final_action is None
            assert record.rejection_reason == "Customer already resolved manually."
            assert record.handled is True

        def test_decision_list_response_defaults_to_empty_items(self):
            """US-04 S2: items defaults to [] — an empty history is a valid 200."""
            response = HumanDecisionListResponse(total=0, skip=0, limit=50)
            assert response.items == []
            assert response.total == 0

        def test_decision_list_response_rejects_invalid_bounds(self):
            """§3.2: total >= 0, skip >= 0, limit >= 1."""
            with pytest.raises(ValidationError):
                HumanDecisionListResponse(total=-1, skip=0, limit=50)
            with pytest.raises(ValidationError):
                HumanDecisionListResponse(total=0, skip=-1, limit=50)
            with pytest.raises(ValidationError):
                HumanDecisionListResponse(total=0, skip=0, limit=0)

    # ------------------------------------------------------------------
    # §2.2 Pure engine — normalize_override_action()
    # ------------------------------------------------------------------

    class TestNormalizeOverrideAction:
        """ERR_HUM_008 / US-02: only refund|redelivery|coupon are selectable final actions."""

        def test_refund_is_canonical(self):
            """'refund' normalizes to the refund action."""
            assert normalize_override_action("refund") == ResolutionAction.REFUND

        def test_redelivery_is_canonical(self):
            """'redelivery' normalizes to the redelivery action."""
            assert normalize_override_action("redelivery") == ResolutionAction.REDELIVERY

        def test_coupon_is_canonical(self):
            """'coupon' normalizes to the coupon action."""
            assert normalize_override_action("coupon") == ResolutionAction.COUPON

        def test_matching_is_case_insensitive(self):
            """Case-insensitive matching: 'REFUND' is accepted."""
            assert normalize_override_action("REFUND") == ResolutionAction.REFUND
            assert normalize_override_action("Redelivery") == ResolutionAction.REDELIVERY
            assert normalize_override_action("COUPON") == ResolutionAction.COUPON

        def test_other_is_rejected(self):
            """ERR_HUM_008: F3's 'other' marker can never be a human final action."""
            with pytest.raises(HumanDecisionInvalidActionError):
                normalize_override_action("other")

        def test_unknown_action_is_rejected(self):
            """ERR_HUM_008: an unrecognized action string is rejected."""
            for raw in ("apology_no_action", "escalation", "refund_the_universe", "full_refund"):
                with pytest.raises(HumanDecisionInvalidActionError):
                    normalize_override_action(raw)

        def test_blank_action_is_rejected(self):
            """ERR_HUM_008: empty/whitespace action strings are rejected."""
            with pytest.raises(HumanDecisionInvalidActionError):
                normalize_override_action("")
            with pytest.raises(HumanDecisionInvalidActionError):
                normalize_override_action("   ")

    # ------------------------------------------------------------------
    # §2.2 Pure engine — validate_override_policy()
    # ------------------------------------------------------------------

    class TestValidateOverridePolicy:
        """US-02 S2 / EC-02 / ERR_HUM_004: overrides honor the F3 order-context policy."""

        def test_redelivery_blocked_on_cancelled_order(self):
            """EC-02: redelivery on a cancelled order is blocked."""
            with pytest.raises(HumanDecisionPolicyBlockedError):
                validate_override_policy(ResolutionAction.REDELIVERY, "cancelled")

        def test_redelivery_blocked_case_insensitive(self):
            """EC-02: the status comparison is case-insensitive."""
            with pytest.raises(HumanDecisionPolicyBlockedError):
                validate_override_policy(ResolutionAction.REDELIVERY, "CANCELLED")

        def test_redelivery_allowed_on_delivered_order(self):
            """BR 'Override must respect order context': delivered orders may be re-shipped."""
            validate_override_policy(ResolutionAction.REDELIVERY, "delivered")

        def test_refund_allowed_on_cancelled_order(self):
            """BR-04: refunds are never blocked by order status."""
            validate_override_policy(ResolutionAction.REFUND, "cancelled")

        def test_coupon_allowed_on_cancelled_order(self):
            """BR-04: coupons are never blocked by order status."""
            validate_override_policy(ResolutionAction.COUPON, "cancelled")

        def test_redelivery_allowed_on_blank_status(self):
            """BR-04: a blank/unknown order status does not block redelivery."""
            validate_override_policy(ResolutionAction.REDELIVERY, "")
            validate_override_policy(ResolutionAction.REDELIVERY, "   ")

    # ------------------------------------------------------------------
    # §2.2 Pure engine — validate_rejection_reason()
    # ------------------------------------------------------------------

    class TestValidateRejectionReason:
        """US-03 S2 / EC-03 / ERR_HUM_005: a rejection requires a non-blank reason."""

        def test_valid_reason_passes(self):
            """US-03 S1: a real reason is accepted."""
            validate_rejection_reason("Customer already contacted via phone.")

        def test_empty_reason_raises(self):
            """EC-03: an empty reason is rejected."""
            with pytest.raises(HumanDecisionInvalidReasonError):
                validate_rejection_reason("")

        def test_whitespace_reason_raises(self):
            """EC-03: whitespace-only text is treated as no reason."""
            with pytest.raises(HumanDecisionInvalidReasonError):
                validate_rejection_reason("   ")

        def test_none_reason_raises(self):
            """EC-03: a missing reason is rejected."""
            with pytest.raises(HumanDecisionInvalidReasonError):
                validate_rejection_reason(None)

    # ------------------------------------------------------------------
    # §2.2 Pure engine — final_refund_for()
    # ------------------------------------------------------------------

    class TestFinalRefundFor:
        """US-02 S1: a human-chosen refund derives a capped amount; other actions yield None."""

        def test_default_ratio_is_full_refund(self):
            """A manual refund defaults to 100% of the order value."""
            assert final_refund_for(ResolutionAction.REFUND, 1000.0) == 1000.0

        def test_partial_ratio_is_applied(self):
            """A custom refund ratio scales the amount."""
            assert final_refund_for(ResolutionAction.REFUND, 1000.0, 0.5) == 500.0

        def test_amount_is_rounded_to_two_decimals(self):
            """The derived amount is rounded to paise (2 decimals)."""
            assert final_refund_for(ResolutionAction.REFUND, 333.333, 0.5) == pytest.approx(166.67)

        def test_refund_is_capped_at_order_value(self):
            """BR-05: a refund can never exceed the order value."""
            assert final_refund_for(ResolutionAction.REFUND, 1000.0, 2.0) == 1000.0

        def test_unknown_order_value_yields_zero_refund(self):
            """§8 note 5: a missing order behaves with order_value 0.0."""
            assert final_refund_for(ResolutionAction.REFUND, 0.0) == 0.0

        def test_redelivery_yields_no_refund(self):
            """Only refund actions produce a refund amount."""
            assert final_refund_for(ResolutionAction.REDELIVERY, 1000.0) is None

        def test_coupon_yields_no_refund(self):
            """Only refund actions produce a refund amount."""
            assert final_refund_for(ResolutionAction.COUPON, 1000.0) is None

    # ------------------------------------------------------------------
    # §2.3 Service — approve_ticket() (US-01)
    # ------------------------------------------------------------------

    class TestApproveTicketService:
        """US-01 S1: approve the suggested action, record the decision, flip the lane."""

        @pytest.mark.asyncio
        async def test_approve_records_decision_and_flips_lane(self, db_session):
            """US-01 S1: Given an escalated ticket with a suggestion, When the agent
            approves, Then the decision is recorded with identity/action/timestamp and
            the ticket moves to Auto-Resolved (decision_log.auto_resolved=True)."""
            await _seed_ticket(db_session)

            record = await approve_ticket(db_session, "N-003", "agent-7")

            assert isinstance(record, HumanDecisionRecord)
            assert record.ticket_id == "N-003"
            assert record.order_id == "ORD-1002"
            assert record.agent_action == HumanAction.APPROVE
            assert record.original_action == "refund"   # suggested action preserved
            assert record.final_action == "refund"      # suggested action becomes final
            assert record.rejection_reason is None
            assert record.final_reply is None
            assert record.agent_id == "agent-7"
            assert "T" in record.created_at              # ISO-8601 UTC timestamp

            lane = await _read_decision_log(db_session, "N-003")
            assert lane["auto_resolved"] is True         # lane move (US-01 S1)

        @pytest.mark.asyncio
        async def test_approve_unknown_ticket_raises_not_found(self, db_session):
            """EC-04 / ERR_HUM_001: no decision record for the ticket -> 404 semantics."""
            with pytest.raises(HumanDecisionTicketNotFoundError):
                await approve_ticket(db_session, "N-999", "agent-7")

        @pytest.mark.asyncio
        async def test_approve_already_handled_raises(self, db_session):
            """US-01 S2 / EC-01 / ERR_HUM_002: a second decision is refused."""
            await _seed_ticket(db_session)
            await _seed_human_decision(db_session)

            with pytest.raises(HumanDecisionAlreadyHandledError):
                await approve_ticket(db_session, "N-003", "agent-7")

        @pytest.mark.asyncio
        async def test_approve_auto_resolved_ticket_raises_not_actionable(self, db_session):
            """BR 'Only escalated tickets can be acted on' / ERR_HUM_003."""
            await _seed_ticket(db_session, **_base_auto_resolved_ticket())

            with pytest.raises(HumanDecisionNotActionableError):
                await approve_ticket(db_session, "N-002", "agent-7")

        @pytest.mark.asyncio
        async def test_approve_blank_agent_raises(self, db_session):
            """BR 'Agents must be identifiable' / ERR_HUM_006."""
            await _seed_ticket(db_session)
            with pytest.raises(HumanDecisionInvalidAgentError):
                await approve_ticket(db_session, "N-003", "")
            with pytest.raises(HumanDecisionInvalidAgentError):
                await approve_ticket(db_session, "N-003", "   ")

        @pytest.mark.asyncio
        async def test_approve_without_suggestion_raises(self, db_session):
            """ERR_HUM_009: an escalated ticket with no suggested action cannot be approved."""
            await _seed_ticket(db_session, action=None)

            with pytest.raises(HumanDecisionNoSuggestionError):
                await approve_ticket(db_session, "N-003", "agent-7")

    # ------------------------------------------------------------------
    # §2.3 Service — override_ticket() (US-02)
    # ------------------------------------------------------------------

    class TestOverrideTicketService:
        """US-02: replace the suggested action (optionally editing the reply)."""

        @pytest.mark.asyncio
        async def test_override_records_new_action_and_reply(self, db_session):
            """US-02 S1: Given a coupon suggestion, When the agent overrides to refund with
            an edited reply, Then the new action and reply become final and the original
            suggestion is preserved for the audit record."""
            await _seed_ticket(db_session, action="coupon")
            await _seed_order(db_session, "ORD-1002", "delivered", 1000.0)

            record = await override_ticket(
                db_session,
                "N-003",
                "agent-7",
                ResolutionAction.REFUND,
                "We are sorry for the trouble — a full refund of ₹1000 has been initiated.",
            )

            assert isinstance(record, HumanDecisionRecord)
            assert record.ticket_id == "N-003"
            assert record.agent_action == HumanAction.OVERRIDE
            assert record.original_action == "coupon"  # original suggestion recorded (US-02 S1)
            assert record.final_action == "refund"     # new action becomes final
            assert record.rejection_reason is None
            assert record.final_reply == (
                "We are sorry for the trouble — a full refund of ₹1000 has been initiated."
            )
            assert record.agent_id == "agent-7"
            assert "T" in record.created_at

            lane = await _read_decision_log(db_session, "N-003")
            assert lane["auto_resolved"] is True       # lane move (US-02 S1)
            assert lane["action"] == "refund"          # decision_log action updated
            assert lane["refund_amount"] == 1000.0     # refund amount derived

        @pytest.mark.asyncio
        async def test_override_without_reply_keeps_final_reply_none(self, db_session):
            """US-02: when no reply body is provided, the drafted reply stands (final_reply null)."""
            await _seed_ticket(db_session, action="coupon")
            await _seed_order(db_session, "ORD-1002", "delivered", 500.0)

            record = await override_ticket(db_session, "N-003", "agent-7", ResolutionAction.COUPON)
            assert record.final_action == "coupon"
            assert record.final_reply is None

        @pytest.mark.asyncio
        async def test_override_policy_blocked_raises(self, db_session):
            """US-02 S2 / EC-02 / ERR_HUM_004: redelivery on a cancelled order is blocked."""
            await _seed_ticket(db_session, action="coupon")
            await _seed_order(db_session, "ORD-1002", "cancelled", 500.0)

            with pytest.raises(HumanDecisionPolicyBlockedError):
                await override_ticket(
                    db_session, "N-003", "agent-7", ResolutionAction.REDELIVERY
                )

        @pytest.mark.asyncio
        async def test_override_missing_order_context_is_unrestricted(self, db_session):
            """§8 note 5: a missing order behaves as an unrestricted policy check."""
            await _seed_ticket(db_session, action="coupon")
            # No orders_context row for ORD-1002.

            record = await override_ticket(
                db_session, "N-003", "agent-7", ResolutionAction.REDELIVERY
            )
            assert record.final_action == "redelivery"

        @pytest.mark.asyncio
        async def test_override_unknown_ticket_raises(self, db_session):
            """EC-04 / ERR_HUM_001."""
            with pytest.raises(HumanDecisionTicketNotFoundError):
                await override_ticket(db_session, "N-999", "agent-7", ResolutionAction.REFUND)

        @pytest.mark.asyncio
        async def test_override_already_handled_raises(self, db_session):
            """EC-01 / ERR_HUM_002."""
            await _seed_ticket(db_session)
            await _seed_human_decision(db_session)

            with pytest.raises(HumanDecisionAlreadyHandledError):
                await override_ticket(db_session, "N-003", "agent-7", ResolutionAction.REFUND)

        @pytest.mark.asyncio
        async def test_override_auto_resolved_ticket_raises(self, db_session):
            """BR 'Only escalated tickets can be acted on' / ERR_HUM_003."""
            await _seed_ticket(db_session, **_base_auto_resolved_ticket())

            with pytest.raises(HumanDecisionNotActionableError):
                await override_ticket(db_session, "N-002", "agent-7", ResolutionAction.REFUND)

        @pytest.mark.asyncio
        async def test_override_blank_agent_raises(self, db_session):
            """BR 'Agents must be identifiable' / ERR_HUM_006."""
            await _seed_ticket(db_session)
            with pytest.raises(HumanDecisionInvalidAgentError):
                await override_ticket(db_session, "N-003", "  ", ResolutionAction.REFUND)

    # ------------------------------------------------------------------
    # §2.3 Service — reject_ticket() (US-03)
    # ------------------------------------------------------------------

    class TestRejectTicketService:
        """US-03: reject the suggestion with a documented reason; never apply it."""

        @pytest.mark.asyncio
        async def test_reject_records_reason_and_keeps_lane(self, db_session):
            """US-03 S1: Given a suggestion the agent disagrees with, When they reject with
            a reason, Then the rejection is recorded, final_action is null (never applied),
            and the ticket stays in the review lane (auto_resolved untouched)."""
            await _seed_ticket(db_session, action="coupon")

            record = await reject_ticket(db_session, "N-003", "agent-7", "Customer already resolved manually.")

            assert isinstance(record, HumanDecisionRecord)
            assert record.ticket_id == "N-003"
            assert record.agent_action == HumanAction.REJECT
            assert record.original_action == "coupon"
            assert record.final_action is None             # suggestion never applied
            assert record.rejection_reason == "Customer already resolved manually."
            assert record.final_reply is None
            assert record.agent_id == "agent-7"
            assert "T" in record.created_at

            lane = await _read_decision_log(db_session, "N-003")
            assert lane["auto_resolved"] is False          # stays in Needs Human Review

        @pytest.mark.asyncio
        async def test_reject_blank_reason_raises(self, db_session):
            """US-03 S2 / EC-03 / ERR_HUM_005: blank reasons are refused."""
            await _seed_ticket(db_session)
            for bad in ("", "   ", None):
                with pytest.raises(HumanDecisionInvalidReasonError):
                    await reject_ticket(db_session, "N-003", "agent-7", bad)

        @pytest.mark.asyncio
        async def test_reject_unknown_ticket_raises(self, db_session):
            """EC-04 / ERR_HUM_001."""
            with pytest.raises(HumanDecisionTicketNotFoundError):
                await reject_ticket(db_session, "N-999", "agent-7", "a reason")

        @pytest.mark.asyncio
        async def test_reject_already_handled_raises(self, db_session):
            """EC-01 / ERR_HUM_002."""
            await _seed_ticket(db_session)
            await _seed_human_decision(db_session)

            with pytest.raises(HumanDecisionAlreadyHandledError):
                await reject_ticket(db_session, "N-003", "agent-7", "a reason")

        @pytest.mark.asyncio
        async def test_reject_auto_resolved_ticket_raises(self, db_session):
            """BR 'Only escalated tickets can be acted on' / ERR_HUM_003."""
            await _seed_ticket(db_session, **_base_auto_resolved_ticket())

            with pytest.raises(HumanDecisionNotActionableError):
                await reject_ticket(db_session, "N-002", "agent-7", "a reason")

        @pytest.mark.asyncio
        async def test_reject_blank_agent_raises(self, db_session):
            """BR 'Agents must be identifiable' / ERR_HUM_006."""
            await _seed_ticket(db_session)
            with pytest.raises(HumanDecisionInvalidAgentError):
                await reject_ticket(db_session, "N-003", "", "a reason")

    # ------------------------------------------------------------------
    # §2.3 Service — list_human_decisions() (US-04)
    # ------------------------------------------------------------------

    class TestListHumanDecisionsService:
        """US-04: audit history, newest first, page by page (EC-06)."""

        @pytest.mark.asyncio
        async def test_list_is_empty_when_no_decisions(self, db_session):
            """US-04 S2: no decisions yet -> empty list and total 0 (not an error)."""
            items, total = await list_human_decisions(db_session)
            assert items == []
            assert total == 0

        @pytest.mark.asyncio
        async def test_list_orders_newest_first(self, db_session):
            """US-04 S1: entries are ordered newest first (created_at DESC)."""
            await _seed_human_decision(
                db_session, ticket_id="N-001", created_at="2026-08-08T08:00:00+00:00"
            )
            await _seed_human_decision(
                db_session, ticket_id="N-002", created_at="2026-08-08T09:00:00+00:00"
            )
            await _seed_human_decision(
                db_session, ticket_id="N-003", created_at="2026-08-08T10:00:00+00:00"
            )

            items, total = await list_human_decisions(db_session)
            assert total == 3
            assert [item.ticket_id for item in items] == ["N-003", "N-002", "N-001"]

        @pytest.mark.asyncio
        async def test_list_tie_breaks_by_ticket_id_desc(self, db_session):
            """EC-06: identical created_at values tie-break with ticket_id DESC."""
            await _seed_human_decision(db_session, ticket_id="N-001", created_at="2026-08-08T10:00:00+00:00")
            await _seed_human_decision(db_session, ticket_id="N-002", created_at="2026-08-08T10:00:00+00:00")

            items, total = await list_human_decisions(db_session)
            assert [item.ticket_id for item in items] == ["N-002", "N-001"]

        @pytest.mark.asyncio
        async def test_list_paginates_with_skip_and_limit(self, db_session):
            """EC-06: pagination returns manageable chunks with the total count."""
            for i in range(1, 4):
                await _seed_human_decision(
                    db_session,
                    ticket_id=f"N-00{i}",
                    created_at=f"2026-08-08T0{i}:00:00+00:00",
                )

            page1, total = await list_human_decisions(db_session, skip=0, limit=2)
            assert total == 3
            assert len(page1) == 2

            page2, total = await list_human_decisions(db_session, skip=2, limit=2)
            assert total == 3
            assert len(page2) == 1
            assert page1[0].ticket_id != page2[0].ticket_id

    # ------------------------------------------------------------------
    # §2.3 Service — get_human_decision()
    # ------------------------------------------------------------------

    class TestGetHumanDecisionService:
        """F6 handled-status check used by the frontend detail panel."""

        @pytest.mark.asyncio
        async def test_get_returns_record_after_approve(self, db_session):
            """After a decision, the record is retrievable by ticket id."""
            await _seed_ticket(db_session)
            await approve_ticket(db_session, "N-003", "agent-7")

            record = await get_human_decision(db_session, "N-003")
            assert record is not None
            assert record.ticket_id == "N-003"
            assert record.agent_action == HumanAction.APPROVE

        @pytest.mark.asyncio
        async def test_get_returns_none_when_no_decision(self, db_session):
            """A ticket with no human decision yields None (caller maps to 404)."""
            assert await get_human_decision(db_session, "N-777") is None

    # ------------------------------------------------------------------
    # §2.3 Service — one-final-decision invariant (EC-01)
    # ------------------------------------------------------------------

    class TestOneDecisionInvariant:
        """EC-01: the human_decision_log PK guarantees exactly one decision per ticket."""

        @pytest.mark.asyncio
        async def test_duplicate_ticket_id_insert_raises_integrity_error(self, db_session):
            """EC-01: the PK constraint rejects a second row for the same ticket."""
            await _seed_human_decision(db_session, ticket_id="N-003")

            with pytest.raises(IntegrityError):
                await db_session.execute(
                    text(
                        "INSERT INTO human_decision_log "
                        "(ticket_id, order_id, agent_action, agent_id, created_at) "
                        "VALUES (:ticket_id, :order_id, :agent_action, :agent_id, :created_at)"
                    ),
                    {
                        "ticket_id": "N-003",
                        "order_id": "ORD-1002",
                        "agent_action": "override",
                        "agent_id": "agent-9",
                        "created_at": "2026-08-08T11:00:00+00:00",
                    },
                )
                await db_session.commit()

        @pytest.mark.asyncio
        async def test_ec05_read_operations_create_no_partial_record(self, client, db_session):
            """EC-05: merely opening the dashboard / detail / history creates no decision."""
            await _seed_ticket(db_session)

            await client.get("/api/v1/dashboard")
            resp404 = await client.get("/api/v1/human-decisions/N-003")
            assert resp404.status_code == 404
            await client.get("/api/v1/human-decisions")

            items, total = await list_human_decisions(db_session)
            assert total == 0
            assert items == []

    # ------------------------------------------------------------------
    # §2.4 API — POST .../approve (US-01)
    # ------------------------------------------------------------------

    class TestApproveEndpoint:
        """`POST /api/v1/human-decisions/{ticket_id}/approve`."""

        @pytest.mark.asyncio
        async def test_approve_succeeds_and_records_decision(self, client, db_session):
            """US-01 S1: approval returns the recorded decision with all audit fields."""
            await _seed_ticket(db_session)

            resp = await client.post(
                "/api/v1/human-decisions/N-003/approve", json={"agent_id": "agent-7"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ticket_id"] == "N-003"
            assert data["order_id"] == "ORD-1002"
            assert data["agent_action"] == "approve"
            assert data["original_action"] == "refund"
            assert data["final_action"] == "refund"
            assert data["rejection_reason"] is None
            assert data["final_reply"] is None
            assert data["agent_id"] == "agent-7"
            assert "T" in data["created_at"]                     # ISO-8601 UTC timestamp
            assert set(data.keys()) == {
                "ticket_id", "order_id", "agent_action", "original_action",
                "final_action", "rejection_reason", "final_reply",
                "agent_id", "created_at",
            }

        @pytest.mark.asyncio
        async def test_approve_moves_ticket_to_auto_resolved_lane(self, client, db_session):
            """US-01 S1: after approval the ticket surfaces in the Auto-Resolved lane."""
            await _seed_ticket(db_session)

            assert (await client.post(
                "/api/v1/human-decisions/N-003/approve", json={"agent_id": "agent-7"}
            )).status_code == 200

            board = (await client.get("/api/v1/dashboard")).json()
            auto_ids = [c["ticket_id"] for c in board["auto_resolved"]["tickets"]]
            review_ids = [c["ticket_id"] for c in board["needs_review"]["tickets"]]
            assert "N-003" in auto_ids
            assert "N-003" not in review_ids

        @pytest.mark.asyncio
        async def test_approve_unknown_ticket_returns_404(self, client, db_session):
            """EC-04 / ERR_HUM_001."""
            resp = await client.post(
                "/api/v1/human-decisions/N-999/approve", json={"agent_id": "agent-7"}
            )
            assert resp.status_code == 404
            assert "ticket not found" in resp.json()["detail"]

        @pytest.mark.asyncio
        async def test_approve_already_handled_returns_409_no_duplicate(self, client, db_session):
            """US-01 S2 / EC-01 / ERR_HUM_002: the second action is refused and no
            duplicate record is created."""
            await _seed_ticket(db_session)
            assert (await client.post(
                "/api/v1/human-decisions/N-003/approve", json={"agent_id": "agent-7"}
            )).status_code == 200

            second = await client.post(
                "/api/v1/human-decisions/N-003/approve", json={"agent_id": "agent-9"}
            )
            assert second.status_code == 409
            assert "already been handled" in second.json()["detail"]

            history = (await client.get("/api/v1/human-decisions")).json()
            assert history["total"] == 1                      # no duplicate record
            assert history["items"][0]["agent_id"] == "agent-7"  # first action wins

        @pytest.mark.asyncio
        async def test_approve_auto_resolved_ticket_returns_409(self, client, db_session):
            """BR 'Only escalated tickets can be acted on' / ERR_HUM_003."""
            await _seed_ticket(db_session, **_base_auto_resolved_ticket())

            resp = await client.post(
                "/api/v1/human-decisions/N-002/approve", json={"agent_id": "agent-7"}
            )
            assert resp.status_code == 409
            assert "awaiting human review" in resp.json()["detail"]

        @pytest.mark.asyncio
        async def test_approve_blank_agent_returns_422(self, client, db_session):
            """BR 'Agents must be identifiable' / ERR_HUM_006."""
            await _seed_ticket(db_session)

            resp = await client.post("/api/v1/human-decisions/N-003/approve", json={"agent_id": ""})
            assert resp.status_code == 422
            missing = await client.post("/api/v1/human-decisions/N-003/approve", json={})
            assert missing.status_code == 422

        @pytest.mark.asyncio
        async def test_approve_without_suggestion_returns_422(self, client, db_session):
            """ERR_HUM_009: no suggested action to approve."""
            await _seed_ticket(db_session, action=None)

            resp = await client.post(
                "/api/v1/human-decisions/N-003/approve", json={"agent_id": "agent-7"}
            )
            assert resp.status_code == 422

        @pytest.mark.asyncio
        async def test_approve_returns_500_when_data_unavailable(self, client, db_engine):
            """ERR_HUM_007: a persistence/data failure yields 500 with a clear message."""
            await client.post("/api/v1/human-decisions/N-003/approve", json={"agent_id": "agent-7"})
            await db_engine.dispose()

            resp = await client.post(
                "/api/v1/human-decisions/N-003/approve", json={"agent_id": "agent-7"}
            )
            assert resp.status_code == 500

    # ------------------------------------------------------------------
    # §2.4 API — POST .../override (US-02)
    # ------------------------------------------------------------------

    class TestOverrideEndpoint:
        """`POST /api/v1/human-decisions/{ticket_id}/override`."""

        @pytest.mark.asyncio
        async def test_override_succeeds_with_new_action_and_edited_reply(self, client, db_session):
            """US-02 S1: the override returns the new action + edited reply as final."""
            await _seed_ticket(db_session, action="coupon")
            await _seed_order(db_session, "ORD-1002", "delivered", 1000.0)

            resp = await client.post(
                "/api/v1/human-decisions/N-003/override",
                json={
                    "agent_id": "agent-7",
                    "action": "refund",
                    "reply_body": "We are sorry — a full refund of ₹1000 has been initiated.",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["agent_action"] == "override"
            assert data["original_action"] == "coupon"
            assert data["final_action"] == "refund"
            assert data["final_reply"] == "We are sorry — a full refund of ₹1000 has been initiated."
            assert data["agent_id"] == "agent-7"

        @pytest.mark.asyncio
        async def test_override_moves_ticket_to_auto_resolved_lane(self, client, db_session):
            """US-02 S1: after a valid override the ticket surfaces in Auto-Resolved."""
            await _seed_ticket(db_session, action="coupon")
            await _seed_order(db_session, "ORD-1002", "delivered", 500.0)

            assert (await client.post(
                "/api/v1/human-decisions/N-003/override",
                json={"agent_id": "agent-7", "action": "refund"},
            )).status_code == 200

            board = (await client.get("/api/v1/dashboard")).json()
            auto_ids = [c["ticket_id"] for c in board["auto_resolved"]["tickets"]]
            assert "N-003" in auto_ids

        @pytest.mark.asyncio
        async def test_override_policy_blocked_returns_422_ticket_unchanged(self, client, db_session):
            """US-02 S2 / EC-02 / ERR_HUM_004: redelivery on a cancelled order is refused,
            the ticket stays in the review lane, and nothing is recorded."""
            await _seed_ticket(db_session, action="coupon")
            await _seed_order(db_session, "ORD-1002", "cancelled", 500.0)

            resp = await client.post(
                "/api/v1/human-decisions/N-003/override",
                json={"agent_id": "agent-7", "action": "redelivery"},
            )
            assert resp.status_code == 422
            assert "cancelled" in resp.json()["detail"].lower()

            history = (await client.get("/api/v1/human-decisions")).json()
            assert history["total"] == 0                        # no decision recorded
            board = (await client.get("/api/v1/dashboard")).json()
            review_ids = [c["ticket_id"] for c in board["needs_review"]["tickets"]]
            assert "N-003" in review_ids                        # ticket unchanged

        @pytest.mark.asyncio
        async def test_override_other_action_returns_422(self, client, db_session):
            """ERR_HUM_008: 'other' parses as the enum but is rejected by the service."""
            await _seed_ticket(db_session)
            await _seed_order(db_session, "ORD-1002", "delivered", 500.0)

            resp = await client.post(
                "/api/v1/human-decisions/N-003/override",
                json={"agent_id": "agent-7", "action": "other"},
            )
            assert resp.status_code == 422

        @pytest.mark.asyncio
        async def test_override_unknown_action_returns_422(self, client, db_session):
            """ERR_HUM_008: an unrecognized action string fails request validation."""
            await _seed_ticket(db_session)

            resp = await client.post(
                "/api/v1/human-decisions/N-003/override",
                json={"agent_id": "agent-7", "action": "garbage"},
            )
            assert resp.status_code == 422

        @pytest.mark.asyncio
        async def test_override_unknown_ticket_returns_404(self, client, db_session):
            """EC-04 / ERR_HUM_001."""
            resp = await client.post(
                "/api/v1/human-decisions/N-999/override",
                json={"agent_id": "agent-7", "action": "refund"},
            )
            assert resp.status_code == 404

        @pytest.mark.asyncio
        async def test_override_already_handled_returns_409(self, client, db_session):
            """EC-01 / ERR_HUM_002."""
            await _seed_ticket(db_session)
            await _seed_human_decision(db_session)

            resp = await client.post(
                "/api/v1/human-decisions/N-003/override",
                json={"agent_id": "agent-7", "action": "refund"},
            )
            assert resp.status_code == 409

        @pytest.mark.asyncio
        async def test_override_auto_resolved_ticket_returns_409(self, client, db_session):
            """BR 'Only escalated tickets can be acted on' / ERR_HUM_003."""
            await _seed_ticket(db_session, **_base_auto_resolved_ticket())

            resp = await client.post(
                "/api/v1/human-decisions/N-002/override",
                json={"agent_id": "agent-7", "action": "refund"},
            )
            assert resp.status_code == 409

        @pytest.mark.asyncio
        async def test_override_blank_agent_returns_422(self, client, db_session):
            """BR 'Agents must be identifiable' / ERR_HUM_006."""
            await _seed_ticket(db_session)

            resp = await client.post(
                "/api/v1/human-decisions/N-003/override",
                json={"agent_id": "", "action": "refund"},
            )
            assert resp.status_code == 422

    # ------------------------------------------------------------------
    # §2.4 API — POST .../reject (US-03)
    # ------------------------------------------------------------------

    class TestRejectEndpoint:
        """`POST /api/v1/human-decisions/{ticket_id}/reject`."""

        @pytest.mark.asyncio
        async def test_reject_succeeds_with_reason(self, client, db_session):
            """US-03 S1: the rejection is recorded with reason and final_action null."""
            await _seed_ticket(db_session, action="coupon")

            resp = await client.post(
                "/api/v1/human-decisions/N-003/reject",
                json={"agent_id": "agent-7", "reason": "Customer already resolved manually."},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["agent_action"] == "reject"
            assert data["original_action"] == "coupon"
            assert data["final_action"] is None               # suggestion never applied
            assert data["rejection_reason"] == "Customer already resolved manually."
            assert data["final_reply"] is None
            assert data["agent_id"] == "agent-7"

        @pytest.mark.asyncio
        async def test_reject_stays_in_review_lane_but_becomes_final(self, client, db_session):
            """US-03 S1: a rejected ticket stays in Needs Human Review but no further
            human action is accepted (one final decision per ticket)."""
            await _seed_ticket(db_session, action="coupon")
            assert (await client.post(
                "/api/v1/human-decisions/N-003/reject",
                json={"agent_id": "agent-7", "reason": "handled externally"},
            )).status_code == 200

            board = (await client.get("/api/v1/dashboard")).json()
            review_ids = [c["ticket_id"] for c in board["needs_review"]["tickets"]]
            assert "N-003" in review_ids                     # still visible in review lane

            second = await client.post(
                "/api/v1/human-decisions/N-003/approve", json={"agent_id": "agent-9"}
            )
            assert second.status_code == 409                  # final: no further action

        @pytest.mark.asyncio
        async def test_reject_blank_reason_returns_422(self, client, db_session):
            """US-03 S2 / EC-03 / ERR_HUM_005: blank reasons are refused and not saved."""
            await _seed_ticket(db_session)

            for reason in ("", "   "):
                resp = await client.post(
                    "/api/v1/human-decisions/N-003/reject",
                    json={"agent_id": "agent-7", "reason": reason},
                )
                assert resp.status_code == 422

            history = (await client.get("/api/v1/human-decisions")).json()
            assert history["total"] == 0                      # nothing saved (EC-03)

        @pytest.mark.asyncio
        async def test_reject_missing_reason_returns_422(self, client, db_session):
            """US-03 S2: a request without a reason fails body validation."""
            await _seed_ticket(db_session)

            resp = await client.post(
                "/api/v1/human-decisions/N-003/reject", json={"agent_id": "agent-7"}
            )
            assert resp.status_code == 422

        @pytest.mark.asyncio
        async def test_reject_unknown_ticket_returns_404(self, client, db_session):
            """EC-04 / ERR_HUM_001."""
            resp = await client.post(
                "/api/v1/human-decisions/N-999/reject",
                json={"agent_id": "agent-7", "reason": "a reason"},
            )
            assert resp.status_code == 404

        @pytest.mark.asyncio
        async def test_reject_already_handled_returns_409(self, client, db_session):
            """EC-01 / ERR_HUM_002."""
            await _seed_ticket(db_session)
            await _seed_human_decision(db_session)

            resp = await client.post(
                "/api/v1/human-decisions/N-003/reject",
                json={"agent_id": "agent-7", "reason": "a reason"},
            )
            assert resp.status_code == 409

        @pytest.mark.asyncio
        async def test_reject_auto_resolved_ticket_returns_409(self, client, db_session):
            """BR 'Only escalated tickets can be acted on' / ERR_HUM_003."""
            await _seed_ticket(db_session, **_base_auto_resolved_ticket())

            resp = await client.post(
                "/api/v1/human-decisions/N-002/reject",
                json={"agent_id": "agent-7", "reason": "a reason"},
            )
            assert resp.status_code == 409

        @pytest.mark.asyncio
        async def test_reject_blank_agent_returns_422(self, client, db_session):
            """BR 'Agents must be identifiable' / ERR_HUM_006."""
            await _seed_ticket(db_session)

            resp = await client.post(
                "/api/v1/human-decisions/N-003/reject",
                json={"agent_id": "", "reason": "a reason"},
            )
            assert resp.status_code == 422

    # ------------------------------------------------------------------
    # §2.4 API — GET /human-decisions (US-04)
    # ------------------------------------------------------------------

    class TestListHistoryEndpoint:
        """`GET /api/v1/human-decisions` — paginated audit history, newest first."""

        @pytest.mark.asyncio
        async def test_empty_history_returns_200_with_empty_items(self, client, db_session):
            """US-04 S2 / ERR_HUM_010: no decisions yet is a 200 empty state, not an error."""
            resp = await client.get("/api/v1/human-decisions")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0
            assert data["skip"] == 0
            assert data["limit"] == 50
            assert data["items"] == []

        @pytest.mark.asyncio
        async def test_history_lists_newest_first_with_audit_fields(self, client, db_session):
            """US-04 S1: each entry shows ticket, suggestion, final action/reason, agent,
            and timestamp, ordered newest first."""
            await _seed_ticket(db_session, ticket_id="N-001", action="coupon")
            await _seed_ticket(db_session, ticket_id="N-002", action="redelivery")
            assert (await client.post(
                "/api/v1/human-decisions/N-001/reject",
                json={"agent_id": "agent-7", "reason": "resolved by phone"},
            )).status_code == 200
            assert (await client.post(
                "/api/v1/human-decisions/N-002/approve", json={"agent_id": "agent-3"}
            )).status_code == 200

            resp = await client.get("/api/v1/human-decisions")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 2

            first, second = data["items"]
            assert first["ticket_id"] == "N-002"             # newest first
            assert first["agent_action"] == "approve"
            assert first["original_action"] == "redelivery"
            assert first["final_action"] == "redelivery"
            assert first["agent_id"] == "agent-3"
            assert "T" in first["created_at"]

            assert second["ticket_id"] == "N-001"
            assert second["agent_action"] == "reject"
            assert second["final_action"] is None
            assert second["rejection_reason"] == "resolved by phone"
            assert second["agent_id"] == "agent-7"

        @pytest.mark.asyncio
        async def test_history_paginates(self, client, db_session):
            """EC-06: skip/limit page through the growing history."""
            for i in range(1, 4):
                await _seed_ticket(db_session, ticket_id=f"N-01{i}", action="refund")
                await client.post(
                    f"/api/v1/human-decisions/N-01{i}/approve", json={"agent_id": "agent-7"}
                )

            page1 = (await client.get("/api/v1/human-decisions", params={"skip": 0, "limit": 2})).json()
            assert page1["total"] == 3
            assert len(page1["items"]) == 2

            page2 = (await client.get("/api/v1/human-decisions", params={"skip": 2, "limit": 2})).json()
            assert page2["total"] == 3
            assert len(page2["items"]) == 1
            assert page1["items"][0]["ticket_id"] != page2["items"][0]["ticket_id"]

        @pytest.mark.asyncio
        async def test_history_invalid_query_params_return_422(self, client, db_session):
            """§4.4: skip < 0, limit < 1, or limit > 500 fail validation."""
            for params in ({"skip": -1}, {"limit": 0}, {"limit": 501}):
                resp = await client.get("/api/v1/human-decisions", params=params)
                assert resp.status_code == 422

        @pytest.mark.asyncio
        async def test_list_route_is_not_captured_by_ticket_id_param(self, client, db_session):
            """§8 note 2: the literal /human-decisions route wins over {ticket_id}."""
            resp = await client.get("/api/v1/human-decisions")
            assert resp.status_code == 200
            assert "items" in resp.json()

    # ------------------------------------------------------------------
    # §2.4 API — GET /human-decisions/{ticket_id}
    # ------------------------------------------------------------------

    class TestGetDecisionEndpoint:
        """`GET /api/v1/human-decisions/{ticket_id}` — handled-status check."""

        @pytest.mark.asyncio
        async def test_get_returns_record_after_action(self, client, db_session):
            """The record for an acted-on ticket is retrievable by id."""
            await _seed_ticket(db_session)
            await client.post(
                "/api/v1/human-decisions/N-003/approve", json={"agent_id": "agent-7"}
            )

            resp = await client.get("/api/v1/human-decisions/N-003")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ticket_id"] == "N-003"
            assert data["agent_action"] == "approve"

        @pytest.mark.asyncio
        async def test_get_unknown_ticket_returns_404(self, client, db_session):
            """§4.5 / ERR_HUM_002: no human decision -> 404 with a clear message."""
            resp = await client.get("/api/v1/human-decisions/N-777")
            assert resp.status_code == 404
            assert "no human decision" in resp.json()["detail"]
