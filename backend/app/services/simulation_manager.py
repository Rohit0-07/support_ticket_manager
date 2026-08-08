"""In-memory single-flight runtime for the Live Ticket Simulation (FEAT-007).

Holds all mutable state of the one active simulation run and runs the
background tick loop. Contracts documented in
``features/F7-live-ticket-simulation/2_tech_spec.md`` §1.2 / §2.3.
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from app.models.simulation_models import (
    ProcessedTicketEntry,
    SimulationErrorInfo,
    SimulationRunSummary,
    SimulationState,
    SimulationStatusResponse,
    SimulationWarning,
)


def _now_iso() -> str:
    """ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _finalize_summary(manager: "SimulationManager", ended_by: str) -> SimulationRunSummary:
    """Build the final-count summary for a finished/stopped/paused run."""
    auto_resolved = sum(1 for e in manager.processed if e.auto_resolved)
    needs_review = len(manager.processed) - auto_resolved
    return SimulationRunSummary(
        run_id=manager.run_id or "",
        started_at=manager.started_at or _now_iso(),
        ended_at=_now_iso(),
        total_queued=len(manager.queue),
        processed_count=len(manager.processed),
        skipped_count=len(manager.skipped),
        auto_resolved_count=auto_resolved,
        needs_review_count=needs_review,
        ended_by=ended_by,
    )


class SimulationManager:
    """Holds all mutable state of the one active simulation run.

    Public surface used by the service facade:
      - ``state: SimulationState``
      - ``session_id: Optional[str]``  (UUID assigned per run — EC-04)
      - ``queue: List[str]``           (ticket ids, snapshot at start)
      - ``next_index: int``
      - ``processed: List[ProcessedTicketEntry]``
      - ``skipped: List[SimulationWarning]``
      - ``pace_seconds: Optional[float]``
      - ``started_at`` / ``completed_at: Optional[str]``
      - ``last_run_summary: Optional[SimulationRunSummary]``
      - ``task: Optional[asyncio.Task]``

    Concurrency: guarded by an ``asyncio.Lock``; the background tick loop
    checks ``_stop_requested`` and awaits ``_resume_event`` between tickets so
    pause/stop are honored at tick boundaries (never mid-ticket).
    """

    def __init__(self) -> None:
        self.state: SimulationState = SimulationState.IDLE
        self.session_id: Optional[str] = None
        self.run_id: Optional[str] = None
        self.queue: List[str] = []
        self.next_index: int = 0
        self.processed: List[ProcessedTicketEntry] = []
        self.skipped: List[SimulationWarning] = []
        self.pace_seconds: Optional[float] = None
        self.pace_adjusted: bool = False
        self.pace_adjusted_note: Optional[str] = None
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.message: Optional[str] = None
        self.error: Optional[SimulationErrorInfo] = None
        self.last_run_summary: Optional[SimulationRunSummary] = None
        self.task: Optional[asyncio.Task] = None

        # Internal control flags honored at tick boundaries.
        self._stop_requested: bool = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()
        self._last_reported_count: int = 0

    async def tick_loop(self, db_factory) -> None:
        """Background loop: for each queued ticket, await the pace, process,
        record the landed lane, and update progress. Honors pause (holds on
        ``_resume_event``) and stop (exits early). On queue exhaustion sets
        state=COMPLETED (US-03 S2); on ``SimulationPipelineUnavailableError``
        auto-pauses and records the retryable error (EC-03)."""
        # Lazy import to avoid a module-level cycle: the service facade imports
        # this manager, while the loop needs the facade's advance_simulation.
        from app.services.simulation_engine import SimulationPipelineUnavailableError
        from app.services.simulation_service import advance_simulation

        try:
            while not self._stop_requested:
                await self._resume_event.wait()
                if self._stop_requested:
                    break
                if self.next_index >= len(self.queue):
                    break

                pace = self.pace_seconds if self.pace_seconds is not None else 0.05
                await asyncio.sleep(pace)
                if self._stop_requested:
                    break
                if self.next_index >= len(self.queue):
                    break

                try:
                    async with db_factory() as db:
                        await advance_simulation(db, manager=self)
                except SimulationPipelineUnavailableError as exc:
                    self.state = SimulationState.PAUSED
                    self.error = SimulationErrorInfo(
                        code="pipeline_unavailable",
                        message=str(exc),
                        retryable=True,
                    )
                    break
                except Exception as exc:  # pragma: no cover - defensive
                    self.state = SimulationState.PAUSED
                    self.error = SimulationErrorInfo(
                        code="simulation_failed",
                        message=f"Simulation failed: {exc}",
                        retryable=False,
                    )
                    break
        except asyncio.CancelledError:
            pass


_default_manager_instance: Optional[SimulationManager] = None


def default_manager() -> SimulationManager:
    """Return the module-level singleton manager instance."""
    global _default_manager_instance
    if _default_manager_instance is None:
        _default_manager_instance = SimulationManager()
    return _default_manager_instance
