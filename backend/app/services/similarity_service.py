import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import init_db
from app.models.db_models import ResolvedTicket
from app.models.similarity_models import (
    IndexStatusResponse,
    SimilarTicket,
    SimilarityResponse,
    SimilarityStats,
    SimilarityStatus,
)
from app.services.similarity_engine import (
    CorpusLoadError,
    CorpusRecord,
    SimilarityIndex,
    preprocess_description,
)

logger = logging.getLogger(__name__)


@dataclass
class SimilarityIndexBundle:
    """Cached artifact combining the pure index with full ticket records."""

    index: Optional[SimilarityIndex]
    tickets_by_id: Dict[str, ResolvedTicket]  # full ORM rows for enrichment
    corpus_size: int                          # distinct records in index
    built_at: str                             # ISO-8601 UTC
    duplicates_removed: int


class IndexCache:
    """Process-wide in-memory cache for the SimilarityIndexBundle.

    Thread-safety: reads/writes are protected by an asyncio lock so concurrent
    requests share one index (US-03 large-volume back-to-back requirement).
    """

    _bundle: Optional[SimilarityIndexBundle] = None
    _lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    def invalidate(cls) -> None:
        """Drop the cached bundle; the next call to ``get_bundle`` rebuilds it."""
        cls._bundle = None

    @classmethod
    async def get_bundle(cls, db: AsyncSession) -> SimilarityIndexBundle:
        """Return the current bundle, rebuilding it if absent or stale.

        Staleness detection: rebuilds when the persisted ``resolved_tickets``
        row count differs from the cached ``corpus_size`` (e.g., after an F1
        re-seed). Loading all resolved tickets may raise on DB failure.

        Args:
            db: Async DB session.

        Returns:
            The (possibly freshly built) bundle.

        Raises:
            CorpusLoadError: If the resolved-tickets table cannot be read.
        """
        async with cls._lock:
            count = await cls._count_corpus(db)

            if cls._bundle is not None and cls._bundle.corpus_size == count:
                return cls._bundle

            rows = await load_resolved_corpus(db)

            if not rows:
                bundle = SimilarityIndexBundle(
                    index=None,
                    tickets_by_id={},
                    corpus_size=0,
                    built_at=datetime.now(timezone.utc).isoformat(),
                    duplicates_removed=0,
                )
            else:
                records = [
                    CorpusRecord(ticket_id=ticket.ticket_id, description=ticket.description)
                    for ticket in rows
                ]
                index = SimilarityIndex.fit(
                    records,
                    max_chars=settings.SIMILARITY_MAX_QUERY_CHARS,
                    dedupe_identical=settings.SIMILARITY_DEDUPE_IDENTICAL,
                )
                bundle = SimilarityIndexBundle(
                    index=index,
                    tickets_by_id={ticket.ticket_id: ticket for ticket in rows},
                    corpus_size=len(index.doc_ids),
                    built_at=index.built_at,
                    duplicates_removed=index.duplicates_removed,
                )

            cls._bundle = bundle
            return bundle

    @classmethod
    async def _count_corpus(cls, db: AsyncSession) -> int:
        """Return the number of persisted resolved tickets (for staleness checks)."""
        try:
            await init_db()
            result = await db.execute(select(func.count()).select_from(ResolvedTicket))
            return result.scalar_one()
        except Exception as exc:
            raise CorpusLoadError("unable to load resolved ticket history") from exc


async def load_resolved_corpus(db: AsyncSession) -> List[ResolvedTicket]:
    """Fetch every row from the ``resolved_tickets`` table.

    Args:
        db: Async DB session.

    Returns:
        All resolved tickets as ORM objects, in ascending ``ticket_id`` order.

    Raises:
        CorpusLoadError: If the database query fails.
    """
    try:
        await init_db()
        stmt = select(ResolvedTicket).order_by(ResolvedTicket.ticket_id.asc())
        result = await db.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        raise CorpusLoadError("unable to load resolved ticket history") from exc


async def find_similar(
    db: AsyncSession,
    description: str,
    top_n: int = 3,
) -> SimilarityResponse:
    """Main entry point: find the most similar resolved tickets for a description.

    Pipeline:
      1. ``preprocess_description`` the query. If it becomes empty → return
         ``SimilarityStatus.CANNOT_MATCH`` with empty matches (EC-01).
      2. Load/cache the index bundle. If the corpus is empty → return
         ``SimilarityStatus.NO_HISTORY`` with empty matches (EC-02).
      3. ``index.search(...)``. If no match clears ``min_score`` → return
         ``SimilarityStatus.NO_SIMILAR_CASES`` with empty matches (US-01 S2).
      4. Otherwise return ``SimilarityStatus.MATCHED`` with top-N enriched
         ``SimilarTicket`` records (US-01, US-02), measuring ``elapsed_ms``
         around steps 1–4 (US-03).

    Args:
        db: Async DB session.
        description: Raw new-ticket description (may be blank).
        top_n: Number of past cases to return (default 3).

    Returns:
        A complete ``SimilarityResponse``. Status is one of MATCHED,
        NO_SIMILAR_CASES, CANNOT_MATCH, NO_HISTORY.

    Raises:
        CorpusLoadError: If the resolved-tickets table cannot be read (→ 500).
        SimilarityEngineError: On unexpected engine failure (→ 500).
    """
    start = time.perf_counter()

    def elapsed_ms() -> float:
        return (time.perf_counter() - start) * 1000.0

    preprocessed = preprocess_description(
        description,
        max_chars=settings.SIMILARITY_MAX_QUERY_CHARS,
    )

    if not preprocessed:
        return SimilarityResponse(
            query=description,
            status=SimilarityStatus.CANNOT_MATCH,
            matches=[],
            stats=SimilarityStats(
                corpus_size=0,
                elapsed_ms=elapsed_ms(),
                min_score_threshold=settings.SIMILARITY_MIN_SCORE,
                short_query_penalty_applied=False,
            ),
        )

    bundle = await IndexCache.get_bundle(db)

    if bundle.corpus_size == 0:
        return SimilarityResponse(
            query=description,
            status=SimilarityStatus.NO_HISTORY,
            matches=[],
            stats=SimilarityStats(
                corpus_size=0,
                elapsed_ms=elapsed_ms(),
                min_score_threshold=settings.SIMILARITY_MIN_SCORE,
                short_query_penalty_applied=False,
            ),
        )

    outcome = bundle.index.search(
        preprocessed,
        top_n=top_n,
        min_score=settings.SIMILARITY_MIN_SCORE,
        min_meaningful_tokens=settings.SIMILARITY_MIN_MEANINGFUL_TOKENS,
    )

    if not outcome.matches:
        return SimilarityResponse(
            query=description,
            status=SimilarityStatus.NO_SIMILAR_CASES,
            matches=[],
            stats=SimilarityStats(
                corpus_size=bundle.corpus_size,
                elapsed_ms=elapsed_ms(),
                min_score_threshold=settings.SIMILARITY_MIN_SCORE,
                short_query_penalty_applied=outcome.short_query_penalty_applied,
            ),
        )

    matches: List[SimilarTicket] = []
    for ranked in outcome.matches:
        ticket = bundle.tickets_by_id.get(ranked.ticket_id)
        if ticket is None:
            continue
        matches.append(
            SimilarTicket(
                ticket_id=ticket.ticket_id,
                category=ticket.category,
                description=ticket.description,
                action_taken=ticket.action_taken,
                resolution_note=ticket.resolution_note,
                similarity_score=ranked.similarity_score,
            )
        )

    return SimilarityResponse(
        query=description,
        status=SimilarityStatus.MATCHED,
        matches=matches,
        stats=SimilarityStats(
            corpus_size=bundle.corpus_size,
            elapsed_ms=elapsed_ms(),
            min_score_threshold=settings.SIMILARITY_MIN_SCORE,
            short_query_penalty_applied=outcome.short_query_penalty_applied,
        ),
    )


async def rebuild_index(db: AsyncSession) -> IndexStatusResponse:
    """Force a fresh index build from the persisted history.

    Discards the cached bundle, reloads the corpus, and reports index stats.
    Useful after F1 seeding and for verifying EC-02/EC-04 behaviour.

    Args:
        db: Async DB session.

    Returns:
        Index status with corpus size, build time, and duplicate count.

    Raises:
        CorpusLoadError: If the resolved-tickets table cannot be read.
    """
    IndexCache.invalidate()
    bundle = await IndexCache.get_bundle(db)
    return IndexStatusResponse(
        corpus_size=bundle.corpus_size,
        built_at=bundle.built_at,
        duplicates_removed=bundle.duplicates_removed,
    )
