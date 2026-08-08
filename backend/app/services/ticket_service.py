from typing import Optional, Tuple, List
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import ResolvedTicket, NewTicket, OrderContext


async def list_resolved_tickets(
    db: AsyncSession, skip: int = 0, limit: int = 50
) -> Tuple[List[ResolvedTicket], int]:
    """Returns (items, total_count) for resolved tickets with pagination."""
    count_stmt = select(func.count()).select_from(ResolvedTicket)
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = select(ResolvedTicket).offset(skip).limit(limit)
    result = await db.execute(stmt)
    items = list(result.scalars().all())
    return items, total


async def get_resolved_ticket(db: AsyncSession, ticket_id: str) -> Optional[ResolvedTicket]:
    """Returns a single resolved ticket by ID, or None if not found."""
    return await db.get(ResolvedTicket, ticket_id)


async def list_new_tickets(
    db: AsyncSession, skip: int = 0, limit: int = 50
) -> Tuple[List[NewTicket], int]:
    """Returns (items, total_count) for new tickets with pagination."""
    count_stmt = select(func.count()).select_from(NewTicket)
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = select(NewTicket).offset(skip).limit(limit)
    result = await db.execute(stmt)
    items = list(result.scalars().all())
    return items, total


async def get_new_ticket(db: AsyncSession, ticket_id: str) -> Optional[NewTicket]:
    """Returns a single new ticket by ID, or None if not found."""
    return await db.get(NewTicket, ticket_id)


async def list_orders(
    db: AsyncSession, skip: int = 0, limit: int = 50
) -> Tuple[List[OrderContext], int]:
    """Returns (items, total_count) for orders with pagination."""
    count_stmt = select(func.count()).select_from(OrderContext)
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = select(OrderContext).offset(skip).limit(limit)
    result = await db.execute(stmt)
    items = list(result.scalars().all())
    return items, total


async def get_order(db: AsyncSession, order_id: str) -> Optional[OrderContext]:
    """Returns a single order by ID, or None if not found."""
    return await db.get(OrderContext, order_id)
