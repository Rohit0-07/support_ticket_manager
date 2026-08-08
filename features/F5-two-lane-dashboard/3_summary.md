# Feature Summary: Two-Lane Dashboard

| Metadata | Details |
|---|---|
| **Feature ID** | FEAT-005 (F5) |
| **Status** | Implemented & Verified |
| **Created Date** | 2026-08-08 |
| **Last Updated** | 2026-08-08 |

---

## 1. Capability Overview
- Read-only two-lane board ("Auto-Resolved" / "Needs Human Review") showing every processed ticket as a compact card — truncated description, action (or escalation), color-coded confidence — with per-lane count badges. Clicking a card opens a full detail view: complete description, top-3 similar past cases with scores, action, plain-language reasoning, refund amount, and the drafted customer reply. Both lanes always render (empty states included); a data-source failure shows a clear error with a Retry action.

## 2. Exported Interfaces & Capabilities
- **Pure Functions / Engine**:
  - `lane_for(auto_resolved: bool) -> DashboardLane` — BR-01 lane assignment (auto_resolved ↔ needs_review).
  - `confidence_level(score: float, high_threshold: float = 0.75, medium_threshold: float = 0.40) -> ConfidenceLevel` — Inclusive-bucket color coding (high ≥ 0.75, medium ≥ 0.40); `ValueError` on invalid score/thresholds.
  - `truncate_description(text: str, max_chars: int = 120) -> str` — Card preview with U+2026 ellipsis; `ValueError` when max_chars < 1.
- **Service Functions**:
  - `async build_board(db: AsyncSession) -> DashboardBoard` — Aggregates both lanes from `decision_log` + `new_tickets`, newest-first; `DashboardDataUnavailableError` → 500.
  - `async build_ticket_detail(db: AsyncSession, ticket_id: str) -> Optional[DashboardTicketDetail]` — Composes decision verbatim, F1 description, F4 reply, and recomputed top-3 evidence; returns None when no decision record exists (→ 404).
- **API Endpoints** (GET-only, BR-05):
  - `GET /api/v1/dashboard` — Full two-lane board payload.
  - `GET /api/v1/dashboard/tickets/{ticket_id}` — Full detail payload; 404 when no decision record.
- **Data Entities**: No new tables (read-only). Pydantic models: `DashboardLane`, `ConfidenceLevel`, `DashboardTicketCard`, `DashboardLaneSection`, `DashboardBoard`, `SimilarCaseEvidence`, `SimilarCasesStatus`, `ReplySummary`, `DashboardTicketDetail`. Reads F3 `decision_log`, F1 `new_tickets` / `resolved_tickets`, F4 `reply_log`.
- **Exceptions**: `DashboardError` (base), `DashboardDataUnavailableError` (→ 500), `DashboardTicketNotFoundError` (→ 404).
- **Frontend** (global JS): `loadDashboard()`, `renderBoard(board)`, `renderLane(section, laneClass)`, `renderCard(card)`, `openDetail(ticketId)`, `renderDetail(detail)`, `renderSimilarCases(cases)`, `showLoadError(message)`, `confidenceClass(level)`, `escapeHtml(text)`.

## 3. Dependent Features & Integration Points
- **F1 · Data Ingestion & Storage** — REQUIRED: reads `new_tickets` (card/detail descriptions) and `resolved_tickets` (evidence corpus) tables directly.
- **F2 · Similarity Engine** — REQUIRED: recomputes top-3 evidence + scores via pure `SimilarityIndex.fit` / `search` + `preprocess_description` (`app.services.similarity_engine`); deterministic so scores match decision time (BR-03).
- **F3 · Resolution Engine** — REQUIRED: reads `decision_log` (ORM `ResolutionDecisionLog`) for lane, action, confidence, escalation_reason, reasoning, refund_amount, created_at.
- **F4 · Reply Drafting** — REQUIRED: reads `reply_log` for the drafted reply in the detail view.
- **F6 · Human Override Controls** (planned) — downstream consumer of the Needs Human Review lane. **F7 · Live Ticket Simulation** (planned) — downstream consumer of the board endpoints.

## 4. Key Configuration & Constants
- `STM_DASHBOARD_PREVIEW_CHARS` — Card description truncation length (120).
- `STM_DASHBOARD_CONFIDENCE_HIGH` — High-confidence bucket floor (0.75).
- `STM_DASHBOARD_CONFIDENCE_MEDIUM` — Medium-confidence bucket floor (0.40).
- `STM_DASHBOARD_TOP_EVIDENCE` — Top-N evidence cases shown (3).
