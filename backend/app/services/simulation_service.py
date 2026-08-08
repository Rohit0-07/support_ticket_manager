"""Lifecycle facade for the Live Ticket Simulation feature (FEAT-007).

Contracts documented in ``features/F7-live-ticket-simulation/2_tech_spec.md``
§2.2 (service facade), §1.2 (runtime model) and §5 (error mapping).
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.database import init_db
from app.models.db_models import NewTicket, ResolutionDecisionLog
from app.models.dashboard_models import DashboardLane
from app.models.simulation_models import (
    PaceValidationResult,
    ProcessedTicketEntry,
    SimulationCommand,
    SimulationState,
    SimulationStatusResponse,
    SimulationWarning,
)
from app.services.simulation_engine import (
    SimulationPipelineUnavailableError,
    SimulationQueueEmptyError,
    SimulationUnreadableTicketError,
    compute_lane_counts,
    validate_pace,
    validate_state_transition,
)
from app.services.simulation_manager import (
    SimulationManager,
    _finalize_summary,
    default_manager,
)


def _now_iso() -> str:
    """ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _db_factory_from(db: AsyncSession):
    """Build a session factory bound to the same engine as ``db``.

    The background tick loop needs fresh sessions (one per ticket step) while
    reusing the caller's engine — including test engines injected via
    ``get_db`` overrides.
    """
    engine = db.bind
    return async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )


def _mark_completed(manager: SimulationManager) -> None:
    """Transition a RUNNING manager to COMPLETED (US-03 S2)."""
    manager.state = SimulationState.COMPLETED
    manager.completed_at = _now_iso()
    manager.message = "Simulation finished"
    manager.last_run_summary = _finalize_summary(manager, "completed")


def _build_status(manager: SimulationManager) -> SimulationStatusResponse:
    """Snapshot the manager's live state into a ``SimulationStatusResponse``."""
    counts = compute_lane_counts(manager.processed)
    remaining = max(0, len(manager.queue) - manager.next_index)

    recently_landed = [
        entry.ticket_id for entry in manager.processed[manager._last_reported_count:]
    ]
    manager._last_reported_count = len(manager.processed)

    message = manager.message
    if message is None and manager.state == SimulationState.COMPLETED:
        message = "Simulation finished"

    return SimulationStatusResponse(
        state=manager.state,
        session_id=manager.session_id,
        run_id=manager.run_id,
        running=manager.state == SimulationState.RUNNING,
        paused=manager.state == SimulationState.PAUSED,
        started=manager.state != SimulationState.IDLE,
        queue_total=len(manager.queue),
        processed_count=len(manager.processed),
        skipped_count=len(manager.skipped),
        remaining_count=remaining,
        auto_resolved_count=counts.auto_resolved,
        needs_review_count=counts.needs_review,
        lane_counts=counts,
        pace_seconds=manager.pace_seconds,
        pace_adjusted=manager.pace_adjusted,
        pace_adjusted_note=manager.pace_adjusted_note,
        queue_empty=len(manager.queue) == 0,
        last_landed_ticket_id=(
            manager.processed[-1].ticket_id if manager.processed else None
        ),
        recently_landed_ticket_ids=recently_landed,
        warnings=list(manager.skipped),
        error=manager.error,
        message=message,
        completed_at=manager.completed_at,
        last_run_summary=manager.last_run_summary,
    )


async def start_simulation(
    db: AsyncSession,
    pace_seconds: Optional[float] = None,
    manager: Optional[SimulationManager] = None,
) -> SimulationStatusResponse:
    """Start a new live simulation run (US-01, US-02 S1, EC-01/05/06).

    Snapshots the queue (all ``new_tickets`` without a ``decision_log`` row,
    ordered by ``ticket_id`` ASC), validates the pace, launches the
    background tick task, and returns the initial status with
    ``started: true``.

    Args:
        db: Async DB session used to build the queue snapshot.
        pace_seconds: Requested delay between arrivals; None → default pace.
        manager: The simulation runtime; defaults to the shared singleton.

    Returns:
        ``SimulationStatusResponse`` with ``state=RUNNING`` and the queue
        totals.

    Raises:
        SimulationAlreadyRunningError: If a run is already active (EC-01).
        SimulationPaceInvalidError: If pace is non-finite (EC-05).
        SimulationQueueEmptyError: If no unprocessed tickets remain (EC-06);
            carries the final-count status on ``status``.
        SimulationPipelineUnavailableError: If the queue cannot be built (EC-03).
    """
    from app.services.simulation_engine import (
        SimulationAlreadyRunningError,
        SimulationPaceInvalidError,
    )

    manager = manager or default_manager()

    if manager.state in (SimulationState.RUNNING, SimulationState.PAUSED):
        raise SimulationAlreadyRunningError("a simulation is already in progress")

    if pace_seconds is None:
        pace_result = PaceValidationResult(
            pace_seconds=float(settings.SIMULATION_DEFAULT_PACE_SECONDS),
            adjusted=False,
            note=None,
        )
    else:
        pace_result = validate_pace(pace_seconds)

    # Queue snapshot: new_tickets with no decision_log row, ticket_id ASC.
    try:
        await init_db()
        stmt = (
            select(NewTicket.ticket_id)
            .outerjoin(
                ResolutionDecisionLog,
                ResolutionDecisionLog.ticket_id == NewTicket.ticket_id,
            )
            .where(ResolutionDecisionLog.ticket_id.is_(None))
            .order_by(NewTicket.ticket_id.asc())
        )
        result = await db.execute(stmt)
        queue = [row[0] for row in result.all()]
    except Exception as exc:
        raise SimulationPipelineUnavailableError(
            f"Simulation pipeline unavailable: {exc}"
        ) from exc

    if not queue:
        manager.message = "No tickets left to simulate"
        status = _build_status(manager)
        raise SimulationQueueEmptyError(status, "No tickets left to simulate")

    # Initialize the run.
    manager.state = SimulationState.RUNNING
    manager.session_id = str(uuid4())
    manager.run_id = str(uuid4())
    manager.queue = queue
    manager.next_index = 0
    manager.processed = []
    manager.skipped = []
    manager.pace_seconds = pace_result.pace_seconds
    manager.pace_adjusted = pace_result.adjusted
    manager.pace_adjusted_note = pace_result.note
    manager.started_at = _now_iso()
    manager.completed_at = None
    manager.message = None
    manager.error = None
    manager._stop_requested = False
    manager._resume_event.set()
    manager._last_reported_count = 0

    # Launch the background tick loop on the same engine as the caller.
    manager.task = asyncio.create_task(manager.tick_loop(_db_factory_from(db)))

    return _build_status(manager)


async def pause_simulation(
    manager: Optional[SimulationManager] = None,
) -> SimulationStatusResponse:
    """Pause an actively running simulation (US-02 S2).

    Stops further ticket processing at the next tick boundary; progress is
    held unchanged.

    Args:
        manager: The simulation runtime; defaults to the shared singleton.

    Returns:
        ``SimulationStatusResponse`` with ``state=PAUSED``.

    Raises:
        SimulationStateConflictError: If no run is RUNNING (→ 409).
    """
    manager = manager or default_manager()
    manager.state = validate_state_transition(manager.state, SimulationCommand.PAUSE)
    manager._resume_event.clear()
    return _build_status(manager)


async def resume_simulation(
    manager: Optional[SimulationManager] = None,
) -> SimulationStatusResponse:
    """Resume a paused simulation from where it left off (US-02 S2).

    Args:
        manager: The simulation runtime; defaults to the shared singleton.

    Returns:
        ``SimulationStatusResponse`` with ``state=RUNNING``.

    Raises:
        SimulationStateConflictError: If no run is PAUSED (→ 409).
    """
    manager = manager or default_manager()
    manager.state = validate_state_transition(manager.state, SimulationCommand.RESUME)
    manager._resume_event.set()
    return _build_status(manager)


async def stop_simulation(
    manager: Optional[SimulationManager] = None,
) -> SimulationStatusResponse:
    """Stop a running or paused simulation early (US-02 S3).

    Halts at the next tick boundary. Remaining tickets stay unprocessed.
    The run is finalized into ``last_run_summary`` (``ended_by="stopped"``)
    and the state returns to IDLE so the viewer can start again.

    Args:
        manager: The simulation runtime; defaults to the shared singleton.

    Returns:
        ``SimulationStatusResponse`` with ``state=IDLE`` and
        ``last_run_summary`` populated.

    Raises:
        SimulationStateConflictError: If no run is RUNNING/PAUSED (→ 409).
    """
    manager = manager or default_manager()
    manager.state = validate_state_transition(manager.state, SimulationCommand.STOP)
    manager._stop_requested = True
    manager._resume_event.set()
    manager.last_run_summary = _finalize_summary(manager, "stopped")
    return _build_status(manager)


async def get_simulation_status(
    manager: Optional[SimulationManager] = None,
) -> SimulationStatusResponse:
    """Return the current simulation snapshot (US-03 S1/S2).

    Args:
        manager: The simulation runtime; defaults to the shared singleton.

    Returns:
        ``SimulationStatusResponse`` reflecting the live run state; always
        succeeds even when idle (EC-06 final counts included).
    """
    manager = manager or default_manager()
    return _build_status(manager)


async def advance_simulation(
    db: AsyncSession,
    manager: Optional[SimulationManager] = None,
) -> SimulationStatusResponse:
    """Advance the active run by exactly one queue item (test hook).

    Processes the next queued ticket through the F2→F3→F4 pipeline, records
    its lane, updates progress, and returns the updated status. Does **not**
    sleep — the background loop owns pacing. Used by the tick loop and by
    tests for deterministic single-step runs. No-op (returns current status)
    when not RUNNING or when the queue is exhausted.

    Args:
        db: Async DB session for the current step.
        manager: The simulation runtime; defaults to the shared singleton.

    Returns:
        Updated ``SimulationStatusResponse``.

    Raises:
        SimulationPipelineUnavailableError: On unrecoverable pipeline failure;
            the caller (loop) auto-pauses per EC-03.
    """
    manager = manager or default_manager()

    if manager.state != SimulationState.RUNNING:
        return _build_status(manager)

    if manager.next_index >= len(manager.queue):
        _mark_completed(manager)
        return _build_status(manager)

    ticket_id = manager.queue[manager.next_index]
    manager.next_index += 1

    try:
        entry = await _process_ticket(db, ticket_id)
    except SimulationUnreadableTicketError as exc:
        manager.skipped.append(
            SimulationWarning(
                ticket_id=ticket_id,
                code="unreadable_description",
                message=str(exc) or "Ticket description could not be read.",
            )
        )
        if manager.next_index >= len(manager.queue):
            _mark_completed(manager)
        return _build_status(manager)

    manager.processed.append(entry)
    if manager.next_index >= len(manager.queue):
        _mark_completed(manager)
    return _build_status(manager)


async def _process_ticket(
    db: AsyncSession, ticket_id: str
) -> ProcessedTicketEntry:
    """Internal: run one ticket through the F2→F3→F4 pipeline.

    Delegates to ``resolution_service.resolve_ticket`` (which persists the
    ``decision_log`` row and triggers F4 reply drafting), then derives the
    landed lane from the decision's ``auto_resolved`` flag (BR-02).

    Args:
        db: Async DB session.
        ticket_id: F1 ``new_tickets.ticket_id``.

    Returns:
        ``ProcessedTicketEntry`` with ticket id, lane, auto_resolved flag,
        confidence, and processing timestamp.

    Raises:
        SimulationUnreadableTicketError: If the ticket description is blank
            or unparseable (EC-02).
        SimulationPipelineUnavailableError: On any pipeline/db failure that
            prevents processing (EC-03).
    """
    # EC-02: a queued ticket whose description cannot be read is skipped.
    try:
        stmt = select(NewTicket.description).where(NewTicket.ticket_id == ticket_id)
        desc_row = (await db.execute(stmt)).first()
    except Exception as exc:
        raise SimulationPipelineUnavailableError(
            f"Simulation pipeline unavailable: {exc}"
        ) from exc

    if desc_row is None:
        raise SimulationUnreadableTicketError(
            f"ticket {ticket_id} is no longer available"
        )
    description = desc_row[0]
    if not description or not description.strip():
        raise SimulationUnreadableTicketError(
            f"ticket {ticket_id} has an unreadable description"
        )

    from app.services.resolution_service import resolve_ticket

    try:
        decision = await resolve_ticket(db, ticket_id)
    except Exception as exc:
        raise SimulationPipelineUnavailableError(
            f"Simulation pipeline unavailable: {exc}"
        ) from exc

    lane = (
        DashboardLane.AUTO_RESOLVED
        if decision.auto_resolved
        else DashboardLane.NEEDS_REVIEW
    )
    return ProcessedTicketEntry(
        ticket_id=ticket_id,
        lane=lane,
        auto_resolved=decision.auto_resolved,
        confidence=decision.confidence,
        processed_at=_now_iso(),
    )


def reset_simulation_manager() -> None:
    """Reset the singleton runtime to IDLE and cancel its background task.

    Test-isolation helper: guarantees a clean slate between test cases.
    """
    manager = default_manager()
    if manager.task is not None:
        try:
            manager.task.cancel()
        except Exception:
            pass
        manager.task = None
    manager.state = SimulationState.IDLE
    manager.session_id = None
    manager.run_id = None
    manager.queue = []
    manager.next_index = 0
    manager.processed = []
    manager.skipped = []
    manager.pace_seconds = None
    manager.pace_adjusted = False
    manager.pace_adjusted_note = None
    manager.started_at = None
    manager.completed_at = None
    manager.message = None
    manager.error = None
    manager.last_run_summary = None
    manager._stop_requested = False
    manager._resume_event.set()
    manager._last_reported_count = 0
