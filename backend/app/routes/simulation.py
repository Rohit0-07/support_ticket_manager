"""API router for the Live Ticket Simulation feature (FEAT-007).

Endpoints documented in ``features/F7-live-ticket-simulation/2_tech_spec.md`` §4.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.simulation_models import (
    SimulationStatusResponse,
    StartSimulationRequest,
)
from app.services import simulation_service
from app.services.simulation_engine import (
    SimulationAlreadyRunningError,
    SimulationPaceInvalidError,
    SimulationPipelineUnavailableError,
    SimulationQueueEmptyError,
    SimulationStateConflictError,
)

router = APIRouter(prefix="/api/v1", tags=["simulation"])


@router.post("/simulation/start", response_model=SimulationStatusResponse)
async def start_simulation_endpoint(
    payload: StartSimulationRequest,
    db: AsyncSession = Depends(get_db),
) -> SimulationStatusResponse:
    """Start a live ticket simulation run (US-01, US-02 S1)."""
    try:
        return await simulation_service.start_simulation(db, payload.pace_seconds)
    except SimulationQueueEmptyError as exc:
        # EC-06: informational 200 with queue_empty=true and last-run counts.
        return exc.status
    except SimulationAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SimulationStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SimulationPaceInvalidError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SimulationPipelineUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/simulation/pause", response_model=SimulationStatusResponse)
async def pause_simulation_endpoint() -> SimulationStatusResponse:
    """Pause an actively running simulation (US-02 S2)."""
    try:
        return await simulation_service.pause_simulation()
    except SimulationStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/simulation/resume", response_model=SimulationStatusResponse)
async def resume_simulation_endpoint() -> SimulationStatusResponse:
    """Resume a paused simulation from where it left off (US-02 S2)."""
    try:
        return await simulation_service.resume_simulation()
    except SimulationStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/simulation/stop", response_model=SimulationStatusResponse)
async def stop_simulation_endpoint() -> SimulationStatusResponse:
    """Stop a running or paused simulation early (US-02 S3)."""
    try:
        return await simulation_service.stop_simulation()
    except SimulationStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/simulation/status", response_model=SimulationStatusResponse)
async def get_simulation_status_endpoint() -> SimulationStatusResponse:
    """Return the current simulation snapshot (US-03 S1/S2, EC-04)."""
    try:
        return await simulation_service.get_simulation_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Simulation failed: {exc}") from exc
