"""Black-box tests for F7 Live Ticket Simulation (FEAT-007).

Generated exclusively from:
- `features/F7-live-ticket-simulation/1_spec.md` (user stories US-01..US-03,
  business rules BR-01..BR-06, edge cases EC-01..EC-06)
- `features/F7-live-ticket-simulation/2_tech_spec.md` (interface contracts:
  Pydantic models §3, pure engine functions §2.1, service facade §2.2,
  manager §2.3, API contracts §4, error table §5, traceability §6)

No implementation source was read. Every test targets a public contract and
must pass for ANY correct implementation of the spec. Deterministic
single-step assertions use `advance_simulation(db, manager)` and a mocked
pipeline seam (`_process_ticket`) per §8 note 1.
"""

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.dashboard_models import DashboardLane
from app.models.simulation_models import (
    LaneCounts,
    PaceValidationResult,
    ProcessedTicketEntry,
    SimulationCommand,
    SimulationErrorInfo,
    SimulationRunSummary,
    SimulationState,
    SimulationStatusResponse,
    SimulationWarning,
    StartSimulationRequest,
)
from app.services.simulation_engine import (
    SimulationAlreadyRunningError,
    SimulationError,
    SimulationPaceInvalidError,
    SimulationPipelineUnavailableError,
    SimulationQueueEmptyError,
    SimulationStateConflictError,
    SimulationUnreadableTicketError,
    compute_lane_counts,
    detect_session_mismatch,
    validate_pace,
    validate_state_transition,
)
from app.services.simulation_manager import SimulationManager, default_manager
from app.services.simulation_service import (
    advance_simulation,
    get_simulation_status,
    pause_simulation,
    reset_simulation_manager,
    resume_simulation,
    start_simulation,
    stop_simulation,
)


# ---------------------------------------------------------------------------
# Seed & fixture helpers (data shaped by 2_tech_spec.md §3 examples)
# ---------------------------------------------------------------------------

async def _seed_ticket(
    db: AsyncSession,
    ticket_id: str = "N-001",
    order_id: str = "ORD-1001",
    description: str = "milk packet missing from my order",
) -> None:
    """Insert one unprocessed F1 new_tickets row (the simulation queue source)."""
    await db.execute(
        text(
            "INSERT INTO new_tickets (ticket_id, order_id, description) "
            "VALUES (:ticket_id, :order_id, :description)"
        ),
        {"ticket_id": ticket_id, "order_id": order_id, "description": description},
    )
    await db.commit()


def _entry(
    ticket_id: str = "N-001",
    lane: DashboardLane = DashboardLane.AUTO_RESOLVED,
    auto_resolved: bool = True,
    confidence: float = 0.9,
) -> ProcessedTicketEntry:
    """One landed-ticket record returned by the mocked pipeline seam."""
    return ProcessedTicketEntry(
        ticket_id=ticket_id,
        lane=lane,
        auto_resolved=auto_resolved,
        confidence=confidence,
        processed_at="2026-08-08T10:00:00+00:00",
    )


def _status(**overrides) -> SimulationStatusResponse:
    """A valid SimulationStatusResponse with sane defaults for any test."""
    defaults = {
        "state": SimulationState.IDLE,
        "session_id": None,
        "run_id": None,
        "running": False,
        "paused": False,
        "started": False,
        "queue_total": 0,
        "processed_count": 0,
        "skipped_count": 0,
        "remaining_count": 0,
        "auto_resolved_count": 0,
        "needs_review_count": 0,
        "lane_counts": LaneCounts(auto_resolved=0, needs_review=0),
        "queue_empty": True,
        "recently_landed_ticket_ids": [],
        "warnings": [],
    }
    defaults.update(overrides)
    return SimulationStatusResponse(**defaults)


async def _fake_process(db: AsyncSession, ticket_id: str) -> ProcessedTicketEntry:
    """Default mock of the pipeline seam: every ticket auto-resolves."""
    return _entry(ticket_id=ticket_id)


# ---------------------------------------------------------------------------
# Feature: Live Ticket Simulation (FEAT-007)
# ---------------------------------------------------------------------------

class TestLiveTicketSimulation:
    """Tests for the Live Ticket Simulation feature."""

    # ------------------------------------------------------------------
    # §3 Pydantic model contracts
    # ------------------------------------------------------------------

    class TestSimulationModels:
        """Contract tests for the §3 Pydantic models / field constraints."""

        def test_simulation_state_enum_values(self):
            """§3: the lifecycle states carry canonical wire values."""
            assert SimulationState.IDLE.value == "idle"
            assert SimulationState.RUNNING.value == "running"
            assert SimulationState.PAUSED.value == "paused"
            assert SimulationState.COMPLETED.value == "completed"

        def test_simulation_command_enum_values(self):
            """§3: lifecycle commands carry canonical wire values."""
            assert SimulationCommand.START.value == "start"
            assert SimulationCommand.PAUSE.value == "pause"
            assert SimulationCommand.RESUME.value == "resume"
            assert SimulationCommand.STOP.value == "stop"
            assert SimulationCommand.COMPLETE.value == "complete"
            assert SimulationCommand.FAILED.value == "failed"

        def test_pace_validation_result_accepts_valid_pace(self):
            """§3: a canonical pace is non-positive-invalidated and adjustable."""
            result = PaceValidationResult(pace_seconds=3.0, adjusted=False, note=None)
            assert result.pace_seconds == 3.0
            assert result.adjusted is False
            assert result.note is None

        def test_pace_validation_result_rejects_non_positive_pace(self):
            """§3: pace_seconds must be > 0."""
            with pytest.raises(ValidationError):
                PaceValidationResult(pace_seconds=0.0, adjusted=False)
            with pytest.raises(ValidationError):
                PaceValidationResult(pace_seconds=-1.0, adjusted=False)

        def test_lane_counts_accepts_zeros(self):
            """US-03 S1: an empty run reports zero per-lane totals."""
            counts = LaneCounts(auto_resolved=0, needs_review=0)
            assert counts.auto_resolved == 0
            assert counts.needs_review == 0

        def test_lane_counts_rejects_negative_totals(self):
            """§3: lane totals must be >= 0."""
            with pytest.raises(ValidationError):
                LaneCounts(auto_resolved=-1, needs_review=0)
            with pytest.raises(ValidationError):
                LaneCounts(auto_resolved=0, needs_review=-1)

        def test_simulation_warning_shape(self):
            """EC-02: a skip warning carries the ticket id, code, and message."""
            warning = SimulationWarning(
                ticket_id="N-001",
                code="unreadable_description",
                message="Ticket description could not be read.",
            )
            assert warning.ticket_id == "N-001"
            assert warning.code == "unreadable_description"

        def test_simulation_error_info_shape(self):
            """EC-03: the error detail carries a machine code and retryability."""
            info = SimulationErrorInfo(
                code="pipeline_unavailable", message="Pipeline failed.", retryable=True
            )
            assert info.retryable is True

        def test_processed_ticket_entry_accepts_valid_payload(self):
            """§3: a landed ticket records id, lane, flag, confidence, timestamp."""
            entry = _entry()
            assert entry.ticket_id == "N-001"
            assert entry.lane == DashboardLane.AUTO_RESOLVED
            assert entry.auto_resolved is True
            assert entry.confidence == 0.9

        def test_processed_ticket_entry_rejects_confidence_out_of_range(self):
            """§3: confidence must be within [0, 1]."""
            with pytest.raises(ValidationError):
                ProcessedTicketEntry(
                    ticket_id="N-001",
                    lane=DashboardLane.AUTO_RESOLVED,
                    auto_resolved=True,
                    confidence=1.5,
                    processed_at="2026-08-08T10:00:00+00:00",
                )

        def test_run_summary_accepts_valid_counts(self):
            """§3: a final run summary carries per-lane and skip tallies."""
            summary = SimulationRunSummary(
                run_id="run-1",
                started_at="2026-08-08T10:00:00+00:00",
                ended_at="2026-08-08T10:02:00+00:00",
                total_queued=5,
                processed_count=4,
                skipped_count=1,
                auto_resolved_count=3,
                needs_review_count=1,
                ended_by="completed",
            )
            assert summary.ended_by == "completed"

        def test_run_summary_rejects_negative_counts(self):
            """§3: all summary counts must be >= 0."""
            with pytest.raises(ValidationError):
                SimulationRunSummary(
                    run_id="run-1",
                    started_at="2026-08-08T10:00:00+00:00",
                    total_queued=-1,
                    processed_count=0,
                    skipped_count=0,
                    auto_resolved_count=0,
                    needs_review_count=0,
                    ended_by="completed",
                )

        def test_start_request_accepts_omitted_pace(self):
            """US-02 S1: omitting pace_seconds means 'use the default pace'."""
            request = StartSimulationRequest()
            assert request.pace_seconds is None

        def test_start_request_accepts_valid_pace(self):
            """US-02 S1: a positive pace is accepted."""
            request = StartSimulationRequest(pace_seconds=3.0)
            assert request.pace_seconds == 3.0

        def test_start_request_rejects_non_positive_pace(self):
            """§3/EC-05: pace must be > 0."""
            with pytest.raises(ValidationError):
                StartSimulationRequest(pace_seconds=0)
            with pytest.raises(ValidationError):
                StartSimulationRequest(pace_seconds=-2.0)

        def test_status_response_accepts_valid_payload(self):
            """US-03 S1: the full snapshot shape is constructible."""
            status = _status(
                state=SimulationState.RUNNING,
                running=True,
                started=True,
                queue_total=20,
                processed_count=12,
                remaining_count=8,
                auto_resolved_count=9,
                needs_review_count=3,
                lane_counts=LaneCounts(auto_resolved=9, needs_review=3),
                queue_empty=False,
            )
            assert status.state == SimulationState.RUNNING
            assert status.processed_count == 12
            assert status.lane_counts.auto_resolved == 9

        def test_status_response_defaults_for_collections(self):
            """§3: recently-landed ids and warnings default to empty lists."""
            status = _status()
            assert status.recently_landed_ticket_ids == []
            assert status.warnings == []
            assert status.pace_adjusted is False

        def test_status_response_rejects_negative_counts(self):
            """§3: queue/processed/skip/remaining counts must be >= 0."""
            with pytest.raises(ValidationError):
                _status(queue_total=-1)
            with pytest.raises(ValidationError):
                _status(processed_count=-1)
            with pytest.raises(ValidationError):
                _status(skipped_count=-1)
            with pytest.raises(ValidationError):
                _status(remaining_count=-1)
            with pytest.raises(ValidationError):
                _status(auto_resolved_count=-1)

    # ------------------------------------------------------------------
    # §2.1 Pure engine — validate_pace() (US-02 S1, EC-05)
    # ------------------------------------------------------------------

    class TestValidatePace:
        """EC-05 / US-02 S1: canonicalize the arrival delay with clamping."""

        @pytest.fixture(autouse=True)
        def _known_bounds(self, monkeypatch):
            """Pin the clamp bounds so expectations are exact, not env-dependent."""
            monkeypatch.setattr(settings, "SIMULATION_MIN_PACE_SECONDS", 1.0)
            monkeypatch.setattr(settings, "SIMULATION_MAX_PACE_SECONDS", 30.0)

        def test_valid_pace_passes_through(self):
            """US-02 S1: a pace inside the bounds is returned unchanged."""
            result = validate_pace(3.0)
            assert isinstance(result, PaceValidationResult)
            assert result.pace_seconds == 3.0
            assert result.adjusted is False
            assert result.note is None

        def test_pace_below_minimum_is_clamped_up(self):
            """EC-05: a near-zero delay is raised to the configured minimum."""
            result = validate_pace(0.05)
            assert result.pace_seconds == 1.0
            assert result.adjusted is True
            assert result.note is not None

        def test_pace_above_maximum_is_clamped_down(self):
            """EC-05: an excessive delay is capped at the configured maximum."""
            result = validate_pace(999.0)
            assert result.pace_seconds == 30.0
            assert result.adjusted is True
            assert result.note is not None

        def test_pace_equal_to_minimum_is_not_adjusted(self):
            """EC-05: the boundary value itself is accepted unadjusted."""
            result = validate_pace(1.0)
            assert result.pace_seconds == 1.0
            assert result.adjusted is False

        def test_pace_equal_to_maximum_is_not_adjusted(self):
            """EC-05: the upper boundary value is accepted unadjusted."""
            result = validate_pace(30.0)
            assert result.pace_seconds == 30.0
            assert result.adjusted is False

        def test_nan_pace_raises(self):
            """EC-05: a NaN delay is non-finite and refused (→ 422)."""
            with pytest.raises(SimulationPaceInvalidError):
                validate_pace(float("nan"))

        def test_positive_infinity_raises(self):
            """EC-05: +inf is non-finite and refused."""
            with pytest.raises(SimulationPaceInvalidError):
                validate_pace(float("inf"))

        def test_negative_infinity_raises(self):
            """EC-05: -inf is non-finite and refused."""
            with pytest.raises(SimulationPaceInvalidError):
                validate_pace(float("-inf"))

    # ------------------------------------------------------------------
    # §2.1 Pure engine — validate_state_transition() (US-02, BR-03)
    # ------------------------------------------------------------------

    class TestValidateStateTransition:
        """BR-03: lifecycle transitions are enforced by a state machine."""

        def test_idle_can_start(self):
            """US-01 S1: IDLE --START--> RUNNING."""
            assert (
                validate_state_transition(SimulationState.IDLE, SimulationCommand.START)
                == SimulationState.RUNNING
            )

        def test_completed_can_start(self):
            """US-03 S2: after completion the viewer may start again."""
            assert (
                validate_state_transition(
                    SimulationState.COMPLETED, SimulationCommand.START
                )
                == SimulationState.RUNNING
            )

        def test_running_can_pause(self):
            """US-02 S2: RUNNING --PAUSE--> PAUSED."""
            assert (
                validate_state_transition(
                    SimulationState.RUNNING, SimulationCommand.PAUSE
                )
                == SimulationState.PAUSED
            )

        def test_paused_can_resume(self):
            """US-02 S2: PAUSED --RESUME--> RUNNING."""
            assert (
                validate_state_transition(
                    SimulationState.PAUSED, SimulationCommand.RESUME
                )
                == SimulationState.RUNNING
            )

        def test_running_can_stop(self):
            """US-02 S3: RUNNING --STOP--> IDLE."""
            assert (
                validate_state_transition(SimulationState.RUNNING, SimulationCommand.STOP)
                == SimulationState.IDLE
            )

        def test_paused_can_stop(self):
            """US-02 S3: PAUSED --STOP--> IDLE."""
            assert (
                validate_state_transition(SimulationState.PAUSED, SimulationCommand.STOP)
                == SimulationState.IDLE
            )

        def test_running_can_complete(self):
            """US-03 S2: RUNNING --COMPLETE--> COMPLETED (queue exhausted)."""
            assert (
                validate_state_transition(
                    SimulationState.RUNNING, SimulationCommand.COMPLETE
                )
                == SimulationState.COMPLETED
            )

        def test_running_can_fail_into_paused(self):
            """EC-03: RUNNING --FAILED--> PAUSED (auto-pause on pipeline failure)."""
            assert (
                validate_state_transition(
                    SimulationState.RUNNING, SimulationCommand.FAILED
                )
                == SimulationState.PAUSED
            )

        def test_start_while_running_raises(self):
            """EC-01: START while RUNNING is a conflict (→ 409)."""
            with pytest.raises(SimulationStateConflictError):
                validate_state_transition(SimulationState.RUNNING, SimulationCommand.START)

        def test_start_while_paused_raises(self):
            """EC-01: START while PAUSED is also refused."""
            with pytest.raises(SimulationStateConflictError):
                validate_state_transition(SimulationState.PAUSED, SimulationCommand.START)

        def test_pause_while_idle_raises(self):
            """§2.1: PAUSE from IDLE is not allowed (→ 409)."""
            with pytest.raises(SimulationStateConflictError):
                validate_state_transition(SimulationState.IDLE, SimulationCommand.PAUSE)

        def test_pause_while_paused_raises(self):
            """§2.1: PAUSE from PAUSED is not allowed."""
            with pytest.raises(SimulationStateConflictError):
                validate_state_transition(SimulationState.PAUSED, SimulationCommand.PAUSE)

        def test_resume_while_running_raises(self):
            """§2.1: RESUME from RUNNING is not allowed (→ 409)."""
            with pytest.raises(SimulationStateConflictError):
                validate_state_transition(SimulationState.RUNNING, SimulationCommand.RESUME)

        def test_resume_while_idle_raises(self):
            """§2.1: RESUME from IDLE is not allowed."""
            with pytest.raises(SimulationStateConflictError):
                validate_state_transition(SimulationState.IDLE, SimulationCommand.RESUME)

        def test_stop_while_idle_raises(self):
            """§2.1: STOP from IDLE is not allowed (→ 409)."""
            with pytest.raises(SimulationStateConflictError):
                validate_state_transition(SimulationState.IDLE, SimulationCommand.STOP)

        def test_complete_while_paused_raises(self):
            """§2.1: COMPLETE only fires from RUNNING."""
            with pytest.raises(SimulationStateConflictError):
                validate_state_transition(SimulationState.PAUSED, SimulationCommand.COMPLETE)

        def test_failed_while_idle_raises(self):
            """§2.1: FAILED only fires from RUNNING."""
            with pytest.raises(SimulationStateConflictError):
                validate_state_transition(SimulationState.IDLE, SimulationCommand.FAILED)

    # ------------------------------------------------------------------
    # §2.1 Pure engine — compute_lane_counts() (US-03 S1)
    # ------------------------------------------------------------------

    class TestComputeLaneCounts:
        """US-03 S1: tally landed tickets per lane for the progress badges."""

        def test_empty_entries_yield_zero_counts(self):
            """US-03 S1: no landed tickets yet → both lanes at zero."""
            counts = compute_lane_counts([])
            assert isinstance(counts, LaneCounts)
            assert counts.auto_resolved == 0
            assert counts.needs_review == 0

        def test_all_auto_resolved_entries(self):
            """US-03 S1: only auto-resolved tickets land in that lane."""
            counts = compute_lane_counts([
                _entry(ticket_id="N-001"),
                _entry(ticket_id="N-002"),
                _entry(ticket_id="N-003"),
            ])
            assert counts.auto_resolved == 3
            assert counts.needs_review == 0

        def test_mixed_lanes_are_counted_per_lane(self):
            """US-03 S1: auto-resolved and review tickets are counted separately."""
            counts = compute_lane_counts([
                _entry(ticket_id="N-001"),
                _entry(
                    ticket_id="N-002",
                    lane=DashboardLane.NEEDS_REVIEW,
                    auto_resolved=False,
                ),
                _entry(ticket_id="N-003"),
                _entry(
                    ticket_id="N-004",
                    lane=DashboardLane.NEEDS_REVIEW,
                    auto_resolved=False,
                ),
            ])
            assert counts.auto_resolved == 2
            assert counts.needs_review == 2

        def test_entry_without_lane_raises_defensive_error(self):
            """§2.1: an entry lacking a valid lane surfaces as a SimulationError."""
            malformed = ProcessedTicketEntry.model_construct(
                ticket_id="N-001",
                lane=None,
                auto_resolved=True,
                confidence=0.9,
                processed_at="2026-08-08T10:00:00+00:00",
            )
            with pytest.raises(SimulationError):
                compute_lane_counts([malformed])

    # ------------------------------------------------------------------
    # §2.1 Pure engine — detect_session_mismatch() (EC-04)
    # ------------------------------------------------------------------

    class TestDetectSessionMismatch:
        """EC-04: page refresh during an active run is detected via session id."""

        def test_active_run_with_unknown_session_is_a_mismatch(self):
            """EC-04: a fresh page (no remembered session) during a run → mismatch."""
            status = _status(
                state=SimulationState.RUNNING,
                running=True,
                session_id="run-abc",
                queue_empty=False,
            )
            assert detect_session_mismatch(status, None) is True

        def test_active_run_with_different_session_is_a_mismatch(self):
            """EC-04: the page's session differs from the server's → mismatch."""
            status = _status(
                state=SimulationState.RUNNING,
                running=True,
                session_id="run-abc",
                queue_empty=False,
            )
            assert detect_session_mismatch(status, "run-old") is True

        def test_paused_run_with_different_session_is_a_mismatch(self):
            """EC-04: a paused run belongs to another session → mismatch."""
            status = _status(
                state=SimulationState.PAUSED,
                paused=True,
                session_id="run-abc",
                queue_empty=False,
            )
            assert detect_session_mismatch(status, "run-old") is True

        def test_active_run_with_matching_session_is_ok(self):
            """EC-04: same session id → the page may resume the run."""
            status = _status(
                state=SimulationState.RUNNING,
                running=True,
                session_id="run-abc",
                queue_empty=False,
            )
            assert detect_session_mismatch(status, "run-abc") is False

        def test_idle_run_never_mismatches(self):
            """EC-04: no active run → no mismatch regardless of remembered session."""
            status = _status(state=SimulationState.IDLE)
            assert detect_session_mismatch(status, None) is False
            assert detect_session_mismatch(status, "run-abc") is False

        def test_completed_run_never_mismatches(self):
            """EC-04: a finished run is not resumable and not a mismatch."""
            status = _status(state=SimulationState.COMPLETED, queue_empty=True)
            assert detect_session_mismatch(status, "run-abc") is False

    # ------------------------------------------------------------------
    # §2.2 Service — start_simulation() (US-01, EC-01/05/06)
    # ------------------------------------------------------------------

    class TestStartSimulationService:
        """US-01/EC-01/EC-05/EC-06: launching a run from the queue snapshot."""

        @pytest.mark.asyncio
        async def test_start_empty_queue_raises_queue_empty(self, db_session):
            """EC-06/US-01 S2: no unprocessed tickets → no run may start."""
            with pytest.raises(SimulationQueueEmptyError) as exc:
                await start_simulation(db_session)
            status = exc.value.status
            assert status.started is False
            assert status.queue_empty is True
            assert status.state == SimulationState.IDLE
            assert status.message is not None

        @pytest.mark.asyncio
        async def test_start_while_running_raises_already_running(self, db_session):
            """EC-01: a second start while a run is active is refused."""
            manager = default_manager()
            manager.state = SimulationState.RUNNING
            with pytest.raises(SimulationAlreadyRunningError):
                await start_simulation(db_session)

        @pytest.mark.asyncio
        async def test_start_while_paused_raises_already_running(self, db_session):
            """EC-01: a paused run is still an active run — start is refused."""
            manager = default_manager()
            manager.state = SimulationState.PAUSED
            with pytest.raises(SimulationAlreadyRunningError):
                await start_simulation(db_session)

        @pytest.mark.asyncio
        async def test_start_non_finite_pace_raises(self, db_session):
            """EC-05: a NaN delay is refused before a run is launched."""
            await _seed_ticket(db_session, "N-001")
            with pytest.raises(SimulationPaceInvalidError):
                await start_simulation(db_session, pace_seconds=float("nan"))

        @pytest.mark.asyncio
        async def test_start_when_pipeline_unavailable_raises(self, db_engine, db_session):
            """EC-03 at start: queue cannot be built → 500 semantics."""
            await _seed_ticket(db_session, "N-001")
            await db_engine.dispose()
            with pytest.raises(SimulationPipelineUnavailableError):
                await start_simulation(db_session)

    # ------------------------------------------------------------------
    # §2.2 Service — pause/resume/stop (US-02 S2/S3)
    # ------------------------------------------------------------------

    class TestPauseResumeStopService:
        """US-02: the lifecycle commands behave per the state machine."""

        @pytest.mark.asyncio
        async def test_pause_running_run(self):
            """US-02 S2: pausing a running run returns a PAUSED snapshot."""
            manager = default_manager()
            manager.state = SimulationState.RUNNING
            status = await pause_simulation(manager=manager)
            assert status.state == SimulationState.PAUSED
            assert status.running is False
            assert status.paused is True

        @pytest.mark.asyncio
        async def test_pause_idle_raises(self):
            """§4.2: pausing without a running run → conflict (409)."""
            with pytest.raises(SimulationStateConflictError):
                await pause_simulation()

        @pytest.mark.asyncio
        async def test_resume_paused_run(self):
            """US-02 S2: resuming a paused run returns a RUNNING snapshot."""
            manager = default_manager()
            manager.state = SimulationState.PAUSED
            status = await resume_simulation(manager=manager)
            assert status.state == SimulationState.RUNNING

        @pytest.mark.asyncio
        async def test_resume_running_raises(self):
            """§4.3: resuming a running run → conflict (409)."""
            manager = default_manager()
            manager.state = SimulationState.RUNNING
            with pytest.raises(SimulationStateConflictError):
                await resume_simulation(manager=manager)

        @pytest.mark.asyncio
        async def test_resume_idle_raises(self):
            """§4.3: resuming with nothing paused → conflict (409)."""
            with pytest.raises(SimulationStateConflictError):
                await resume_simulation()

        @pytest.mark.asyncio
        async def test_stop_running_run_records_stopped_summary(self):
            """US-02 S3: stopping leaves unprocessed tickets queued and returns IDLE."""
            manager = default_manager()
            manager.state = SimulationState.RUNNING
            manager.queue = ["N-001", "N-002", "N-003"]
            manager.next_index = 1
            status = await stop_simulation(manager=manager)
            assert status.state == SimulationState.IDLE
            assert status.remaining_count == 2          # remaining tickets stay queued
            assert status.last_run_summary is not None
            assert status.last_run_summary.ended_by == "stopped"

        @pytest.mark.asyncio
        async def test_stop_paused_run_records_stopped_summary(self):
            """US-02 S3: a paused run may also be stopped."""
            manager = default_manager()
            manager.state = SimulationState.PAUSED
            status = await stop_simulation(manager=manager)
            assert status.state == SimulationState.IDLE
            assert status.last_run_summary.ended_by == "stopped"

        @pytest.mark.asyncio
        async def test_stop_idle_raises(self):
            """§4.4: stopping with nothing active → conflict (409)."""
            with pytest.raises(SimulationStateConflictError):
                await stop_simulation()

    # ------------------------------------------------------------------
    # §2.2 Service — get_simulation_status() (US-03, EC-04/EC-06)
    # ------------------------------------------------------------------

    class TestGetSimulationStatusService:
        """US-03 S1/S2: the status snapshot reflects the live run."""

        @pytest.mark.asyncio
        async def test_status_is_idle_by_default(self):
            """EC-06: idle status still succeeds with a valid snapshot."""
            status = await get_simulation_status()
            assert status.state == SimulationState.IDLE
            assert status.running is False
            assert status.paused is False

        @pytest.mark.asyncio
        async def test_status_reports_active_run_and_session(self):
            """EC-04: an active run exposes state, counts, and its session id."""
            manager = default_manager()
            manager.state = SimulationState.RUNNING
            manager.session_id = "run-abc"
            status = await get_simulation_status(manager=manager)
            assert status.state == SimulationState.RUNNING
            assert status.running is True
            assert status.session_id == "run-abc"

        @pytest.mark.asyncio
        async def test_status_reports_completed_run(self):
            """US-03 S2: a completed run carries completion time."""
            manager = default_manager()
            manager.state = SimulationState.COMPLETED
            manager.completed_at = "2026-08-08T10:02:00+00:00"
            status = await get_simulation_status(manager=manager)
            assert status.state == SimulationState.COMPLETED
            assert status.completed_at is not None

    # ------------------------------------------------------------------
    # §2.2 Service — advance_simulation() (US-01/03, EC-02/03, deterministic)
    # ------------------------------------------------------------------

    class TestAdvanceSimulationService:
        """Single-step deterministic runs via the mocked pipeline seam."""

        @pytest.mark.asyncio
        async def test_advance_processes_one_ticket(self, monkeypatch, db_session):
            """US-01 S1: one step lands the next ticket and updates progress."""
            monkeypatch.setattr(
                "app.services.simulation_service._process_ticket", _fake_process
            )
            manager = default_manager()
            manager.state = SimulationState.RUNNING
            manager.queue = ["N-001", "N-002"]
            manager.next_index = 0

            status = await advance_simulation(db_session, manager=manager)

            assert status.state == SimulationState.RUNNING
            assert status.processed_count == 1
            assert status.auto_resolved_count == 1
            assert status.remaining_count == 1
            assert status.last_landed_ticket_id == "N-001"
            assert "N-001" in status.recently_landed_ticket_ids
            assert manager.next_index == 1

        @pytest.mark.asyncio
        async def test_advance_lands_in_review_lane_by_outcome(self, monkeypatch, db_session):
            """BR-02: the lane comes from the outcome, never forced."""
            async def fake_review(db, ticket_id):
                return _entry(
                    ticket_id=ticket_id,
                    lane=DashboardLane.NEEDS_REVIEW,
                    auto_resolved=False,
                    confidence=0.3,
                )

            monkeypatch.setattr(
                "app.services.simulation_service._process_ticket", fake_review
            )
            manager = default_manager()
            manager.state = SimulationState.RUNNING
            manager.queue = ["N-001"]
            manager.next_index = 0

            status = await advance_simulation(db_session, manager=manager)

            assert status.needs_review_count == 1
            assert status.auto_resolved_count == 0
            assert status.lane_counts.needs_review == 1

        @pytest.mark.asyncio
        async def test_advance_completes_when_queue_exhausted(self, monkeypatch, db_session):
            """US-03 S2: processing the last ticket reaches COMPLETED."""
            monkeypatch.setattr(
                "app.services.simulation_service._process_ticket", _fake_process
            )
            manager = default_manager()
            manager.state = SimulationState.RUNNING
            manager.queue = ["N-001"]
            manager.next_index = 0

            status = await advance_simulation(db_session, manager=manager)

            assert status.state == SimulationState.COMPLETED
            assert status.processed_count == 1
            assert status.completed_at is not None
            assert status.message is not None

        @pytest.mark.asyncio
        async def test_advance_skips_unreadable_ticket(self, monkeypatch, db_session):
            """EC-02: an unreadable ticket is skipped and reported as a warning."""
            async def fake_unreadable(db, ticket_id):
                raise SimulationUnreadableTicketError()

            monkeypatch.setattr(
                "app.services.simulation_service._process_ticket", fake_unreadable
            )
            manager = default_manager()
            manager.state = SimulationState.RUNNING
            manager.queue = ["N-001", "N-002"]
            manager.next_index = 0

            status = await advance_simulation(db_session, manager=manager)

            assert status.skipped_count == 1
            assert len(status.warnings) == 1
            assert status.warnings[0].code == "unreadable_description"

        @pytest.mark.asyncio
        async def test_advance_propagates_pipeline_unavailable(self, monkeypatch, db_session):
            """EC-03: an unrecoverable pipeline failure is surfaced to the caller."""
            async def fake_broken(db, ticket_id):
                raise SimulationPipelineUnavailableError()

            monkeypatch.setattr(
                "app.services.simulation_service._process_ticket", fake_broken
            )
            manager = default_manager()
            manager.state = SimulationState.RUNNING
            manager.queue = ["N-001"]
            manager.next_index = 0

            with pytest.raises(SimulationPipelineUnavailableError):
                await advance_simulation(db_session, manager=manager)

        @pytest.mark.asyncio
        async def test_advance_is_noop_when_not_running(self, db_session):
            """§2.2: advancing an idle manager changes nothing."""
            manager = default_manager()
            manager.state = SimulationState.IDLE
            status = await advance_simulation(db_session, manager=manager)
            assert status.state == SimulationState.IDLE
            assert status.processed_count == 0

    # ------------------------------------------------------------------
    # §2.3 Manager — singleton + reset (BR-03, §8 note 1)
    # ------------------------------------------------------------------

    class TestSimulationManager:
        """§2.3: the single-flight runtime is one shared instance and resettable."""

        def test_default_manager_is_a_singleton(self):
            """BR-03: repeated access returns the same single-flight instance."""
            assert default_manager() is default_manager()

        def test_default_manager_is_a_simulation_manager(self):
            """§2.3: the singleton is a SimulationManager instance."""
            assert isinstance(default_manager(), SimulationManager)

        def test_reset_returns_manager_to_idle(self):
            """§8 note 1: resetting a busy manager yields a clean IDLE state."""
            manager = default_manager()
            manager.state = SimulationState.RUNNING
            manager.session_id = "run-abc"
            manager.queue = ["N-001", "N-002"]
            manager.next_index = 1

            reset_simulation_manager()

            assert manager.state == SimulationState.IDLE
            assert manager.session_id is None
            assert manager.queue == []
            assert manager.next_index == 0

    # ------------------------------------------------------------------
    # §4 API — POST /api/v1/simulation/start (US-01, EC-01/05/06)
    # ------------------------------------------------------------------

    class TestStartEndpoint:
        """`POST /api/v1/simulation/start`."""

        @pytest.mark.asyncio
        async def test_start_empty_queue_returns_200_informational(self, client):
            """EC-06/US-01 S2: no tickets left → 200 with queue_empty and message."""
            resp = await client.post("/api/v1/simulation/start", json={})
            assert resp.status_code == 200
            data = resp.json()
            assert data["started"] is False
            assert data["queue_empty"] is True
            assert data["state"] == "idle"
            assert data["message"]

        @pytest.mark.asyncio
        async def test_start_returns_409_when_already_running(self, client):
            """EC-01: a second start while a run is active → 409."""
            manager = default_manager()
            manager.state = SimulationState.RUNNING

            resp = await client.post("/api/v1/simulation/start", json={})
            assert resp.status_code == 409
            assert "already" in resp.json()["detail"]

        @pytest.mark.asyncio
        async def test_start_non_finite_pace_returns_422(self, client, db_session):
            """EC-05: a NaN delay is refused with 422.

            JSON cannot carry a literal NaN float, so the non-finite value is
            sent as the string "NaN"; model validation must refuse it (422).
            """
            await _seed_ticket(db_session, "N-001")

            resp = await client.post(
                "/api/v1/simulation/start", json={"pace_seconds": "NaN"}
            )
            assert resp.status_code == 422

        @pytest.mark.asyncio
        async def test_start_returns_500_when_pipeline_unavailable(self, client, db_engine, db_session):
            """EC-03 at start: an unavailable pipeline → 500."""
            await _seed_ticket(db_session, "N-001")
            await db_engine.dispose()

            resp = await client.post("/api/v1/simulation/start", json={})
            assert resp.status_code == 500
            assert "unavailable" in resp.json()["detail"].lower()

    # ------------------------------------------------------------------
    # §4 API — POST /api/v1/simulation/pause|resume|stop (US-02)
    # ------------------------------------------------------------------

    class TestPauseResumeStopEndpoint:
        """`POST /api/v1/simulation/pause|resume|stop`."""

        @pytest.mark.asyncio
        async def test_pause_running_returns_paused(self, client):
            """US-02 S2: pausing a running run → 200 PAUSED."""
            manager = default_manager()
            manager.state = SimulationState.RUNNING

            resp = await client.post("/api/v1/simulation/pause")
            assert resp.status_code == 200
            assert resp.json()["state"] == "paused"
            assert resp.json()["paused"] is True

        @pytest.mark.asyncio
        async def test_pause_idle_returns_409(self, client):
            """§4.2: pausing with no active run → 409."""
            resp = await client.post("/api/v1/simulation/pause")
            assert resp.status_code == 409

        @pytest.mark.asyncio
        async def test_resume_paused_returns_running(self, client):
            """US-02 S2: resuming a paused run → 200 RUNNING."""
            manager = default_manager()
            manager.state = SimulationState.PAUSED

            resp = await client.post("/api/v1/simulation/resume")
            assert resp.status_code == 200
            assert resp.json()["state"] == "running"

        @pytest.mark.asyncio
        async def test_resume_not_paused_returns_409(self, client):
            """§4.3: resuming without a paused run → 409."""
            resp = await client.post("/api/v1/simulation/resume")
            assert resp.status_code == 409

        @pytest.mark.asyncio
        async def test_stop_running_returns_idle_with_summary(self, client):
            """US-02 S3: stopping returns IDLE and records a stopped summary."""
            manager = default_manager()
            manager.state = SimulationState.RUNNING
            manager.queue = ["N-001", "N-002"]
            manager.next_index = 0

            resp = await client.post("/api/v1/simulation/stop")
            assert resp.status_code == 200
            data = resp.json()
            assert data["state"] == "idle"
            assert data["remaining_count"] == 2        # remaining tickets stay queued
            assert data["last_run_summary"] is not None
            assert data["last_run_summary"]["ended_by"] == "stopped"

        @pytest.mark.asyncio
        async def test_stop_idle_returns_409(self, client):
            """§4.4: stopping with nothing active → 409."""
            resp = await client.post("/api/v1/simulation/stop")
            assert resp.status_code == 409

    # ------------------------------------------------------------------
    # §4 API — GET /api/v1/simulation/status (US-03)
    # ------------------------------------------------------------------

    class TestStatusEndpoint:
        """`GET /api/v1/simulation/status`."""

        @pytest.mark.asyncio
        async def test_get_status_always_returns_200(self, client):
            """US-03 S1: the snapshot endpoint always succeeds, even when idle."""
            resp = await client.get("/api/v1/simulation/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["state"] == "idle"
            assert data["running"] is False
            assert data["queue_empty"] is True
            assert "processed_count" in data
            assert "lane_counts" in data

        @pytest.mark.asyncio
        async def test_get_status_exposes_live_run_state(self, client):
            """EC-04: an active run is visible with state, session, and counts."""
            manager = default_manager()
            manager.state = SimulationState.RUNNING
            manager.session_id = "run-abc"

            resp = await client.get("/api/v1/simulation/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["state"] == "running"
            assert data["running"] is True
            assert data["session_id"] == "run-abc"
