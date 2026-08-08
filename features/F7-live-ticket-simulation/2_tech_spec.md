# Technical Specification: Live Ticket Simulation (F7)

| Metadata | Details |
|---|---|
| **Feature Name** | Live Ticket Simulation |
| **Derived From** | `features/F7-live-ticket-simulation/1_spec.md` |
| **Status** | Draft |
| **Author** | Technical Architect (AI) |
| **Created Date** | 2026-08-08 |

---

## 1. System Architecture & Components

### 1.1 Component Overview

F7 adds a **server-side, single-instance, in-memory simulation runtime** plus a thin REST control surface and a frontend control bar. The simulation reuses the existing F2 → F3 → F4 processing pipeline and the F5 two-lane dashboard **verbatim** — it introduces **no new processing behavior, no new database tables, and no persistence** of its own. Tickets processed by the simulation are persisted exactly as if they had been processed outside the simulation (F3 `decision_log` + F4 `reply_log` rows), which is what makes them appear on the F5 board (BR-05).

```
┌─────────────────────────────────────────────────────────────────────┐
│ Frontend (frontend/app.js + index.html + style.css)                  │
│   Simulation Control Bar: pace select, Start/Pause/Resume/Stop,      │
│   progress indicator, warnings area, error banner                    │
│   Polls GET /api/v1/simulation/status every SIM_POLL_INTERVAL_MS     │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTP JSON
┌───────────────────────────────▼─────────────────────────────────────┐
│ Backend                                                              │
│  app/routes/simulation.py            REST control surface (F7 §4)   │
│  app/services/simulation_service.py  Facade: lifecycle + tick loop  │
│  app/services/simulation_manager.py  Singleton runtime (one run)     │
│  app/services/simulation_engine.py   Pure rules: pace, transitions, │
│                                       lane counts, session mismatch │
│  app/models/simulation_models.py     Pydantic contracts (F7 §3)     │
│  app/core/config.py                  STM_SIMULATION_* settings      │
└──────────────┬──────────────────────────────────────────────────────┘
               │ calls existing pipeline (read-only reuse)
┌──────────────▼──────────────────────────────────────────────────────┐
│ Existing pipeline (F2/F3/F4) and dashboard (F5)                     │
│  similarity_service.find_similar → resolution_service.resolve_ticket│
│  → reply drafting (F4) → decision_log/reply_log rows                │
│  GET /api/v1/dashboard (F5) reads decision_log for the live board   │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 Runtime Model (Key Design Decision)

- **Single-flight run (BR-03)**: Exactly one simulation may be active. All lifecycle state lives in a module-level `SimulationManager` singleton so it survives individual HTTP requests. A background `asyncio.Task` runs the tick loop.
- **Queue snapshot at start**: The queue is the set of `new_tickets` (F1) rows that have **no** `decision_log` row yet (i.e., not already processed). This makes EC-06 natural: after a completed run every queued ticket has a decision row, so the next `start` yields an empty queue.
- **Ticks are pipeline invocations**: Each tick calls the existing `resolution_service.resolve_ticket(db, ticket_id)` (which internally runs F2 similarity → F3 decision → persists `decision_log`, and F4 reply drafting), then records the landed lane. BR-02 is preserved: lanes come only from the processing outcome.
- **Pause/stop responsiveness**: The loop sleeps in sub-second increments between tickets and checks pause/stop flags so `pause`/`stop` take effect within one poll interval, never mid-ticket.
- **Page refresh (EC-04)**: `session_id` is assigned per run. The frontend remembers the `session_id` it started; on load it compares against `GET /status`. A mismatch (or a fresh page seeing an active run) triggers the "previous simulation cannot be resumed" notice and offers Start New (stop + start).

### 1.3 Lifecycle State Machine

```
         START (queue non-empty)          COMPLETE (internal)
  IDLE ───────────────────────────► RUNNING ───────────────────► COMPLETED
   ▲                                │   │                          │
   │           STOP                 │   │  PAUSE                   │ START (queue empty:
   │      (early stop, ready)       │   │                          │ EC-06 → 200, no run)
   └────────────────────────────────▼───▼                          │
                              ┌─────┴─────┐                        │
                              │  PAUSED   │◄───────────────────────┘
                              └─────┬─────┘
                                    │ RESUME
                                    └──────────────► RUNNING
   Pipeline failure mid-run (EC-03): RUNNING ───► PAUSED (error set, retryable)
```

Transitions enforced by the pure function `validate_state_transition` (§2.1). Invalid transitions raise `SimulationStateConflictError` (→ 409).

### 1.4 Configuration Additions (`backend/app/core/config.py`, env prefix `STM_`)

| Setting | Type | Default | Purpose |
|---|---|---|---|
| `SIMULATION_DEFAULT_PACE_SECONDS` | float | `3.0` | Pace used when `pace_seconds` omitted (US-02 S1). |
| `SIMULATION_MIN_PACE_SECONDS` | float | `1.0` | Floor for EC-05; any value below is clamped to this. |
| `SIMULATION_MAX_PACE_SECONDS` | float | `30.0` | Ceiling; any value above is clamped to this (sane demos). |

Tests may set `STM_SIMULATION_MIN_PACE_SECONDS=0.01` and `STM_SIMULATION_DEFAULT_PACE_SECONDS=0.05` in the environment for fast, deterministic API-level runs. For fully deterministic single-step testing use `advance_simulation` (§2.2).

### 1.5 Files Touched

| File | Change |
|---|---|
| `backend/app/models/simulation_models.py` | **New** — Pydantic contracts (§3). |
| `backend/app/services/simulation_engine.py` | **New** — pure rules (§2.1). |
| `backend/app/services/simulation_manager.py` | **New** — singleton runtime + background task. |
| `backend/app/services/simulation_service.py` | **New** — facade functions (§2.2). |
| `backend/app/routes/simulation.py` | **New** — REST router (§4). |
| `backend/app/main.py` | Add `simulation` router import + `app.include_router(simulation.router)`. |
| `backend/app/core/config.py` | Add `STM_SIMULATION_*` settings (§1.4). |
| `frontend/index.html` | Add Simulation Control Bar + progress/warnings/error DOM. |
| `frontend/app.js` | Add simulation functions (§2.3). |
| `frontend/style.css` | Add control bar, progress, warning, error banner, card-landing animation classes. |

---

## 2. Interface Definitions & Function Signatures

### 2.1 Pure Engine Functions — `backend/app/services/simulation_engine.py`

No I/O, no `AsyncSession`. Fully deterministic for black-box testing.

```python
"""Pure rules for the Live Ticket Simulation feature (FEAT-007)."""

from typing import Optional, Sequence

from app.models.simulation_models import (
    LaneCounts,
    PaceValidationResult,
    SimulationCommand,
    SimulationState,
    SimulationStatusResponse,
)
from app.models.dashboard_models import DashboardLane


class SimulationError(Exception):
    """Base class for all F7 simulation errors."""


class SimulationStateConflictError(SimulationError):
    """Raised when a command is invalid for the current state (→ 409)."""


class SimulationAlreadyRunningError(SimulationStateConflictError):
    """Raised by START when a run is already active (EC-01, → 409)."""


class SimulationPaceInvalidError(SimulationError):
    """Raised when pace_seconds is non-finite (NaN/±inf) (EC-05, → 422)."""


class SimulationQueueEmptyError(SimulationError):
    """Raised by start when no unprocessed tickets remain (EC-06).

    Carries a ready-to-send ``SimulationStatusResponse`` on ``status`` so the
    route can reply 200 with ``started: false``, ``queue_empty: true``, the
    final counts from the last run, and a human message.
    """

    def __init__(self, status: "SimulationStatusResponse", message: str) -> None:
        super().__init__(message)
        self.status = status


class SimulationUnreadableTicketError(SimulationError):
    """Internal: a queued ticket has a blank/unreadable description (EC-02).

    Never surfaces as an HTTP error. The tick loop catches it, records a
    SimulationWarning, increments ``skipped_count``, and continues.
    """


class SimulationPipelineUnavailableError(SimulationError):
    """Raised when the processing pipeline cannot load data (EC-03).

    At start time → 500. Mid-run the tick loop catches it, auto-pauses the
    run (state=PAUSED), and sets ``error`` with ``retryable: true``.
    """


def validate_pace(pace_seconds: float) -> PaceValidationResult:
    """Canonicalize the arrival delay between tickets (US-02 S1, EC-05).

    Non-finite input (NaN, ±inf) raises ``SimulationPaceInvalidError``.
    Values below ``SIMULATION_MIN_PACE_SECONDS`` are clamped up to the
    minimum; values above ``SIMULATION_MAX_PACE_SECONDS`` are clamped down to
    the maximum. A clamp sets ``adjusted=True`` and a brief note.

    Args:
        pace_seconds: Requested delay in seconds between arrivals.

    Returns:
        ``PaceValidationResult`` with the canonical pace, an ``adjusted``
        flag, and an explanatory note when a clamp occurred.

    Raises:
        SimulationPaceInvalidError: If ``pace_seconds`` is NaN or ±inf.
    """
    ...


def validate_state_transition(
    current: SimulationState, command: SimulationCommand
) -> SimulationState:
    """Compute the next state for a lifecycle command (US-02, BR-03).

    Valid transitions:
      IDLE/COMPLETED --START--> RUNNING
      RUNNING        --PAUSE--> PAUSED
      PAUSED         --RESUME--> RUNNING
      RUNNING/PAUSED --STOP--> IDLE
      RUNNING        --COMPLETE--> COMPLETED   (internal, queue exhausted)
      RUNNING        --FAILED--> PAUSED        (internal, EC-03)

    Args:
        current: The current ``SimulationState``.
        command: The lifecycle command being applied.

    Returns:
        The resulting ``SimulationState``.

    Raises:
        SimulationStateConflictError: If the transition is not allowed
            (includes START while RUNNING/PAUSED → EC-01).
    """
    ...


def compute_lane_counts(entries: Sequence["ProcessedTicketEntry"]) -> LaneCounts:
    """Count landed tickets per lane for progress reporting (US-03 S1).

    Args:
        entries: The run's processed-ticket records so far.

    Returns:
        ``LaneCounts`` with ``auto_resolved`` and ``needs_review`` totals.

    Raises:
        SimulationError: If any entry lacks a valid lane (defensive).
    """
    ...


def detect_session_mismatch(
    status: SimulationStatusResponse, known_session_id: Optional[str]
) -> bool:
    """Detect the EC-04 page-refresh condition.

    True when the server has an active run (RUNNING or PAUSED) whose
    ``session_id`` differs from the ``session_id`` the current page believes
    it started (or when the page has no remembered session but a run is
    active).

    Args:
        status: The current ``SimulationStatusResponse`` from the server.
        known_session_id: The session_id the page recorded at start, or None
            on a fresh page load.

    Returns:
        True iff the active run cannot be resumed by this page.
    """
    ...
```

### 2.2 Service Facade — `backend/app/services/simulation_service.py`

```python
"""Lifecycle facade for the Live Ticket Simulation feature (FEAT-007)."""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.simulation_models import (
    ProcessedTicketEntry,
    SimulationStatusResponse,
    StartSimulationRequest,
)
from app.services.simulation_manager import SimulationManager, default_manager


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
    ...


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
    ...


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
    ...


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
    ...


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
    ...


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
    ...


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
    ...


def reset_simulation_manager() -> None:
    """Reset the singleton runtime to IDLE and cancel its background task.

    Test-isolation helper: guarantees a clean slate between test cases.
    """
    ...
```

### 2.3 Simulation Manager — `backend/app/services/simulation_manager.py`

```python
"""In-memory single-flight runtime for the Live Ticket Simulation (FEAT-007)."""

import asyncio
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.simulation_models import (
    ProcessedTicketEntry,
    SimulationRunSummary,
    SimulationState,
    SimulationStatusResponse,
    SimulationWarning,
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

    async def tick_loop(self, db_factory) -> None:
        """Background loop: for each queued ticket, await the pace, process,
        record the landed lane, and update progress. Honors pause (holds on
        ``_resume_event``) and stop (exits early). On queue exhaustion sets
        state=COMPLETED (US-03 S2); on ``SimulationPipelineUnavailableError``
        auto-pauses and records the retryable error (EC-03)."""
        ...


def default_manager() -> SimulationManager:
    """Return the module-level singleton manager instance."""
    ...
```

### 2.4 Frontend Functions — `frontend/app.js`

Reuses F5 globals (`loadDashboard`, `openDetail`) unchanged.

```javascript
/**
 * Start the simulation with the currently selected pace.
 * POST /api/v1/simulation/start {pace_seconds}; records session_id from the
 * 200 response; then begins polling. Handles EC-01 (409) and EC-06
 * (started:false + queue_empty:true) messages.
 */
async function startSimulation() {}

/** POST /api/v1/simulation/pause (US-02 S2). */
async function pauseSimulation() {}

/** POST /api/v1/simulation/resume (US-02 S2). */
async function resumeSimulation() {}

/** POST /api/v1/simulation/stop (US-02 S3); returns controls to ready. */
async function stopSimulation() {}

/**
 * Poll loop (SIM_POLL_INTERVAL_MS = 1000). GET /api/v1/simulation/status;
 * when processed_count/lane counts changed, calls loadDashboard() to refresh
 * the F5 board and renderProgress(status) to update "n of N" + lane badges
 * (US-03 S1). Detects EC-04 via detectSessionMismatch() and shows the
 * "cannot be resumed" notice + Start New option.
 */
async function pollSimulationStatus() {}

/** Render state-specific control bar (Start/Pause/Resume/Stop enablement). */
function renderSimulationControls(status) {}

/** Render "n of N", per-lane counts, skipped count, and percent (US-03). */
function renderProgress(status) {}

/** Render EC-02 skip warnings in the progress area. */
function renderSimulationWarnings(status) {}

/** Render EC-03 error banner with Retry (resume) and Stop actions. */
function showSimulationError(status) {}

/** EC-04: compare known session_id vs server status; show notice + Start New. */
function handleSimulationSessionMismatch(status) {}

/** Completion notice + final counts when state === COMPLETED (US-03 S2). */
function showSimulationComplete(status) {}
```

Frontend constants: `SIM_POLL_INTERVAL_MS = 1000`. `index.html` adds a **Simulation Control Bar** (pace `<select>` with 2/3/5 s options plus a numeric custom input, Start / Pause / Resume / Stop buttons, progress indicator, warnings list, error banner) placed above the F5 two-lane board.

---

## 3. Data Models & Schemas

All models live in `backend/app/models/simulation_models.py` (Pydantic v2, `str`-backed enums, matching F5/F6 conventions). **No new DB tables** are introduced.

```python
from datetime import datetime
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
```

---

## 4. API Contracts

Router: `APIRouter(prefix="/api/v1", tags=["simulation"])` in `backend/app/routes/simulation.py`. Registered in `main.py` after `human_decisions` router. All errors use FastAPI `HTTPException(status_code=..., detail=str(exc))` per repo convention.

### 4.1 `POST /api/v1/simulation/start`

**Request body** (`StartSimulationRequest`):

```json
{ "pace_seconds": 3.0 }
```

**Responses**

| Status | Body / Detail | Scenario |
|---|---|---|
| `200` | `SimulationStatusResponse` with `started: true`, `state: RUNNING`, queue totals | US-01 S1, US-02 S1 — run launched |
| `200` | `SimulationStatusResponse` with `started: false`, `queue_empty: true`, `state: IDLE`, `last_run_summary` (final counts), `message: "No tickets left to simulate"` | EC-06 / US-01 S2 — queue empty |
| `200` | `SimulationStatusResponse` with `pace_adjusted: true`, `pace_adjusted_note`, `started: true` | EC-05 — pace clamped to minimum |
| `409` | `{"detail": "a simulation is already in progress"}` | EC-01 / US-02 — `SimulationAlreadyRunningError` |
| `422` | `{"detail": "pace_seconds must be finite"}` | EC-05 non-finite — `SimulationPaceInvalidError` |
| `500` | `{"detail": "Simulation pipeline unavailable: ..."}` | EC-03 at start — `SimulationPipelineUnavailableError` |

### 4.2 `POST /api/v1/simulation/pause`

**Body:** none. **Responses:**

| Status | Body / Detail | Scenario |
|---|---|---|
| `200` | `SimulationStatusResponse` with `state: PAUSED`; `processed_count` unchanged | US-02 S2 |
| `409` | `{"detail": "no simulation is running"}` | `SimulationStateConflictError` |

### 4.3 `POST /api/v1/simulation/resume`

**Body:** none. **Responses:**

| Status | Body / Detail | Scenario |
|---|---|---|
| `200` | `SimulationStatusResponse` with `state: RUNNING`, continues from `processed_count` | US-02 S2 |
| `409` | `{"detail": "simulation is not paused"}` | `SimulationStateConflictError` |

### 4.4 `POST /api/v1/simulation/stop`

**Body:** none. **Responses:**

| Status | Body / Detail | Scenario |
|---|---|---|
| `200` | `SimulationStatusResponse` with `state: IDLE`, `last_run_summary` (`ended_by: "stopped"`), `remaining_count` > 0 | US-02 S3 — early stop, remaining tickets stay queued |
| `409` | `{"detail": "no simulation is running"}` | `SimulationStateConflictError` |

### 4.5 `GET /api/v1/simulation/status`

**Query params:** none. **Responses:**

| Status | Body / Detail | Scenario |
|---|---|---|
| `200` | `SimulationStatusResponse` (always) | US-03 S1/S2 — live progress; EC-04 session matching; EC-03 error detail when paused |
| `500` | `{"detail": "Simulation failed: ..."}` | Unexpected runtime corruption |

**Polling contract:** the frontend polls every `SIM_POLL_INTERVAL_MS` (1000 ms). When `processed_count` or `lane_counts` differ from the previous snapshot, the frontend refreshes the F5 board via `GET /api/v1/dashboard` and animates `recently_landed_ticket_ids` into lanes.

### 4.6 Reused Endpoints (not F7-owned)

| Endpoint | Owner | F7 Use |
|---|---|---|
| `GET /api/v1/dashboard` | F5 | Refresh board after each landing (US-01 S1) |
| `GET /api/v1/dashboard/tickets/{ticket_id}` | F5 | Ticket detail on card click (US-01 S3) — unchanged |
| `POST /api/v1/human-decisions/...` | F6 | Simulated tickets in Needs Human Review remain actionable (F6 integration) |

---

## 5. Error Types & Handling

### 5.1 Exception Hierarchy

```
SimulationError (base)
├── SimulationStateConflictError            → 409 (pause/resume/stop in wrong state)
│   └── SimulationAlreadyRunningError        → 409 (EC-01)
├── SimulationPaceInvalidError               → 422 (EC-05 non-finite)
├── SimulationQueueEmptyError                → 200 response (EC-06), carries .status
├── SimulationUnreadableTicketError          → internal skip warning (EC-02), not HTTP
└── SimulationPipelineUnavailableError       → 500 at start / auto-pause mid-run (EC-03)
```

### 5.2 Edge Case → Error/Handling Mapping

| EC | Trigger | Error Type / Handling | HTTP |
|---|---|---|---|
| EC-01 | Start while running | `SimulationAlreadyRunningError` via `validate_state_transition(START)` | `409` with "already in progress" message |
| EC-02 | Queued ticket missing/unreadable description | `SimulationUnreadableTicketError` caught in `tick_loop`; recorded as `SimulationWarning` (`code="unreadable_description"`), `skipped_count` incremented, loop continues; skipped count reported in `last_run_summary` | not an HTTP error; surfaced via `status.warnings` + completion summary |
| EC-03 | Pipeline unavailable mid-run | `SimulationPipelineUnavailableError` caught in `tick_loop`; auto-pause → `state=PAUSED`, `error={code:"pipeline_unavailable", retryable:true}`; progress preserved; viewer may Resume (Retry) or Stop | start path `500`; mid-run via `GET /status` |
| EC-04 | Page refresh during run | `session_id` comparison via `detect_session_mismatch()`; frontend shows "previous simulation cannot be resumed" and offers Start New (stop + start); processed tickets remain on the F5 board (persisted `decision_log`) | client-side notice; backend support via `session_id` |
| EC-05 | Delay zero/extremely small | `validate_pace` clamps to `SIMULATION_MIN_PACE_SECONDS`; `pace_adjusted=true` + note in status; non-finite values → `SimulationPaceInvalidError` | `200` with note; `422` for non-finite |
| EC-06 | All tickets already processed | Queue snapshot empty → `SimulationQueueEmptyError`; route returns `200` with `started:false`, `queue_empty:true`, `message`, and `last_run_summary` final counts | `200` (informational) |

### 5.3 Error Response Shape

All HTTP errors follow the repo convention:

```json
{ "detail": "human-readable error string" }
```

---

## 6. Spec-to-Component Traceability

| Spec Item | Technical Component | Function / Endpoint |
|---|---|---|
| US-01 S1: start simulation with tickets available | SimulationService + Manager tick loop | `start_simulation()` · `advance_simulation()` · `_process_ticket()` · `POST /api/v1/simulation/start` |
| US-01 S2: start when queue empty | Queue snapshot + error mapping | `SimulationQueueEmptyError` · `POST /api/v1/simulation/start` → 200 `started:false` (EC-06) |
| US-01 S3: ticket detail after landing | F5 reuse (no new code) | `GET /api/v1/dashboard/tickets/{ticket_id}` · `openDetail()` |
| US-02 S1: configure pace before start | Engine pace rule | `validate_pace()` · `StartSimulationRequest.pace_seconds` · `POST /api/v1/simulation/start` |
| US-02 S2: pause and resume | State machine + manager flags | `validate_state_transition()` · `pause_simulation()` · `resume_simulation()` · `POST /simulation/pause|resume` |
| US-02 S3: stop early, return to ready | State machine + run summary | `stop_simulation()` · `SimulationRunSummary(ended_by="stopped")` · `POST /api/v1/simulation/stop` |
| US-03 S1: progress updates per ticket | Lane counting + status snapshot | `compute_lane_counts()` · `SimulationStatusResponse` · `GET /api/v1/simulation/status` · `pollSimulationStatus()` / `renderProgress()` |
| US-03 S2: completion state + notification | State machine COMPLETE | `validate_state_transition(COMPLETE)` · `state=COMPLETED` + `completed_at` + `message` · `showSimulationComplete()` |
| BR-01 (queue = unprocessed only) | Queue snapshot query | `start_simulation()` (LEFT JOIN `decision_log` filter) |
| BR-02 (lane from outcome only) | Pipeline delegation | `_process_ticket()` → `resolution_service.resolve_ticket()` |
| BR-03 (one simulation at a time) | Singleton manager + transition guard | `SimulationManager` · `validate_state_transition()` (EC-01) |
| BR-04 (no delete/duplicate/alter) | No new tables; idempotent F3 upsert | reuse of `resolution_service._persist_decision()` |
| BR-05 (visible afterward on dashboard) | Persisted `decision_log`/`reply_log` rows | `GET /api/v1/dashboard` (F5) |
| BR-06 (sensible minimum pace) | Pace clamp | `validate_pace()` · `SIMULATION_MIN_PACE_SECONDS` (EC-05) |
| EC-01 | Error type | `SimulationAlreadyRunningError` → 409 |
| EC-02 | Error type + warning model | `SimulationUnreadableTicketError` · `SimulationWarning` |
| EC-03 | Error type + auto-pause | `SimulationPipelineUnavailableError` · `SimulationErrorInfo` |
| EC-04 | Session mismatch detection | `detect_session_mismatch()` · `session_id` · `handleSimulationSessionMismatch()` |
| EC-05 | Error type + clamp | `SimulationPaceInvalidError` · `validate_pace()` · `pace_adjusted` |
| EC-06 | Error type + informational 200 | `SimulationQueueEmptyError` · `last_run_summary` |

---

## 7. Sequence Diagram

### 7.1 Primary Workflow — Start → Live Landing → Pause/Resume → Completion (US-01, US-02, US-03)

```mermaid
sequenceDiagram
    participant V as Viewer
    participant F as Frontend (app.js)
    participant R as Simulation Routes
    participant S as Simulation Manager
    participant P as Pipeline (F2/F3/F4)
    participant DB as SQLite (decision_log)
    participant D as F5 Dashboard API

    V->>F: Select pace (e.g. 3 s) + click Start Simulation
    F->>R: POST /api/v1/simulation/start {pace_seconds: 3}
    R->>S: start_simulation(db, 3)
    S->>S: validate_pace(3) → {3, adjusted:false}
    S->>S: queue = new_tickets w/o decision_log → [N-001 … N-020]
    S-->>R: SimulationStatusResponse {state: RUNNING, session_id, queue_total: 20}
    R-->>F: 200 {started: true}
    F->>V: Control bar shows RUNNING; record session_id

    loop Each queued ticket (pace honored between arrivals)
        S->>S: wait tick / honor pause+stop flags
        S->>P: process N-00X (F2 similarity → F3 decision → F4 reply)
        P->>DB: insert decision_log + reply_log rows
        S->>S: record ProcessedTicketEntry (lane) + compute_lane_counts
        F->>R: GET /api/v1/simulation/status (poll, 1 s)
        R-->>F: 200 {processed_count: n, lane_counts, recently_landed: [N-00X]}
        F->>D: GET /api/v1/dashboard
        D-->>F: 200 DashboardBoard (card in correct lane)
        F->>V: Animate card into lane; update "n of 20" + lane badges
    end

    V->>F: Click Pause (mid-run)
    F->>R: POST /api/v1/simulation/pause
    R-->>F: 200 {state: PAUSED, processed_count held}
    F->>V: Progress holds; Resume enabled
    V->>F: Click Resume
    F->>R: POST /api/v1/simulation/resume
    R-->>F: 200 {state: RUNNING}
    F->>V: Processing continues from where it left off

    S->>S: queue exhausted → state = COMPLETED
    F->>R: GET /api/v1/simulation/status
    R-->>F: 200 {state: COMPLETED, completed_at, message: "Simulation finished"}
    F->>V: Show completion notice + final counts (US-03 S2)
```

### 7.2 EC-03 — Pipeline Unavailable Mid-Run (auto-pause + retry/stop)

```mermaid
sequenceDiagram
    participant Loop as Background Tick Loop
    participant P as Pipeline (F2/F3/F4)
    participant M as SimulationManager
    participant F as Frontend
    participant R as Simulation Routes

    Loop->>P: process next ticket
    P-->>Loop: SimulationPipelineUnavailableError
    Loop->>M: auto-pause (state=PAUSED) + set error {retryable: true}
    Note over M: processed_count preserved — no ticket lost (progress kept)
    F->>R: GET /api/v1/simulation/status
    R-->>F: 200 {state: PAUSED, error: {code:"pipeline_unavailable", retryable:true}}
    F->>F: showSimulationError(status) → error banner + Retry/Stop buttons
    V->>F: Click Retry (Resume)
    F->>R: POST /api/v1/simulation/resume
    R-->>F: 200 {state: RUNNING}   (or error recurs → auto-pause again)
    V->>F: Click Stop (alternative)
    F->>R: POST /api/v1/simulation/stop
    R-->>F: 200 {state: IDLE, last_run_summary.ended_by:"paused_with_error"}
```

---

## 8. Notes for Implementers & Test Engineers

1. **Deterministic tests**: prefer `advance_simulation(db)` for single-step assertions; use env overrides `STM_SIMULATION_MIN_PACE_SECONDS=0.01` / `STM_SIMULATION_DEFAULT_PACE_SECONDS=0.05` for API-level runs; call `reset_simulation_manager()` between test cases.
2. **Pace unit**: seconds (`float`), matching the spec's "number of seconds between arrivals" (US-02 S1). The frontend converts select options (2/3/5) to seconds.
3. **Queue ordering**: `ticket_id ASC` for a deterministic demo (N-001 first).
4. **F6 coexistence**: simulated tickets landing in Needs Human Review get no special handling — the F6 routes act on them as on any other ticket.
5. **No SSE/WebSockets**: the vanilla-JS stack uses 1-second polling; the `recently_landed_ticket_ids` field exists so the frontend can avoid full-board re-renders when nothing changed.
