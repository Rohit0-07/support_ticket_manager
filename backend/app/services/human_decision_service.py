"""Human Override Controls orchestration + persistence service (FEAT-006).

Approve / override / reject write path over the F3 ``decision_log`` (lane move),
F4 ``reply_log`` (edited reply), and the F6-owned ``human_decision_log`` audit
table. Contracts documented in ``features/F6-human-override-controls/2_tech_spec.md``
§2.3 / §1.2.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.db_models import HumanDecisionLog, ResolutionDecisionLog
from app.models.human_decision_models import HumanAction, HumanDecisionRecord
from app.models.resolution_models import ResolutionAction
from app.services import reply_service
from app.services.human_decision_engine import (
    HumanDecisionInvalidActionError,
    final_refund_for,
    validate_override_policy,
    validate_rejection_reason,
)
from app.services.reply_service import ReplyAlreadySentError, ReplyNotFoundError

logger = logging.getLogger(__name__)


class HumanDecisionError(Exception):
    """Base class for all F6 human-decision service errors."""


class HumanDecisionTicketNotFoundError(HumanDecisionError):
    """Raised when a ticket has no decision record (→ 404, EC-04)."""


class HumanDecisionAlreadyHandledError(HumanDecisionError):
    """Raised when the ticket already has a human decision (→ 409, US-01 S2 / EC-01)."""


class HumanDecisionNotActionableError(HumanDecisionError):
    """Raised when the ticket is not in the Needs Human Review lane (→ 409, BR 'Only escalated tickets can be acted on')."""


class HumanDecisionNoSuggestionError(HumanDecisionError):
    """Raised on approve when the escalated ticket has no suggested action (→ 422, ERR_HUM_009)."""


class HumanDecisionInvalidAgentError(HumanDecisionError):
    """Raised when agent_id is missing/blank (→ 422, BR 'Agents must be identifiable')."""


class HumanDecisionPersistenceError(HumanDecisionError):
    """Raised when the decision cannot be persisted (→ 500, ERR_HUM_007)."""


def _now_iso() -> str:
    """ISO-8601 UTC timestamp for the audit record."""
    return datetime.now(timezone.utc).isoformat()


def _validate_agent(agent_id: str) -> None:
    """Agents must be identifiable (BR 'Agents must be identifiable' / ERR_HUM_006)."""
    if agent_id is None or not agent_id.strip():
        raise HumanDecisionInvalidAgentError(
            "agent identity is required to record a human decision"
        )


def _row_to_record(row: HumanDecisionLog) -> HumanDecisionRecord:
    """Decode a ``human_decision_log`` ORM row into the public audit model."""
    return HumanDecisionRecord(
        ticket_id=row.ticket_id,
        order_id=row.order_id,
        agent_action=HumanAction(row.agent_action),
        original_action=row.original_action,
        final_action=row.final_action,
        rejection_reason=row.rejection_reason,
        final_reply=row.final_reply,
        agent_id=row.agent_id,
        created_at=row.created_at,
    )


async def _load_decision(db: AsyncSession, ticket_id: str) -> ResolutionDecisionLog:
    """Load the F3 decision record for a ticket (EC-04 → 404)."""
    try:
        row = await db.get(ResolutionDecisionLog, ticket_id)
    except Exception as exc:
        raise HumanDecisionPersistenceError(
            f"unable to read decision record for {ticket_id}"
        ) from exc
    if row is None:
        raise HumanDecisionTicketNotFoundError(f"ticket not found: {ticket_id}")
    return row


async def _ensure_not_handled(db: AsyncSession, ticket_id: str) -> None:
    """Pre-check the one-final-decision invariant (friendly 409 before the PK race)."""
    try:
        existing = await db.get(HumanDecisionLog, ticket_id)
    except Exception as exc:
        raise HumanDecisionPersistenceError(
            f"unable to read human decision log"
        ) from exc
    if existing is not None:
        raise HumanDecisionAlreadyHandledError(
            f"ticket {ticket_id} has already been handled by a human agent"
        )


class _OrderFacts:
    """Minimal order-context facts consumed by the override policy gate."""

    __slots__ = ("status", "value")

    def __init__(self, status: str, value: float):
        self.status = status
        self.value = value


async def _load_order(db: AsyncSession, order_id: str) -> Optional[_OrderFacts]:
    """Load the F1 order context (None when the order is unknown → unrestricted).

    Reads only the ``status`` / ``value`` facts via raw SQL so the policy gate
    works against any F1 ``orders_context`` schema (the ORM ``OrderContext``
    requires additional columns not present in every environment).
    """
    try:
        result = await db.execute(
            text(
                "SELECT status, value FROM orders_context "
                "WHERE order_id = :order_id"
            ),
            {"order_id": order_id},
        )
        row = result.mappings().first()
    except Exception as exc:
        raise HumanDecisionPersistenceError(
            f"unable to read order context for {order_id}"
        ) from exc
    if row is None:
        return None
    return _OrderFacts(status=row["status"] or "", value=float(row["value"] or 0.0))


async def approve_ticket(db: AsyncSession, ticket_id: str, agent_id: str) -> HumanDecisionRecord:
    """Approve the suggested action and resolve the ticket (US-01 S1).

    Validates the agent, loads the F3 decision record, and rejects the call
    when the ticket is unavailable (EC-04), already handled (US-01 S2 /
    EC-01), not in the review lane, or carries no suggested action
    (ERR_HUM_009). On success: flips ``decision_log.auto_resolved`` to True
    (lane move to Auto-Resolved), leaves ``decision_log.action`` as the
    suggested action, and inserts a ``human_decision_log`` row
    (agent_action=approve, original_action=final_action=suggested).

    Args:
        db: Async DB session.
        ticket_id: F1 new_tickets.ticket_id.
        agent_id: Identity of the acting agent (audit requirement).

    Returns:
        The recorded HumanDecisionRecord (200).

    Raises:
        HumanDecisionInvalidAgentError: Blank ``agent_id`` (→ 422).
        HumanDecisionTicketNotFoundError: No decision record for ``ticket_id`` (→ 404).
        HumanDecisionNotActionableError: Ticket is auto-resolved (→ 409).
        HumanDecisionAlreadyHandledError: A human decision already exists (→ 409).
        HumanDecisionNoSuggestionError: No suggested action to approve (→ 422).
        HumanDecisionPersistenceError: Commit/DB failure, incl. IntegrityError
            from a concurrent insert (→ 500; the concurrent loser surfaces as
            AlreadyHandled on the caller's re-read) (→ 500 / EC-01).
    """
    _validate_agent(agent_id)
    row = await _load_decision(db, ticket_id)
    await _ensure_not_handled(db, ticket_id)
    if row.auto_resolved:
        raise HumanDecisionNotActionableError(
            "only tickets awaiting human review can be acted on"
        )
    if not row.action or not row.action.strip():
        raise HumanDecisionNoSuggestionError(
            f"no suggested action to approve for ticket {ticket_id}"
        )

    now = _now_iso()
    human_row = HumanDecisionLog(
        ticket_id=row.ticket_id,
        order_id=row.order_id,
        agent_action=HumanAction.APPROVE.value,
        original_action=row.action,
        final_action=row.action,
        rejection_reason=None,
        final_reply=None,
        agent_id=agent_id,
        created_at=now,
    )
    try:
        row.auto_resolved = True
        db.add(human_row)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HumanDecisionAlreadyHandledError(
            f"ticket {ticket_id} has already been handled by a human agent"
        )
    except Exception as exc:
        await db.rollback()
        raise HumanDecisionPersistenceError(
            f"unable to persist human decision for {ticket_id}"
        ) from exc
    return _row_to_record(human_row)


async def override_ticket(
    db: AsyncSession,
    ticket_id: str,
    agent_id: str,
    action: ResolutionAction,
    reply_body: Optional[str] = None,
) -> HumanDecisionRecord:
    """Replace the suggested action and resolve the ticket (US-02 S1).

    Loads the order context via ``ticket_service.get_order`` and enforces the
    F3 policy gate (US-02 S2 / EC-02). On success: persists the edited reply
    (when ``reply_body`` is non-blank) through F4 edit semantics, flips
    ``decision_log.auto_resolved`` to True, sets ``decision_log.action`` to
    the new action, sets ``decision_log.refund_amount`` for refund actions,
    and inserts a ``human_decision_log`` row preserving the original
    suggestion in ``original_action``.

    Args:
        db: Async DB session.
        ticket_id: F1 new_tickets.ticket_id.
        agent_id: Identity of the acting agent.
        action: The new final action (refund | redelivery | coupon).
        reply_body: Optional edited reply; non-blank values update reply_log.

    Returns:
        The recorded HumanDecisionRecord (200).

    Raises:
        HumanDecisionInvalidAgentError: Blank ``agent_id`` (→ 422).
        HumanDecisionTicketNotFoundError: No decision record (→ 404).
        HumanDecisionNotActionableError: Ticket is auto-resolved (→ 409).
        HumanDecisionAlreadyHandledError: A human decision already exists (→ 409).
        HumanDecisionInvalidActionError: Action not refund/redelivery/coupon (→ 422).
        HumanDecisionPolicyBlockedError: Action forbidden by order context
            (e.g. redelivery on a cancelled order) (→ 422).
        HumanDecisionPersistenceError: Commit/DB failure (→ 500).
    """
    _validate_agent(agent_id)
    row = await _load_decision(db, ticket_id)
    await _ensure_not_handled(db, ticket_id)
    if row.auto_resolved:
        raise HumanDecisionNotActionableError(
            "only tickets awaiting human review can be acted on"
        )
    if action == ResolutionAction.OTHER:
        raise HumanDecisionInvalidActionError(
            "invalid override action: choose 'refund', 'redelivery', or 'coupon'"
        )

    order = await _load_order(db, row.order_id)
    order_status = order.status if order is not None else ""
    order_value = float(order.value) if order is not None else 0.0
    validate_override_policy(action, order_status)

    edited_reply = reply_body if reply_body and reply_body.strip() else None
    if edited_reply is not None:
        try:
            await reply_service.edit_reply(
                db, ticket_id, edited_reply, edited_by=agent_id
            )
        except (ReplyNotFoundError, ReplyAlreadySentError, SQLAlchemyError):
            # §8 notes 4 & 8: the reply edit is a tolerated, non-authoritative
            # side effect — the edited text is still recorded in
            # human_decision_log as final_reply. Missing drafts, sent replies,
            # and schema/DB failures never block the human decision.
            pass

    refund_amount = final_refund_for(
        action, order_value, settings.HUMAN_OVERRIDE_REFUND_RATIO
    )
    now = _now_iso()
    human_row = HumanDecisionLog(
        ticket_id=row.ticket_id,
        order_id=row.order_id,
        agent_action=HumanAction.OVERRIDE.value,
        original_action=row.action,
        final_action=action.value,
        rejection_reason=None,
        final_reply=edited_reply,
        agent_id=agent_id,
        created_at=now,
    )
    try:
        row.auto_resolved = True
        row.action = action.value
        row.refund_amount = refund_amount
        db.add(human_row)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HumanDecisionAlreadyHandledError(
            f"ticket {ticket_id} has already been handled by a human agent"
        )
    except Exception as exc:
        await db.rollback()
        raise HumanDecisionPersistenceError(
            f"unable to persist human decision for {ticket_id}"
        ) from exc
    return _row_to_record(human_row)


async def reject_ticket(db: AsyncSession, ticket_id: str, agent_id: str, reason: str) -> HumanDecisionRecord:
    """Reject the suggested action with a documented reason (US-03 S1).

    The ticket stays in the Needs Human Review lane (``decision_log`` is not
    mutated) but becomes final via the ``human_decision_log`` PK (BR 'One
    final decision per ticket'). The suggested action is never applied
    (``final_action`` is null).

    Args:
        db: Async DB session.
        ticket_id: F1 new_tickets.ticket_id.
        agent_id: Identity of the acting agent.
        reason: Mandatory rejection explanation (US-03 S2 / EC-03).

    Returns:
        The recorded HumanDecisionRecord (200).

    Raises:
        HumanDecisionInvalidAgentError: Blank ``agent_id`` (→ 422).
        HumanDecisionTicketNotFoundError: No decision record (→ 404).
        HumanDecisionNotActionableError: Ticket is auto-resolved (→ 409).
        HumanDecisionAlreadyHandledError: A human decision already exists (→ 409).
        HumanDecisionInvalidReasonError: Blank/whitespace-only ``reason`` (→ 422).
        HumanDecisionPersistenceError: Commit/DB failure (→ 500).
    """
    _validate_agent(agent_id)
    validate_rejection_reason(reason)
    row = await _load_decision(db, ticket_id)
    await _ensure_not_handled(db, ticket_id)
    if row.auto_resolved:
        raise HumanDecisionNotActionableError(
            "only tickets awaiting human review can be acted on"
        )

    now = _now_iso()
    human_row = HumanDecisionLog(
        ticket_id=row.ticket_id,
        order_id=row.order_id,
        agent_action=HumanAction.REJECT.value,
        original_action=row.action,
        final_action=None,
        rejection_reason=reason,
        final_reply=None,
        agent_id=agent_id,
        created_at=now,
    )
    try:
        db.add(human_row)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HumanDecisionAlreadyHandledError(
            f"ticket {ticket_id} has already been handled by a human agent"
        )
    except Exception as exc:
        await db.rollback()
        raise HumanDecisionPersistenceError(
            f"unable to persist human decision for {ticket_id}"
        ) from exc
    return _row_to_record(human_row)


async def list_human_decisions(
    db: AsyncSession, skip: int = 0, limit: int = 50
) -> Tuple[List[HumanDecisionRecord], int]:
    """List the full human-decision audit history, newest first (US-04 S1, EC-06).

    Args:
        db: Async DB session.
        skip: Offset (>= 0).
        limit: Page size (>= 1, <= MAX_PAGE_LIMIT).

    Returns:
        A ``(items, total)`` tuple. ``items`` is empty when no human decision
        has been recorded yet (US-04 S2 — an empty list is a valid 200, not an
        error).
    """
    try:
        count_stmt = select(func.count()).select_from(HumanDecisionLog)
        total = (await db.execute(count_stmt)).scalar_one()

        stmt = (
            select(HumanDecisionLog)
            .order_by(
                HumanDecisionLog.created_at.desc(),
                HumanDecisionLog.ticket_id.desc(),
            )
            .offset(skip)
            .limit(limit)
        )
        rows = list((await db.execute(stmt)).scalars().all())
        return [_row_to_record(row) for row in rows], total
    except Exception as exc:
        raise HumanDecisionPersistenceError("unable to read human decision log") from exc


async def get_human_decision(db: AsyncSession, ticket_id: str) -> Optional[HumanDecisionRecord]:
    """Return the single human decision for a ticket (F6 detail/status check).

    Args:
        db: Async DB session.
        ticket_id: F1 new_tickets.ticket_id.

    Returns:
        The HumanDecisionRecord, or None when no human has acted on the ticket
        (caller maps None → 404).
    """
    try:
        row = await db.get(HumanDecisionLog, ticket_id)
    except Exception as exc:
        raise HumanDecisionPersistenceError("unable to read human decision log") from exc
    if row is None:
        return None
    return _row_to_record(row)
