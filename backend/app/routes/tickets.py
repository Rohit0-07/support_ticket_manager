from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.models.ticket_models import (
    ResolvedTicketSchema,
    ResolvedTicketListResponse,
    NewTicketSchema,
    NewTicketListResponse,
)
from app.services import ticket_service

router = APIRouter(prefix="/api/v1", tags=["tickets"])


@router.get("/resolved-tickets", response_model=ResolvedTicketListResponse)
async def list_resolved_tickets(
    skip: int = Query(0, ge=0),
    limit: int = Query(settings.DEFAULT_PAGE_LIMIT, ge=1, le=settings.MAX_PAGE_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    items, total = await ticket_service.list_resolved_tickets(db, skip=skip, limit=limit)
    return ResolvedTicketListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=items,
    )


@router.get("/resolved-tickets/{ticket_id}", response_model=ResolvedTicketSchema)
async def get_resolved_ticket(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
):
    ticket = await ticket_service.get_resolved_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(
            status_code=404,
            detail=f"Resolved ticket '{ticket_id}' not found",
        )
    return ticket


@router.get("/new-tickets", response_model=NewTicketListResponse)
async def list_new_tickets(
    skip: int = Query(0, ge=0),
    limit: int = Query(settings.DEFAULT_PAGE_LIMIT, ge=1, le=settings.MAX_PAGE_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    items, total = await ticket_service.list_new_tickets(db, skip=skip, limit=limit)
    return NewTicketListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=items,
    )


@router.get("/new-tickets/{ticket_id}", response_model=NewTicketSchema)
async def get_new_ticket(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
):
    ticket = await ticket_service.get_new_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(
            status_code=404,
            detail=f"New ticket '{ticket_id}' not found",
        )
    return ticket
