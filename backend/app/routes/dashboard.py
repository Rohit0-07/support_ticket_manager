"""API router for the Two-Lane Dashboard feature (FEAT-005).

Endpoints documented in ``features/F5-two-lane-dashboard/2_tech_spec.md`` §2.4 / §4.
F5 exposes GET-only endpoints (BR-05) and never mutates state.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.dashboard_models import DashboardBoard, DashboardTicketDetail
from app.services import dashboard_service
from app.services.dashboard_service import (
    DashboardDataUnavailableError,
    DashboardError,
)

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardBoard)
async def dashboard_board_endpoint(
    db: AsyncSession = Depends(get_db),
) -> DashboardBoard:
    """Return the full two-lane board (US-01, US-04).

    Raises:
        HTTPException(500): On DashboardDataUnavailableError (EC-06).
    """
    try:
        return await dashboard_service.build_board(db)
    except DashboardDataUnavailableError as exc:
        raise HTTPException(status_code=500, detail=f"Dashboard data unavailable: {exc}") from exc
    except DashboardError as exc:
        raise HTTPException(status_code=500, detail=f"Dashboard failed: {exc}") from exc


@router.get("/dashboard/tickets/{ticket_id}", response_model=DashboardTicketDetail)
async def dashboard_ticket_detail_endpoint(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
) -> DashboardTicketDetail:
    """Return full read-only detail for one ticket (US-03).

    Raises:
        HTTPException(404): When no decision record exists for ticket_id.
        HTTPException(500): On DashboardDataUnavailableError (EC-06).
    """
    try:
        detail = await dashboard_service.build_ticket_detail(db, ticket_id)
    except DashboardDataUnavailableError as exc:
        raise HTTPException(status_code=500, detail=f"Dashboard data unavailable: {exc}") from exc
    except DashboardError as exc:
        raise HTTPException(status_code=500, detail=f"Dashboard failed: {exc}") from exc
    if detail is None:
        raise HTTPException(status_code=404, detail=f"no decision record for ticket {ticket_id}")
    return detail
