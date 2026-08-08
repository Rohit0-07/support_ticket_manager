# Feature Summary: Resolution Engine

| Metadata | Details |
|---|---|
| **Feature ID** | FEAT-003 (F3) |
| **Status** | Implemented & Verified |
| **Created Date** | 2026-08-08 |
| **Last Updated** | 2026-08-08 |

---

## 1. Capability Overview
- Decides for each incoming ticket whether it can be auto-resolved (refund / redelivery / coupon) based on the top-3 similar past cases, match confidence, and order facts — or must be escalated to the human review lane. Every decision is deterministic, explained in plain language, and persisted to an auditable decision log.

## 2. Exported Interfaces & Capabilities
- **Pure Engine** (decision matrix, no I/O):
  - `canonicalize_action(raw_action: str) -> ResolutionAction` — Normalizes raw F1 action strings to refund/redelivery/coupon/other.
  - `precedents_agree(actions) -> bool` — True iff all canonical actions are identical (BR-01).
  - `most_common_action(actions) -> Optional[ResolutionAction]` — Modal action for suggestions; deterministic tie-break.
  - `confidence_meets_threshold(confidence, threshold) -> bool` — `>=` boundary rule (BR-02 / EC-08).
  - `action_allowed_by_order(action, order_status) -> bool` — Blocks redelivery on cancelled orders (BR-04).
  - `derive_proposed_refund(source_action, order_value, partial_ratio=0.5) -> float` — Refund implied by a precedent.
  - `apply_refund_cap(proposed_refund, order_value) -> Tuple[float, bool]` — Caps refund at order value (BR-05).
  - `evaluate_resolution(input: DecisionInput) -> ResolutionDecision` — Full decision matrix: auto-resolve vs escalate with exact reasoning.
  - Exceptions: `ResolutionEngineError` (base), `TicketNotFoundError`, `ResolutionPersistenceError`.
- **Service**:
  - `resolve_ticket(db, ticket_id) -> ResolutionDecision` — End-to-end resolve + persist (idempotent, keyed on ticket_id).
  - `list_decisions(db, skip=0, limit=50) -> Tuple[List[DecisionLogEntry], int]` — Audit log, newest first.
  - `get_decision(db, ticket_id) -> Optional[DecisionLogEntry]` — Single audit record.
  - `compute_resolution_stats(db) -> ResolutionStats` — Lane counts for the dashboard.
- **API Endpoints**:
  - `POST /api/v1/resolution/resolve` — Resolve a ticket; 200 carries `auto_resolved` + `escalation_reason`.
  - `GET /api/v1/resolution/decisions` — Paginated audit log (skip/limit).
  - `GET /api/v1/resolution/decisions/{ticket_id}` — Audit record for one ticket (404 if none).
  - `GET /api/v1/resolution/stats` — Aggregate auto/escalated/action/reason counts.
- **Data Entities**: New F3-owned `decision_log` table (ORM `ResolutionDecisionLog`). Models: `ResolutionRequest`, `DecisionInput`, `ResolutionDecision`, `DecisionLogEntry`, `DecisionListResponse`, `ResolutionStats`; enums `ResolutionAction`, `ResolutionOutcome`, `EscalationReason`. Reads F1 `new_tickets` / `orders_context`; uses F2 `SimilarTicket` + `SimilarityStatus`.

## 3. Dependent Features & Integration Points
- **F1 · Data Ingestion & Storage** — REQUIRED: reads persisted tickets and orders via `ticket_service`; missing ticket → 404, missing order → escalate `order_not_found`.
- **F2 · Similarity Engine** — REQUIRED: calls `similarity_service.find_similar` for top-N precedents; statuses `no_similar_cases` / `cannot_match` / `no_history` map directly to escalation.
- **F4 · Reply Drafting** — Downstream consumer of `ResolutionDecision` (action, outcome, evidence, reasoning).
- **F5 · Two-Lane Dashboard** — Downstream consumer of `auto_resolved` flag, `GET .../decisions`, and `GET .../stats`.

## 4. Key Configuration & Constants
- `STM_RESOLUTION_CONFIDENCE_THRESHOLD` — Auto-resolve confidence bar, default 0.75 (BR-02).
- `STM_RESOLUTION_TOP_N_PRECEDENTS` — Required agreeing precedent count, default 3 (BR-01).
- `STM_RESOLUTION_PARTIAL_REFUND_RATIO` — Fraction of order value for partial refunds, default 0.5 (BR-05).
