"""API router for the Reply Drafting feature (FEAT-004).

Endpoints documented in ``features/F4-reply-drafting/2_tech_spec.md`` §2.4 / §4.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.reply_models import (
    EditReplyRequest,
    GenerateReplyRequest,
    ReplyListResponse,
    ReplyRecord,
    ReplyStats,
    SendReplyRequest,
)
from app.services import reply_service
from app.services.reply_engine import ReplyEngineError, ReplyTemplateError
from app.services.resolution_engine import ResolutionEngineError, TicketNotFoundError
from app.services.similarity_engine import CorpusLoadError, SimilarityEngineError

router = APIRouter(prefix="/api/v1", tags=["replies"])


@router.post("/replies/generate", response_model=ReplyRecord)
async def generate_reply_endpoint(
    payload: GenerateReplyRequest,
    db: AsyncSession = Depends(get_db),
) -> ReplyRecord:
    """Generate (and persist) the deterministic reply draft for one ticket."""
    try:
        return await reply_service.generate_reply(db, payload.ticket_id)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (CorpusLoadError, SimilarityEngineError, ResolutionEngineError, ReplyEngineError) as exc:
        raise HTTPException(status_code=500, detail=f"Reply drafting failed: {exc}") from exc


@router.get("/replies", response_model=ReplyListResponse)
async def list_replies_endpoint(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> ReplyListResponse:
    """List the full reply log, newest first (US-02 audit)."""
    try:
        items, total = await reply_service.list_replies(db, skip, limit)
    except ReplyEngineError as exc:
        raise HTTPException(status_code=500, detail=f"Reply drafting failed: {exc}") from exc
    return ReplyListResponse(total=total, skip=skip, limit=limit, items=items)


# NOTE: registered BEFORE /replies/{ticket_id} so the literal path "stats" is
# not captured by the {ticket_id} path parameter (tech spec §8 note 5).
@router.get("/replies/stats", response_model=ReplyStats)
async def reply_stats_endpoint(
    db: AsyncSession = Depends(get_db),
) -> ReplyStats:
    """Return aggregate reply statistics for the dashboard (F5)."""
    try:
        return await reply_service.compute_reply_stats(db)
    except ReplyEngineError as exc:
        raise HTTPException(status_code=500, detail=f"Reply drafting failed: {exc}") from exc


@router.get("/replies/{ticket_id}", response_model=ReplyRecord)
async def get_reply_endpoint(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
) -> ReplyRecord:
    """Return the reply record for one ticket (US-02 detail view)."""
    try:
        record = await reply_service.get_reply(db, ticket_id)
    except ReplyEngineError as exc:
        raise HTTPException(status_code=500, detail=f"Reply drafting failed: {exc}") from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"no reply record for ticket {ticket_id}")
    return record


@router.put("/replies/{ticket_id}", response_model=ReplyRecord)
async def edit_reply_endpoint(
    ticket_id: str,
    payload: EditReplyRequest,
    db: AsyncSession = Depends(get_db),
) -> ReplyRecord:
    """Edit the customer-facing wording of an unsent draft (US-02 S1)."""
    try:
        return await reply_service.edit_reply(db, ticket_id, payload.body, payload.edited_by)
    except reply_service.ReplyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except reply_service.ReplyAlreadySentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except reply_service.InvalidReplyBodyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ReplyEngineError as exc:
        raise HTTPException(status_code=500, detail=f"Reply drafting failed: {exc}") from exc


@router.post("/replies/{ticket_id}/send", response_model=ReplyRecord)
async def send_reply_endpoint(
    ticket_id: str,
    payload: Optional[SendReplyRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> ReplyRecord:
    """Send a reply to the customer (as-is or with a final edit)."""
    body = payload.body if payload else None
    edited_by = payload.edited_by if payload else None
    try:
        return await reply_service.send_reply(db, ticket_id, body, edited_by)
    except reply_service.ReplyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except reply_service.InvalidReplyBodyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ReplyEngineError as exc:
        raise HTTPException(status_code=500, detail=f"Reply drafting failed: {exc}") from exc
