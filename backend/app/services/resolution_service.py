import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import init_db
from app.models.db_models import ResolutionDecisionLog
from app.models.resolution_models import (
    DecisionInput,
    DecisionListResponse,
    DecisionLogEntry,
    EscalationReason,
    ResolutionDecision,
    ResolutionOutcome,
    ResolutionStats,
)
from app.models.similarity_models import SimilarityStatus
from app.services import similarity_service, ticket_service
from app.services.resolution_engine import (
    ResolutionEngineError,
    ResolutionPersistenceError,
    TicketNotFoundError,
    evaluate_resolution,
)
from app.services.similarity_engine import CorpusLoadError

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decision_to_log_row(decision: ResolutionDecision) -> ResolutionDecisionLog:
    """Map a ``ResolutionDecision`` to a ``decision_log`` ORM row (BR-07)."""
    return ResolutionDecisionLog(
        ticket_id=decision.ticket_id,
        order_id=decision.order_id,
        action=decision.action.value if decision.action else None,
        confidence=decision.confidence,
        auto_resolved=decision.auto_resolved,
        escalation_reason=decision.escalation_reason.value if decision.escalation_reason else None,
        similar_ticket_ids=json.dumps([t.ticket_id for t in decision.similar_tickets]),
        reasoning=decision.reasoning,
        refund_amount=decision.refund_amount,
        created_at=decision.created_at,
    )


def _row_to_entry(row: ResolutionDecisionLog) -> DecisionLogEntry:
    """Decode a ``decision_log`` ORM row into the public audit model."""
    try:
        evidence_ids = json.loads(row.similar_ticket_ids or "[]")
    except (ValueError, TypeError):
        evidence_ids = []
    return DecisionLogEntry(
        ticket_id=row.ticket_id,
        order_id=row.order_id,
        action=row.action,
        confidence=row.confidence,
        auto_resolved=row.auto_resolved,
        escalation_reason=row.escalation_reason,
        similar_ticket_ids=evidence_ids,
        reasoning=row.reasoning,
        refund_amount=row.refund_amount,
        created_at=row.created_at,
    )


async def resolve_ticket(db: AsyncSession, ticket_id: str) -> ResolutionDecision:
    """Resolve a single new ticket end-to-end and persist the decision record.

    Pipeline:
      1. Load the ``NewTicket`` from F1. If missing → raise ``TicketNotFoundError`` (→ 404).
      2. Load the linked ``OrderContext``. If missing → build an escalated
         decision with reason ``order_not_found`` (EC-07) and record it.
      3. Call ``similarity_service.find_similar(db, ticket.description, top_n=settings.RESOLUTION_TOP_N_PRECEDENTS)``
         to obtain the top-N precedents + status (F2 integration).
      4. Build ``DecisionInput`` with ``confidence`` = top match ``similarity_score``
         (0.0 when no matches), ``precedent_status`` = F2 status, and order facts.
      5. ``evaluate_resolution(input)`` → ``ResolutionDecision``.
      6. Persist a ``ResolutionDecisionLog`` row (US-03 S1/S2); re-resolving an
         already-processed ticket overwrites its prior record (idempotent re-run).
      7. Return the decision.

    Args:
        db: Async DB session.
        ticket_id: F1 ``new_tickets.ticket_id``.

    Returns:
        The full ``ResolutionDecision`` (auto-resolved or escalated).

    Raises:
        TicketNotFoundError: If ``ticket_id`` does not exist (→ 404).
        ResolutionPersistenceError: If the decision record cannot be saved (→ 500).
        CorpusLoadError / ResolutionEngineError: On unexpected engine/db failure (→ 500).
    """
    await init_db()

    ticket = await ticket_service.get_new_ticket(db, ticket_id)
    if ticket is None:
        raise TicketNotFoundError(f"ticket not found: {ticket_id}")

    order = await ticket_service.get_order(db, ticket.order_id)

    if order is None:
        # EC-07: linked order not found — escalate, never act without order facts.
        decision = ResolutionDecision(
            ticket_id=ticket.ticket_id,
            order_id=ticket.order_id,
            description=ticket.description,
            outcome=ResolutionOutcome.ESCALATED,
            auto_resolved=False,
            action=None,
            escalation_reason=EscalationReason.ORDER_NOT_FOUND,
            confidence=0.0,
            similar_tickets=[],
            reasoning=f"Escalated: linked order {ticket.order_id} not found in system",
            refund_amount=None,
            created_at=_now_iso(),
        )
    else:
        response = await similarity_service.find_similar(
            db,
            ticket.description,
            top_n=settings.RESOLUTION_TOP_N_PRECEDENTS,
        )
        confidence = response.matches[0].similarity_score if response.matches else 0.0
        decision_input = DecisionInput(
            ticket_id=ticket.ticket_id,
            order_id=ticket.order_id,
            description=ticket.description,
            precedents=response.matches,
            confidence=confidence,
            threshold=settings.RESOLUTION_CONFIDENCE_THRESHOLD,
            expected_precedents=settings.RESOLUTION_TOP_N_PRECEDENTS,
            precedent_status=response.status,
            order_status=order.status,
            order_value=order.value,
            partial_refund_ratio=settings.RESOLUTION_PARTIAL_REFUND_RATIO,
        )
        decision = evaluate_resolution(decision_input)

    await _persist_decision(db, decision)
    return decision


async def _persist_decision(db: AsyncSession, decision: ResolutionDecision) -> None:
    """Upsert a decision record keyed on ``ticket_id`` (BR-07, idempotent)."""
    try:
        existing = await db.get(ResolutionDecisionLog, decision.ticket_id)
        if existing is not None:
            await db.delete(existing)
        db.add(_decision_to_log_row(decision))
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise ResolutionPersistenceError(
            f"unable to persist decision for ticket {decision.ticket_id}"
        ) from exc


async def list_decisions(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[List[DecisionLogEntry], int]:
    """Return (items, total_count) for the audit log, newest first (US-03).

    ``DecisionLogEntry.similar_ticket_ids`` is decoded from the JSON string
    column. Persistence failures reading the table raise ``ResolutionEngineError``.

    Args:
        db: Async DB session.
        skip: Offset for pagination.
        limit: Page size.

    Returns:
        A tuple of ``DecisionLogEntry`` rows (newest first) and the total count.
    """
    await init_db()
    try:
        count_stmt = select(func.count()).select_from(ResolutionDecisionLog)
        total = (await db.execute(count_stmt)).scalar_one()

        stmt = (
            select(ResolutionDecisionLog)
            .order_by(ResolutionDecisionLog.created_at.desc(), ResolutionDecisionLog.ticket_id.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
        return [_row_to_entry(row) for row in rows], total
    except Exception as exc:
        raise ResolutionEngineError("unable to read decision log") from exc


async def get_decision(db: AsyncSession, ticket_id: str) -> Optional[DecisionLogEntry]:
    """Return a single audit record by ticket id, or None if never processed.

    Args:
        db: Async DB session.
        ticket_id: F1 ``new_tickets.ticket_id``.

    Returns:
        The ``DecisionLogEntry`` or None.
    """
    await init_db()
    try:
        row = await db.get(ResolutionDecisionLog, ticket_id)
        if row is None:
            return None
        return _row_to_entry(row)
    except Exception as exc:
        raise ResolutionEngineError("unable to read decision log") from exc


async def compute_resolution_stats(db: AsyncSession) -> ResolutionStats:
    """Aggregate counts for the dashboard lane badges (F5 consumer).

    Args:
        db: Async DB session.

    Returns:
        ``ResolutionStats`` with totals and per-action / per-reason breakdowns.
    """
    await init_db()
    try:
        rows = (await db.execute(select(ResolutionDecisionLog))).scalars().all()
    except Exception as exc:
        raise ResolutionEngineError("unable to read decision log") from exc

    total = len(rows)
    auto = sum(1 for r in rows if r.auto_resolved)
    by_action: dict = {}
    by_reason: dict = {}
    for row in rows:
        if row.action:
            by_action[row.action] = by_action.get(row.action, 0) + 1
        if row.escalation_reason:
            by_reason[row.escalation_reason] = by_reason.get(row.escalation_reason, 0) + 1

    return ResolutionStats(
        total_decisions=total,
        auto_resolved_count=auto,
        escalated_count=total - auto,
        by_action=by_action,
        by_escalation_reason=by_reason,
    )
