"""Reply drafting orchestration + persistence service (FEAT-004).

Calls F3's ``resolution_service.resolve_ticket`` to obtain the authoritative
decision, renders it via ``reply_engine.draft_reply``, and persists an auditable
``reply_log`` record that preserves agent edits (EC-04).

Contracts documented in ``features/F4-reply-drafting/2_tech_spec.md`` §2.3.
"""

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import init_db
from app.models.db_models import ReplyLog
from app.models.reply_models import (
    ReplyRecord,
    ReplyStatus,
    ReplyStats,
    ReplyVariant,
)
from app.services import resolution_service
from app.services.reply_engine import (
    ReplyEngineError,
    ReplyTemplateError,
    draft_reply,
)
from app.services.resolution_engine import TicketNotFoundError

logger = logging.getLogger(__name__)


class ReplyNotFoundError(ReplyEngineError):
    """Raised when no ``reply_log`` record exists for the requested ticket (→ 404)."""


class ReplyAlreadySentError(ReplyEngineError):
    """Raised when an agent tries to edit a reply that has already been sent (→ 409)."""


class InvalidReplyBodyError(ReplyEngineError):
    """Raised when an edit/send body is empty or whitespace-only (→ 422)."""


class ReplyPersistenceError(ReplyEngineError):
    """Raised when a ``reply_log`` record cannot be written (→ 500)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_body(body: str) -> None:
    if not body or not body.strip():
        raise InvalidReplyBodyError("reply body must not be empty")


def _row_to_record(row: ReplyLog) -> ReplyRecord:
    """Decode a ``reply_log`` ORM row into the public ``ReplyRecord`` model."""
    try:
        cited = json.loads(row.cited_ticket_ids or "[]")
    except (ValueError, TypeError):
        cited = []
    try:
        history = json.loads(row.draft_history or "[]")
    except (ValueError, TypeError):
        history = []
    return ReplyRecord(
        ticket_id=row.ticket_id,
        variant=ReplyVariant(row.variant),
        original_draft=row.original_draft,
        final_body=row.final_body,
        status=ReplyStatus(row.status),
        cited_ticket_ids=cited,
        draft_history=history,
        edited_by=row.edited_by,
        edited_at=row.edited_at,
        sent_at=row.sent_at,
        created_at=row.created_at,
    )


async def generate_reply(db: AsyncSession, ticket_id: str) -> ReplyRecord:
    """Draft (or re-draft) the reply for one ticket and persist it (US-01..US-03).

    Pipeline:
      1. Call ``resolution_service.resolve_ticket(db, ticket_id)`` to obtain the
         authoritative ``ResolutionDecision`` (idempotent; re-runs F2+F3 so a
         decision always exists — BR-01). ``TicketNotFoundError`` propagates (→ 404).
      2. ``draft_reply(decision)`` → deterministic ``DraftedReply``.
      3. Upsert a ``ReplyLog`` row keyed on ``ticket_id`` (one reply per ticket):
         - no existing row → create with ``original_draft = final_body = draft``,
           ``status = draft``;
         - existing row with ``status = sent`` → **return unchanged** — the
           customer-facing reply must keep reflecting the agent's final version (EC-04);
         - existing row with ``status = draft`` → append the prior ``original_draft``
           to ``draft_history`` (audit), refresh ``original_draft``/``variant``/cited ids;
           if never edited (``edited_by is None``) also refresh ``final_body``; if edited,
           **preserve ``final_body`` and the edit metadata** (EC-04).
      4. Persist and return the ``ReplyRecord``.

    Args:
        db: Async DB session.
        ticket_id: F1 ``new_tickets.ticket_id``.

    Returns:
        The persisted ``ReplyRecord`` (status ``draft`` unless already sent).

    Raises:
        TicketNotFoundError: If the ticket does not exist (→ 404).
        ReplyTemplateError / ReplyPersistenceError: On render or write failure (→ 500).
    """
    await init_db()

    decision = await resolution_service.resolve_ticket(db, ticket_id)
    try:
        drafted = draft_reply(decision)
    except ReplyTemplateError as exc:
        raise ReplyTemplateError(
            f"unable to draft reply for ticket {ticket_id}: {exc}"
        ) from exc

    now = _now_iso()
    variant = drafted.variant.value
    reply_text = drafted.reply_text
    cited = json.dumps(drafted.cited_ticket_ids)

    existing = await db.get(ReplyLog, ticket_id)
    if existing is not None and existing.status == ReplyStatus.SENT.value:
        # EC-04: a sent reply is frozen; never overwrite the customer-facing version.
        return _row_to_record(existing)

    try:
        if existing is None:
            row = ReplyLog(
                ticket_id=ticket_id,
                variant=variant,
                original_draft=reply_text,
                final_body=reply_text,
                status=ReplyStatus.DRAFT.value,
                cited_ticket_ids=cited,
                edited_by=None,
                edited_at=None,
                sent_at=None,
                draft_history=json.dumps([]),
                created_at=now,
            )
            db.add(row)
        else:
            history = json.loads(existing.draft_history or "[]")
            history.append(existing.original_draft)
            existing.draft_history = json.dumps(history)
            existing.variant = variant
            existing.original_draft = reply_text
            existing.cited_ticket_ids = cited
            existing.created_at = now
            if existing.edited_by is None:
                existing.final_body = reply_text
            # else: preserve final_body / edited_by / edited_at (EC-04)
        await db.commit()
        refreshed = await db.get(ReplyLog, ticket_id)
        assert refreshed is not None
        return _row_to_record(refreshed)
    except Exception as exc:
        await db.rollback()
        raise ReplyPersistenceError(
            f"unable to persist reply for ticket {ticket_id}"
        ) from exc


async def get_reply(db: AsyncSession, ticket_id: str) -> Optional[ReplyRecord]:
    """Return a single reply record by ticket id, or None if never generated.

    Args:
        db: Async DB session.
        ticket_id: F1 ``new_tickets.ticket_id``.

    Returns:
        The ``ReplyRecord`` or None.
    """
    await init_db()
    try:
        row = await db.get(ReplyLog, ticket_id)
    except Exception as exc:
        raise ReplyPersistenceError("unable to read reply log") from exc
    if row is None:
        return None
    return _row_to_record(row)


async def list_replies(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[List[ReplyRecord], int]:
    """Return (items, total_count) for the reply log, newest first (US-02 audit).

    Args:
        db: Async DB session.
        skip: Offset for pagination.
        limit: Page size.

    Returns:
        A tuple of ``ReplyRecord`` rows (newest first) and the total count.
    """
    await init_db()
    try:
        count_stmt = select(func.count()).select_from(ReplyLog)
        total = (await db.execute(count_stmt)).scalar_one()

        stmt = (
            select(ReplyLog)
            .order_by(ReplyLog.created_at.desc(), ReplyLog.ticket_id.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
        return [_row_to_record(row) for row in rows], total
    except Exception as exc:
        raise ReplyPersistenceError("unable to read reply log") from exc


async def edit_reply(
    db: AsyncSession,
    ticket_id: str,
    body: str,
    edited_by: Optional[str] = None,
) -> ReplyRecord:
    """Replace the customer-facing wording of an unsent draft (US-02 S1).

    Rules:
      - No record → ``ReplyNotFoundError`` (→ 404).
      - Empty/whitespace ``body`` → ``InvalidReplyBodyError`` (→ 422).
      - Already sent (``status == SENT``) → ``ReplyAlreadySentError`` (→ 409):
        sent replies are immutable to keep the audit trail intact.
      - Otherwise set ``final_body = body``, ``edited_by``, ``edited_at``; the
        ``original_draft`` and ``draft_history`` are untouched (BR-05). Status
        remains ``draft`` until ``send_reply``.

    Args:
        db: Async DB session.
        ticket_id: F1 ``new_tickets.ticket_id``.
        body: Agent's replacement wording (non-empty).
        edited_by: Optional agent identifier for audit.

    Returns:
        The updated ``ReplyRecord`` (status ``draft``).

    Raises:
        ReplyNotFoundError: No reply record (→ 404).
        InvalidReplyBodyError: Empty body (→ 422).
        ReplyAlreadySentError: Reply already sent (→ 409).
        ReplyPersistenceError: Write failure (→ 500).
    """
    await init_db()
    _validate_body(body)

    row = await db.get(ReplyLog, ticket_id)
    if row is None:
        raise ReplyNotFoundError(f"no reply record for ticket {ticket_id}")
    if row.status == ReplyStatus.SENT.value:
        raise ReplyAlreadySentError(f"reply already sent for ticket {ticket_id}")

    try:
        row.final_body = body.strip()
        row.edited_by = edited_by
        row.edited_at = _now_iso()
        await db.commit()
        refreshed = await db.get(ReplyLog, ticket_id)
        assert refreshed is not None
        return _row_to_record(refreshed)
    except Exception as exc:
        await db.rollback()
        raise ReplyPersistenceError(
            f"unable to edit reply for ticket {ticket_id}"
        ) from exc


async def send_reply(
    db: AsyncSession,
    ticket_id: str,
    body: Optional[str] = None,
    edited_by: Optional[str] = None,
) -> ReplyRecord:
    """Send a reply to the customer, optionally applying a final edit (US-02 S1).

    Rules:
      - No record → ``ReplyNotFoundError`` (→ 404).
      - When ``body`` is provided it is validated and applied exactly like
        ``edit_reply`` (final edit) before sending.
      - When ``body`` is None the current ``final_body`` is sent as-is (draft or
        prior edit).
      - Already sent → return the record unchanged (idempotent).
      - Otherwise set ``status = sent`` and ``sent_at``; freeze the record.

    Args:
        db: Async DB session.
        ticket_id: F1 ``new_tickets.ticket_id``.
        body: Optional final wording (edit + send in one step).
        edited_by: Optional agent identifier for audit.

    Returns:
        The sent ``ReplyRecord`` (status ``sent``).

    Raises:
        ReplyNotFoundError: No reply record (→ 404).
        InvalidReplyBodyError: Empty ``body`` (→ 422).
        ReplyPersistenceError: Write failure (→ 500).
    """
    await init_db()

    row = await db.get(ReplyLog, ticket_id)
    if row is None:
        raise ReplyNotFoundError(f"no reply record for ticket {ticket_id}")

    if body is not None:
        _validate_body(body)
        row.final_body = body.strip()
        row.edited_by = edited_by
        row.edited_at = _now_iso()

    if row.status == ReplyStatus.SENT.value:
        # Idempotent: an already-sent reply is returned unchanged.
        return _row_to_record(row)

    try:
        row.status = ReplyStatus.SENT.value
        row.sent_at = _now_iso()
        await db.commit()
        refreshed = await db.get(ReplyLog, ticket_id)
        assert refreshed is not None
        return _row_to_record(refreshed)
    except Exception as exc:
        await db.rollback()
        raise ReplyPersistenceError(
            f"unable to send reply for ticket {ticket_id}"
        ) from exc


async def compute_reply_stats(db: AsyncSession) -> ReplyStats:
    """Aggregate counts for the dashboard (F5 consumer).

    Args:
        db: Async DB session.

    Returns:
        ``ReplyStats`` with totals and per-variant breakdowns.
    """
    await init_db()
    try:
        rows = (await db.execute(select(ReplyLog))).scalars().all()
    except Exception as exc:
        raise ReplyPersistenceError("unable to read reply log") from exc

    total = len(rows)
    sent = sum(1 for r in rows if r.status == ReplyStatus.SENT.value)
    by_variant: dict = {}
    for row in rows:
        by_variant[row.variant] = by_variant.get(row.variant, 0) + 1

    return ReplyStats(
        total_replies=total,
        draft_count=total - sent,
        sent_count=sent,
        by_variant=by_variant,
    )
