from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.resolution_models import (
    DecisionListResponse,
    DecisionLogEntry,
    ResolutionDecision,
    ResolutionRequest,
    ResolutionStats,
)
from app.services import resolution_service
from app.services.resolution_engine import ResolutionEngineError, TicketNotFoundError
from app.services.similarity_engine import CorpusLoadError, SimilarityEngineError

router = APIRouter(prefix="/api/v1", tags=["resolution"])


@router.post("/resolution/resolve", response_model=ResolutionDecision)
async def resolve_ticket_endpoint(
    payload: ResolutionRequest,
    db: AsyncSession = Depends(get_db),
) -> ResolutionDecision:
    """Resolve a new ticket (auto-resolve or escalate) and record the decision.

    Args:
        payload: Request body with ``ticket_id``.
        db: Async DB session dependency.

    Returns:
        A ``ResolutionDecision`` (200). See API contract §4.1 for statuses.

    Raises:
        HTTPException(404): On ``TicketNotFoundError``.
        HTTPException(500): On ``CorpusLoadError`` / ``SimilarityEngineError`` /
            ``ResolutionEngineError`` (incl. persistence failure).
    """
    try:
        return await resolution_service.resolve_ticket(db, payload.ticket_id)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (CorpusLoadError, SimilarityEngineError, ResolutionEngineError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Resolution engine failed: {exc}",
        ) from exc


@router.get("/resolution/decisions", response_model=DecisionListResponse)
async def list_decisions_endpoint(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> DecisionListResponse:
    """List the full decision audit log, newest first (US-03)."""
    try:
        items, total = await resolution_service.list_decisions(db, skip, limit)
    except (CorpusLoadError, SimilarityEngineError, ResolutionEngineError) as exc:
        raise HTTPException(status_code=500, detail=f"Resolution engine failed: {exc}") from exc
    return DecisionListResponse(total=total, skip=skip, limit=limit, items=items)


@router.get("/resolution/decisions/{ticket_id}", response_model=DecisionLogEntry)
async def get_decision_endpoint(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
) -> DecisionLogEntry:
    """Return the decision record for a single ticket (US-03 audit detail).

    Raises:
        HTTPException(404): If no decision record exists for ``ticket_id``.
    """
    try:
        entry = await resolution_service.get_decision(db, ticket_id)
    except (CorpusLoadError, SimilarityEngineError, ResolutionEngineError) as exc:
        raise HTTPException(status_code=500, detail=f"Resolution engine failed: {exc}") from exc
    if entry is None:
        raise HTTPException(status_code=404, detail=f"no decision record for ticket {ticket_id}")
    return entry


@router.get("/resolution/stats", response_model=ResolutionStats)
async def resolution_stats_endpoint(
    db: AsyncSession = Depends(get_db),
) -> ResolutionStats:
    """Return aggregate resolution statistics for the dashboard (F5)."""
    try:
        return await resolution_service.compute_resolution_stats(db)
    except (CorpusLoadError, SimilarityEngineError, ResolutionEngineError) as exc:
        raise HTTPException(status_code=500, detail=f"Resolution engine failed: {exc}") from exc
