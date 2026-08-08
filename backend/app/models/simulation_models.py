"""Pydantic contracts for the Live Ticket Simulation feature (FEAT-007).

These models are the API/engine contracts documented in
``features/F7-live-ticket-simulation/2_tech_spec.md`` §3. F7 introduces no
new database tables (BR-04); all models are request/response/state DTOs.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.dashboard_models import DashboardLane


class SimulationState(str, Enum):
    """Lifecycle state of the (single) simulation run."""

    IDLE = "idle"          # no run active; ready to start
    RUNNING = "running"    # actively processing tickets
    PAUSED = "paused"      # temporarily halted; resumable
    COMPLETED = "completed"  # all queued tickets processed (US-03 S2)


class SimulationCommand(str, Enum):
    """Lifecycle commands consumed by validate_state_transition()."""

    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    COMPLETE = "complete"   # internal: queue exhausted
    FAILED = "failed"       # internal: EC-03 pipeline failure


class PaceValidationResult(BaseModel):
    """Canonical pace after clamping (EC-05)."""

    pace_seconds: float = Field(..., gt=0, description="Canonical delay in seconds.")
    adjusted: bool = Field(..., description="True when the requested value was clamped.")
    note: Optional[str] = Field(None, description="Brief note shown to the viewer when adjusted.")


class LaneCounts(BaseModel):
    """Per-lane landed counts for progress reporting (US-03 S1)."""

    auto_resolved: int = Field(..., ge=0, description="Tickets landed in Auto-Resolved lane.")
    needs_review: int = Field(..., ge=0, description="Tickets landed in Needs Human Review lane.")


class SimulationWarning(BaseModel):
    """One recoverable event surfaced in the progress area (EC-02)."""

    ticket_id: str = Field(..., description="Skipped ticket id.")
    code: str = Field(..., description="Warning code, e.g. 'unreadable_description'.")
    message: str = Field(..., description="Human-readable warning.")


class SimulationErrorInfo(BaseModel):
    """Error detail surfaced when the run auto-pauses (EC-03)."""

    code: str = Field(..., description="Machine code, e.g. 'pipeline_unavailable'.")
    message: str = Field(..., description="Human-readable error message.")
    retryable: bool = Field(..., description="True when Resume/Retry is allowed.")


class ProcessedTicketEntry(BaseModel):
    """Internal record of one landed ticket (used by compute_lane_counts)."""

    ticket_id: str = Field(..., description="F1 new_tickets.ticket_id.")
    lane: DashboardLane = Field(..., description="Lane assigned by the pipeline outcome (BR-02).")
    auto_resolved: bool = Field(..., description="True iff auto-resolved.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Persisted decision confidence.")
    processed_at: str = Field(..., description="ISO-8601 UTC processing timestamp.")


class SimulationRunSummary(BaseModel):
    """Final counts for a finished/stopped run (EC-06, US-02 S3)."""

    run_id: str = Field(..., description="UUID of the run.")
    started_at: str = Field(..., description="ISO-8601 UTC start time.")
    ended_at: Optional[str] = Field(None, description="ISO-8601 UTC end time; null while active.")
    total_queued: int = Field(..., ge=0, description="Queue size at start.")
    processed_count: int = Field(..., ge=0, description="Tickets landed in a lane.")
    skipped_count: int = Field(..., ge=0, description="Tickets skipped (EC-02).")
    auto_resolved_count: int = Field(..., ge=0, description="Landed in Auto-Resolved.")
    needs_review_count: int = Field(..., ge=0, description="Landed in Needs Human Review.")
    ended_by: str = Field(..., description="'completed' | 'stopped' | 'paused_with_error'.")


class StartSimulationRequest(BaseModel):
    """Request body for POST /api/v1/simulation/start (US-02 S1)."""

    pace_seconds: Optional[float] = Field(
        None,
        gt=0,
        description="Delay between arrivals in seconds. Omitted → default pace. "
                    "Values below the configured minimum are clamped up (EC-05).",
    )


class SimulationStatusResponse(BaseModel):
    """Full simulation snapshot returned by all simulation endpoints (US-03)."""

    state: SimulationState = Field(..., description="Current lifecycle state.")
    session_id: Optional[str] = Field(None, description="Per-run UUID for EC-04 session matching.")
    run_id: Optional[str] = Field(None, description="UUID of the active/last run.")
    running: bool = Field(..., description="True iff state == RUNNING.")
    paused: bool = Field(..., description="True iff state == PAUSED.")
    started: bool = Field(..., description="True iff the start request launched a run.")
    queue_total: int = Field(..., ge=0, description="Queue size at start (0 → EC-06).")
    processed_count: int = Field(..., ge=0, description="Tickets landed in a lane so far.")
    skipped_count: int = Field(..., ge=0, description="Tickets skipped so far (EC-02).")
    remaining_count: int = Field(..., ge=0, description="Tickets not yet attempted.")
    auto_resolved_count: int = Field(..., ge=0, description="Landed in Auto-Resolved.")
    needs_review_count: int = Field(..., ge=0, description="Landed in Needs Human Review.")
    lane_counts: LaneCounts = Field(..., description="Per-lane counts for badges (US-03 S1).")
    pace_seconds: Optional[float] = Field(None, description="Canonical pace of the active run.")
    pace_adjusted: bool = Field(default=False, description="True when the pace was clamped (EC-05).")
    pace_adjusted_note: Optional[str] = Field(None, description="Note accompanying a clamp (EC-05).")
    queue_empty: bool = Field(..., description="True when no unprocessed tickets remain (EC-06).")
    last_landed_ticket_id: Optional[str] = Field(None, description="Most recently landed ticket id.")
    recently_landed_ticket_ids: List[str] = Field(
        default_factory=list,
        description="Ids landed since the previous status snapshot (frontend animation trigger).",
    )
    warnings: List[SimulationWarning] = Field(default_factory=list, description="EC-02 skip warnings.")
    error: Optional[SimulationErrorInfo] = Field(None, description="EC-03 error detail when auto-paused.")
    message: Optional[str] = Field(None, description="Viewer-facing notice (e.g. EC-06 / completion).")
    completed_at: Optional[str] = Field(None, description="ISO-8601 UTC completion time (US-03 S2).")
    last_run_summary: Optional[SimulationRunSummary] = Field(
        None, description="Final counts of the previous run (EC-06, US-02 S3)."
    )
