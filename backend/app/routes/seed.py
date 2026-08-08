from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.models.db_models import ResolvedTicket, NewTicket, OrderContext
from app.models.ticket_models import SeedResponse, HealthResponse
from app.services.ingestion_service import seed_all

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.post("/seed", response_model=SeedResponse)
async def seed_data(
    db: AsyncSession = Depends(get_db),
):
    results = await seed_all(settings.CSV_DIR, db=db)
    resolved_res = results.get("resolved_tickets")
    new_res = results.get("new_tickets")
    orders_res = results.get("orders") or results.get("orders_context")

    warnings = []
    if resolved_res:
        warnings.extend(resolved_res.warnings)
    if new_res:
        warnings.extend(new_res.warnings)
    if orders_res:
        warnings.extend(orders_res.warnings)

    return SeedResponse(
        resolved_tickets_loaded=resolved_res.rows_loaded if resolved_res else 0,
        new_tickets_loaded=new_res.rows_loaded if new_res else 0,
        orders_loaded=orders_res.rows_loaded if orders_res else 0,
        warnings=warnings,
    )


@router.get("/health", response_model=HealthResponse)
async def health_check(
    db: AsyncSession = Depends(get_db),
):
    res_count = (await db.execute(select(func.count()).select_from(ResolvedTicket))).scalar_one()
    new_count = (await db.execute(select(func.count()).select_from(NewTicket))).scalar_one()
    orders_count = (await db.execute(select(func.count()).select_from(OrderContext))).scalar_one()

    return HealthResponse(
        status="ok",
        resolved_tickets_count=res_count,
        new_tickets_count=new_count,
        orders_count=orders_count,
    )
