# Feature Summary: Human Override Controls

| Metadata | Details |
|---|---|
| **Feature ID** | FEAT-006 (F6) |
| **Status** | Implemented & Verified |
| **Created Date** | 2026-08-08 |
| **Last Updated** | 2026-08-08 |

---

## 1. Capability Overview
- Lets an identified support agent act on tickets in the **Needs Human Review** lane: **approve** the suggested action, **override** it with a different action (optionally editing the drafted reply), or **reject** it with a mandatory reason. Every decision is recorded with agent identity and timestamp in a new audit log; approve/override move the ticket to the Auto-Resolved lane, while rejected tickets stay visible but final (one decision per ticket).

## 2. Exported Interfaces & Capabilities
- **Engine functions** (pure, no I/O):
  - `normalize_override_action(action: str) -> ResolutionAction` — Validates/canonicalizes override action to refund/redelivery/coupon (raises `HumanDecisionInvalidActionError`).
  - `validate_override_policy(action: ResolutionAction, order_status: str) -> None` — Blocks policy-violating overrides (e.g. redelivery on cancelled orders) via F3 rules; raises `HumanDecisionPolicyBlockedError`.
  - `validate_rejection_reason(reason: str) -> None` — Requires non-blank reason; raises `HumanDecisionInvalidReasonError`.
  - `final_refund_for(action, order_value: float, refund_ratio: float = 1.0) -> Optional[float]` — Capped manual refund amount for refund actions (else None).
- **Service functions**:
  - `async approve_ticket(db, ticket_id: str, agent_id: str) -> HumanDecisionRecord` — Approve suggestion; flips `decision_log.auto_resolved`, inserts audit row.
  - `async override_ticket(db, ticket_id, agent_id, action: ResolutionAction, reply_body: Optional[str] = None) -> HumanDecisionRecord` — Replace suggestion (+ optional reply edit via F4); policy-gated, lane move, audit row.
  - `async reject_ticket(db, ticket_id, agent_id, reason: str) -> HumanDecisionRecord` — Record rejection; ticket stays in review lane but final, suggestion never applied.
  - `async list_human_decisions(db, skip=0, limit=50) -> Tuple[List[HumanDecisionRecord], int]` — Paginated audit history, newest first.
  - `async get_human_decision(db, ticket_id: str) -> Optional[HumanDecisionRecord]` — Handled-status lookup.
- **API Endpoints**:
  - `POST /api/v1/human-decisions/{ticket_id}/approve` — Approve suggestion (200/404/409/422/500).
  - `POST /api/v1/human-decisions/{ticket_id}/override` — Override with new action + optional edited reply.
  - `POST /api/v1/human-decisions/{ticket_id}/reject` — Reject with mandatory reason.
  - `GET /api/v1/human-decisions` — Paginated history (skip/limit, newest first; empty history = 200).
  - `GET /api/v1/human-decisions/{ticket_id}` — One decision (404 if none).
- **Data Entities**: New F6-owned `human_decision_log` table (ORM `HumanDecisionLog`, PK `ticket_id` enforces one-decision-per-ticket). Models: `HumanAction`, `ApproveRequest`, `OverrideRequest`, `RejectRequest`, `HumanDecisionRecord`, `HumanDecisionListResponse`.

## 3. Dependent Features & Integration Points
- **F5 · Two-Lane Dashboard** — REQUIRED: acts on tickets surfaced in the Needs Human Review lane; approve/override move tickets to Auto-Resolved by flipping `decision_log.auto_resolved` (no F5 contract change).
- **F3 · Resolution Engine** — REQUIRED: reads `decision_log` for suggested action/lane; reuses `action_allowed_by_order` and `apply_refund_cap` so human overrides honor the same policy rules.
- **F4 · Reply Drafting** — REQUIRED: override with a non-blank reply persists the edit via reply edit semantics; edited text recorded as `final_reply`.
- **F1 · Data Ingestion & Storage** — Reads `orders_context` (status/value) for the override policy gate and refund derivation.

## 4. Key Configuration & Constants
- `STM_HUMAN_OVERRIDE_REFUND_RATIO` — Fraction of order value for a manual refund, default 1.0 (capped at order value).
