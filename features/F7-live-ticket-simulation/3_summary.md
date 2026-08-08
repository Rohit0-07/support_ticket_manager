# Feature Summary: Live Ticket Simulation

| Metadata | Details |
|---|---|
| **Feature ID** | FEAT-007 (F7) |
| **Status** | Implemented & Verified |
| **Created Date** | 2026-08-08 |
| **Last Updated** | 2026-08-08 |

---

## 1. Capability Overview
- Server-side, single-instance, in-memory simulation runtime that feeds unprocessed tickets into the system one at a time at a configurable pace, routing each through the standard processing pipeline and visibly landing it in the correct dashboard lane. Offers start/pause/resume/stop lifecycle control, live progress with per-lane counts, skip warnings for unreadable tickets, and session-mismatch handling after a page refresh.

## 2. Exported Interfaces & Capabilities
- **Pure Engine Functions**:
  - `validate_pace(pace_seconds: float) -> PaceValidationResult` — Clamps delay to configured min/max (EC-05); non-finite input → 422.
  - `validate_state_transition(current: SimulationState, command: SimulationCommand) -> SimulationState` — Lifecycle state machine; invalid transitions → 409.
  - `compute_lane_counts(entries: Sequence[ProcessedTicketEntry]) -> LaneCounts` — Per-lane landed totals for progress badges.
  - `detect_session_mismatch(status: SimulationStatusResponse, known_session_id: Optional[str]) -> bool` — EC-04 page-refresh detection.
- **Service Functions**:
  - `async start_simulation(db, pace_seconds: Optional[float] = None) -> SimulationStatusResponse` — Launches run from unprocessed queue; handles EC-01/05/06.
  - `async pause_simulation() -> SimulationStatusResponse` / `async resume_simulation() -> SimulationStatusResponse` — Halt/resume at tick boundaries.
  - `async stop_simulation() -> SimulationStatusResponse` — Early stop; returns to IDLE with `last_run_summary`.
  - `async get_simulation_status() -> SimulationStatusResponse` — Polled snapshot; always succeeds.
  - `async advance_simulation(db) -> SimulationStatusResponse` — Deterministic single-step hook (tests/tick loop).
  - `reset_simulation_manager() -> None` — Resets singleton runtime (test isolation).
- **Simulation Manager**: `SimulationManager` singleton runtime with `tick_loop(db_factory)` background pacing loop and `default_manager()` accessor.
- **API Endpoints**:
  - `POST /api/v1/simulation/start` — Start (200 launched / 200 empty-queue / 409 / 422 / 500).
  - `POST /api/v1/simulation/pause` · `POST /api/v1/simulation/resume` · `POST /api/v1/simulation/stop` — Lifecycle control (200 / 409).
  - `GET /api/v1/simulation/status` — Always-200 snapshot; frontend polls every 1s.
- **Data Entities**: No new tables. Pydantic models: `SimulationState`, `SimulationCommand`, `PaceValidationResult`, `LaneCounts`, `SimulationWarning`, `SimulationErrorInfo`, `ProcessedTicketEntry`, `SimulationRunSummary`, `StartSimulationRequest`, `SimulationStatusResponse`. Reads F1 `new_tickets`; persists via F3 `decision_log` / F4 `reply_log`.
- **Exceptions**: `SimulationError` base; `SimulationStateConflictError` + `SimulationAlreadyRunningError` (409), `SimulationPaceInvalidError` (422), `SimulationQueueEmptyError` (200 + final counts), `SimulationUnreadableTicketError` (internal skip), `SimulationPipelineUnavailableError` (500 start / auto-pause mid-run).

## 3. Dependent Features & Integration Points
- **F5 · Two-Lane Dashboard** — REQUIRED: consumes `GET /api/v1/dashboard` and `GET /api/v1/dashboard/tickets/{ticket_id}`; board refreshes after each landing.
- **F2 · Similarity Engine, F3 · Resolution Engine, F4 · Reply Drafting** — REQUIRED: each tick runs the existing pipeline via `resolution_service.resolve_ticket`.
- **F1 · Data Ingestion & Storage** — REQUIRED: queue = `new_tickets` rows lacking a `decision_log` entry.
- **F6 · Human Override Controls** — Compatible: simulated tickets in Needs Human Review remain actionable via F6 endpoints.

## 4. Key Configuration & Constants
- `STM_SIMULATION_DEFAULT_PACE_SECONDS` — Default arrival delay when omitted (3.0).
- `STM_SIMULATION_MIN_PACE_SECONDS` — Clamp floor for too-fast pace (1.0).
- `STM_SIMULATION_MAX_PACE_SECONDS` — Clamp ceiling for demos (30.0).
- `SIM_POLL_INTERVAL_MS` — Frontend status polling interval (1000 ms).
