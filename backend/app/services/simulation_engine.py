"""Pure rules for the Live Ticket Simulation feature (FEAT-007).

No I/O, no ``AsyncSession``. Fully deterministic for black-box testing.
Contracts documented in ``features/F7-live-ticket-simulation/2_tech_spec.md``
§2.1 / §5.
"""

import math
from typing import Optional, Sequence

from app.core.config import settings
from app.models.dashboard_models import DashboardLane
from app.models.simulation_models import (
    LaneCounts,
    PaceValidationResult,
    SimulationCommand,
    SimulationState,
    SimulationStatusResponse,
)


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


# Valid lifecycle transitions (2_tech_spec.md §1.3 / §2.1).
_VALID_TRANSITIONS = {
    (SimulationState.IDLE, SimulationCommand.START): SimulationState.RUNNING,
    (SimulationState.COMPLETED, SimulationCommand.START): SimulationState.RUNNING,
    (SimulationState.RUNNING, SimulationCommand.PAUSE): SimulationState.PAUSED,
    (SimulationState.PAUSED, SimulationCommand.RESUME): SimulationState.RUNNING,
    (SimulationState.RUNNING, SimulationCommand.STOP): SimulationState.IDLE,
    (SimulationState.PAUSED, SimulationCommand.STOP): SimulationState.IDLE,
    (SimulationState.RUNNING, SimulationCommand.COMPLETE): SimulationState.COMPLETED,
    (SimulationState.RUNNING, SimulationCommand.FAILED): SimulationState.PAUSED,
}

# Commands that may be issued only from a RUNNING state (internal, EC-03/§2.1).
_ACTIVE_STATES = (SimulationState.RUNNING, SimulationState.PAUSED)


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
    if not math.isfinite(pace_seconds):
        raise SimulationPaceInvalidError("pace_seconds must be finite")

    minimum = settings.SIMULATION_MIN_PACE_SECONDS
    maximum = settings.SIMULATION_MAX_PACE_SECONDS

    if pace_seconds < minimum:
        return PaceValidationResult(
            pace_seconds=minimum,
            adjusted=True,
            note=f"Arrival delay adjusted to the minimum of {minimum} seconds.",
        )
    if pace_seconds > maximum:
        return PaceValidationResult(
            pace_seconds=maximum,
            adjusted=True,
            note=f"Arrival delay adjusted to the maximum of {maximum} seconds.",
        )
    return PaceValidationResult(pace_seconds=pace_seconds, adjusted=False, note=None)


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
    next_state = _VALID_TRANSITIONS.get((current, command))
    if next_state is not None:
        return next_state

    if command == SimulationCommand.START and current in _ACTIVE_STATES:
        raise SimulationAlreadyRunningError("a simulation is already in progress")
    raise SimulationStateConflictError(
        f"cannot {command.value} from state {current.value}"
    )


def compute_lane_counts(entries: Sequence["ProcessedTicketEntry"]) -> LaneCounts:
    """Count landed tickets per lane for progress reporting (US-03 S1).

    Args:
        entries: The run's processed-ticket records so far.

    Returns:
        ``LaneCounts`` with ``auto_resolved`` and ``needs_review`` totals.

    Raises:
        SimulationError: If any entry lacks a valid lane (defensive).
    """
    valid_lanes = (DashboardLane.AUTO_RESOLVED, DashboardLane.NEEDS_REVIEW)
    auto_resolved = 0
    needs_review = 0
    for entry in entries:
        if entry.lane not in valid_lanes:
            raise SimulationError(
                f"ticket {entry.ticket_id} has an invalid lane: {entry.lane!r}"
            )
        if entry.lane == DashboardLane.AUTO_RESOLVED:
            auto_resolved += 1
        else:
            needs_review += 1
    return LaneCounts(auto_resolved=auto_resolved, needs_review=needs_review)


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
    if status.state not in (SimulationState.RUNNING, SimulationState.PAUSED):
        return False
    if known_session_id is None:
        return True
    return known_session_id != status.session_id
