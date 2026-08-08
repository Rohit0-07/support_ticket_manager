"""Two-Lane Dashboard aggregation service (FEAT-005).

Read-only aggregation over the F1/F3/F4 data stores — the board and detail
views are derived aggregates composed at request time; F5 introduces no new
tables (``2_tech_spec.md`` §1). It reads the persisted F3 ``decision_log`` and
F1 ``new_tickets`` tables to render cards, the F4 ``reply_log`` table for the
detail view's drafted reply, and recomputes the top-3 evidence deterministically
via the pure F2 ``SimilarityIndex`` so similarity scores match decision time
(§1.2 evidence-fidelity note, BR-03).
"""

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import init_db
from app.models.db_models import ResolutionDecisionLog
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
from app.services.similarity_engine import (
    CorpusRecord,
    SimilarityEngineError,
    SimilarityIndex,
    preprocess_description,
)

logger = logging.getLogger(__name__)


class DashboardError(Exception):
    """Base class for all F5 dashboard errors."""


class DashboardDataUnavailableError(DashboardError):
    """Raised when the underlying F1/F3/F4 data cannot be read (→ 500, EC-06)."""


class DashboardTicketNotFoundError(DashboardError):
    """Raised when no decision record exists for a requested ticket (→ 404)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def lane_for(auto_resolved: bool) -> DashboardLane:
    """Map the persisted resolution outcome to a dashboard lane (BR-01).

    Args:
        auto_resolved: The persisted ``decision_log.auto_resolved`` flag.

    Returns:
        DashboardLane.AUTO_RESOLVED when True, else DashboardLane.NEEDS_REVIEW.

    Raises:
        No exceptions.
    """
    if auto_resolved:
        return DashboardLane.AUTO_RESOLVED
    return DashboardLane.NEEDS_REVIEW


def confidence_level(
    score: float,
    high_threshold: float = 0.75,
    medium_threshold: float = 0.40,
) -> ConfidenceLevel:
    """Bucket a confidence score for color-coding (US-02 S1, EC-04).

    Boundary rule is inclusive at the high threshold and inclusive at the
    medium threshold (matches the ``>=`` resolution boundary BR-02):
      - HIGH   when score >= high_threshold
      - MEDIUM when medium_threshold <= score < high_threshold
      - LOW    when score < medium_threshold

    Args:
        score: Confidence in [0.0, 1.0].
        high_threshold: High bucket floor (default 0.75).
        medium_threshold: Medium bucket floor (default 0.40).

    Returns:
        The ConfidenceLevel bucket.

    Raises:
        ValueError: If score is outside [0.0, 1.0], or if thresholds are
            not within [0.0, 1.0] or high_threshold < medium_threshold.
    """
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"score must be within [0.0, 1.0] (got: {score})")
    if not 0.0 <= high_threshold <= 1.0:
        raise ValueError(f"high_threshold must be within [0.0, 1.0] (got: {high_threshold})")
    if not 0.0 <= medium_threshold <= 1.0:
        raise ValueError(
            f"medium_threshold must be within [0.0, 1.0] (got: {medium_threshold})"
        )
    if high_threshold < medium_threshold:
        raise ValueError(
            f"high_threshold must be >= medium_threshold (got: {high_threshold} < {medium_threshold})"
        )

    if score >= high_threshold:
        return ConfidenceLevel.HIGH
    if score >= medium_threshold:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def truncate_description(text: str, max_chars: int = 120) -> str:
    """Shorten a long description for card display with a '…' ellipsis (EC-03).

    The single ellipsis character U+2026 replaces the removed tail; the
    returned string is never longer than max_chars. Text at or under
    max_chars is returned unchanged.

    Args:
        text: The full ticket description.
        max_chars: Maximum preview length, must be >= 1.

    Returns:
        The preview string (unmodified when len(text) <= max_chars).

    Raises:
        ValueError: If max_chars < 1.
    """
    if max_chars < 1:
        raise ValueError(f"max_chars must be >= 1 (got: {max_chars})")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


async def build_board(db: AsyncSession) -> DashboardBoard:
    """Aggregate the full two-lane board (US-01, US-04).

    Sources (all read-only):
      - ``decision_log`` (F3): lane, action, confidence, escalation_reason,
        refund_amount, created_at, evidence ids.
      - ``new_tickets`` (F1): full description (truncated for the card).
    Tickets are included iff they have a decision record; ordering is
    newest-first (created_at DESC, ticket_id DESC). Both lane sections are
    always present with accurate count badges (BR-04, EC-01).

    Args:
        db: Async DB session.

    Returns:
        A DashboardBoard with populated auto_resolved and needs_review
        sections and per-lane counts.

    Raises:
        DashboardDataUnavailableError: If any source table cannot be read
            (unavailable DB or F1/F3 engine failure).
    """
    await init_db()
    try:
        stmt = (
            select(ResolutionDecisionLog)
            .order_by(ResolutionDecisionLog.created_at.desc(), ResolutionDecisionLog.ticket_id.desc())
        )
        rows = list((await db.execute(stmt)).scalars().all())
    except Exception as exc:
        raise DashboardDataUnavailableError("unable to read decision log") from exc

    try:
        descriptions = await _load_new_ticket_descriptions(db)
    except Exception as exc:
        raise DashboardDataUnavailableError("unable to read new ticket data") from exc

    auto_cards: List[DashboardTicketCard] = []
    review_cards: List[DashboardTicketCard] = []
    for row in rows:
        card = _to_card(row, descriptions.get(row.ticket_id, ""))
        if row.auto_resolved:
            auto_cards.append(card)
        else:
            review_cards.append(card)

    return DashboardBoard(
        loaded_at=_now_iso(),
        auto_resolved=DashboardLaneSection(
            label="Auto-Resolved",
            count=len(auto_cards),
            tickets=auto_cards,
        ),
        needs_review=DashboardLaneSection(
            label="Needs Human Review",
            count=len(review_cards),
            tickets=review_cards,
        ),
    )


async def build_ticket_detail(
    db: AsyncSession, ticket_id: str
) -> Optional[DashboardTicketDetail]:
    """Aggregate full read-only detail for one ticket (US-03, EC-02).

    Composes the persisted decision (verbatim reasoning/confidence/action),
    the full F1 description, the F4 reply record (if any), and the top-3
    evidence recomputed deterministically via the pure F2 ``SimilarityIndex``
    for scores (BR-03 note in ``2_tech_spec.md`` §1.2).

    Args:
        db: Async DB session.
        ticket_id: F1 new_tickets.ticket_id.

    Returns:
        The DashboardTicketDetail, or None when no decision record exists
        for ``ticket_id`` (caller maps None → 404).

    Raises:
        DashboardDataUnavailableError: If required data cannot be read.
    """
    await init_db()
    try:
        row = await db.get(ResolutionDecisionLog, ticket_id)
    except Exception as exc:
        raise DashboardDataUnavailableError("unable to read decision log") from exc

    if row is None:
        return None

    description = ""
    try:
        description = await _load_description(db, ticket_id)
    except Exception as exc:
        raise DashboardDataUnavailableError("unable to read new ticket data") from exc

    reply: Optional[ReplySummary] = None
    try:
        reply = await _load_reply(db, ticket_id)
    except Exception as exc:
        raise DashboardDataUnavailableError("unable to read reply log") from exc

    evidence = await _load_similar_cases(
        db,
        description,
        top_n=settings.RESOLUTION_TOP_N_PRECEDENTS,
    )
    status, cases = evidence

    lane = lane_for(row.auto_resolved)
    return DashboardTicketDetail(
        ticket_id=row.ticket_id,
        order_id=row.order_id,
        description=description,
        action=row.action,
        confidence=row.confidence,
        confidence_level=confidence_level(row.confidence),
        lane=lane,
        auto_resolved=row.auto_resolved,
        escalation_reason=row.escalation_reason,
        reasoning=row.reasoning,
        refund_amount=row.refund_amount,
        similar_cases=cases,
        similar_cases_status=status,
        reply=reply,
        created_at=row.created_at,
    )


def _to_card(row: ResolutionDecisionLog, description: str) -> DashboardTicketCard:
    """Map a decision row + description to a compact lane card (US-02)."""
    return DashboardTicketCard(
        ticket_id=row.ticket_id,
        description_preview=truncate_description(
            description, max_chars=settings.DASHBOARD_PREVIEW_CHARS
        ),
        action=row.action,
        confidence=row.confidence,
        confidence_level=confidence_level(row.confidence),
        lane=lane_for(row.auto_resolved),
        auto_resolved=row.auto_resolved,
        escalation_reason=row.escalation_reason,
        created_at=row.created_at,
    )


async def _load_new_ticket_descriptions(db: AsyncSession) -> dict:
    """Return a mapping ticket_id → description for every F1 new ticket."""
    result = await db.execute(
        text("SELECT ticket_id, description FROM new_tickets")
    )
    return {row.ticket_id: row.description for row in result.mappings()}


async def _load_description(db: AsyncSession, ticket_id: str) -> str:
    """Return the full F1 description for one ticket (empty when unknown)."""
    result = await db.execute(
        text("SELECT description FROM new_tickets WHERE ticket_id = :ticket_id"),
        {"ticket_id": ticket_id},
    )
    row = result.mappings().first()
    if row is None:
        return ""
    return row["description"]


async def _load_reply(db: AsyncSession, ticket_id: str) -> Optional[ReplySummary]:
    """Return the F4 reply record for one ticket, or None (ERR_DASH_005)."""
    result = await db.execute(
        text(
            "SELECT ticket_id, variant, final_body, status "
            "FROM reply_log WHERE ticket_id = :ticket_id"
        ),
        {"ticket_id": ticket_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return ReplySummary(
        final_body=row["final_body"],
        variant=row["variant"],
        status=row["status"],
    )


async def _load_similar_cases(
    db: AsyncSession,
    description: str,
    top_n: int,
) -> Tuple[SimilarCasesStatus, List[SimilarCaseEvidence]]:
    """Recompute the top-3 evidence with scores for a ticket description.

    Reuses the deterministic pure F2 ``SimilarityIndex`` (BR-03): the corpus is
    read directly from ``resolved_tickets`` and ranked the same way F3 ranked it
    at decision time, so the evidence and scores shown are the exact items used
    in the decision.

    Args:
        db: Async DB session.
        description: Full untruncated ticket description.
        top_n: Number of evidence cases to surface (F3 RESOLUTION_TOP_N_PRECEDENTS).

    Returns:
        A ``(status, cases)`` tuple. Status is FOUND with up to ``top_n`` ranked
        cases, or NONE when the corpus is empty / no match clears the minimum
        threshold / the description cannot be matched (EC-02).

    Raises:
        DashboardDataUnavailableError: If the resolved-tickets corpus cannot be read.
    """
    try:
        result = await db.execute(
            text(
                "SELECT ticket_id, description, action_taken, resolution_note "
                "FROM resolved_tickets"
            )
        )
        rows = list(result.mappings().all())
    except Exception as exc:
        raise DashboardDataUnavailableError("unable to read similar case evidence") from exc

    if not rows:
        return SimilarCasesStatus.NONE, []

    records = [
        CorpusRecord(ticket_id=row["ticket_id"], description=row["description"])
        for row in rows
    ]
    try:
        index = SimilarityIndex.fit(
            records,
            max_chars=settings.SIMILARITY_MAX_QUERY_CHARS,
            dedupe_identical=settings.SIMILARITY_DEDUPE_IDENTICAL,
        )
    except SimilarityEngineError:
        return SimilarCasesStatus.NONE, []

    preprocessed = preprocess_description(
        description,
        max_chars=settings.SIMILARITY_MAX_QUERY_CHARS,
    )
    if not preprocessed:
        return SimilarCasesStatus.NONE, []

    try:
        outcome = index.search(
            preprocessed,
            top_n=top_n,
            min_score=settings.SIMILARITY_MIN_SCORE,
            min_meaningful_tokens=settings.SIMILARITY_MIN_MEANINGFUL_TOKENS,
        )
    except SimilarityEngineError:
        return SimilarCasesStatus.NONE, []

    if not outcome.matches:
        return SimilarCasesStatus.NONE, []

    by_id = {row["ticket_id"]: row for row in rows}
    cases: List[SimilarCaseEvidence] = []
    for ranked in outcome.matches:
        row = by_id.get(ranked.ticket_id)
        if row is None:
            continue
        cases.append(
            SimilarCaseEvidence(
                ticket_id=row["ticket_id"],
                description=row["description"],
                action_taken=row["action_taken"],
                resolution_note=row["resolution_note"],
                similarity_score=ranked.similarity_score,
            )
        )

    if not cases:
        return SimilarCasesStatus.NONE, []
    return SimilarCasesStatus.FOUND, cases
