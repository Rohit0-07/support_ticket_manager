from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.models.ticket_models import (
    OrderContextSchema,
    OrderContextListResponse,
)
from app.services import ticket_service

router = APIRouter(prefix="/api/v1", tags=["orders"])


@router.get("/orders", response_model=OrderContextListResponse)
async def list_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(settings.DEFAULT_PAGE_LIMIT, ge=1, le=settings.MAX_PAGE_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    items, total = await ticket_service.list_orders(db, skip=skip, limit=limit)
    return OrderContextListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=items,
    )


@router.get("/orders/{order_id}", response_model=OrderContextSchema)
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    order = await ticket_service.get_order(db, order_id)
    if not order:
        raise HTTPException(
            status_code=404,
            detail=f"Order '{order_id}' not found",
        )
    return order
