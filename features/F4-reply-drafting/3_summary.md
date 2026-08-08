# Feature Summary: Reply Drafting

| Metadata | Details |
|---|---|
| **Feature ID** | FEAT-004 (F4) |
| **Status** | Implemented & Verified |
| **Created Date** | 2026-08-08 |
| **Last Updated** | 2026-08-08 |

---

## 1. Capability Overview
- Generates a deterministic, empathetic customer-facing reply for every ticket by consuming the resolution decision and choosing one of three template families (action confirmed / review in progress / acknowledgment). Agents can edit an unsent draft or send it as-is; the original draft and all human edits are preserved in an auditable log.

## 2. Exported Interfaces & Capabilities
- **Pure Engine** (deterministic templates, no I/O):
  - `select_reply_variant(decision: ResolutionDecision) -> ReplyVariant` — Picks template family from outcome + description length.
  - `truncate_quote(description: str, max_chars: int = 120) -> str` — Safe description quote with `…` ellipsis.
  - `build_action_statement(action: Optional[ResolutionAction]) -> str` — Maps action to exact customer phrase (`ReplyTemplateError` for None/OTHER).
  - `build_refund_clause(refund_amount: Optional[float]) -> str` — INR refund sentence or `""` when amount unconfirmed.
  - `build_evidence_sentence(cited_ids: List[str]) -> str` — Cites real precedent ids or `""` when none.
  - `draft_reply(decision: ResolutionDecision) -> DraftedReply` — Full deterministic reply text + cited ids.
  - Exceptions: `ReplyEngineError` (base), `ReplyTemplateError`.
- **Service**:
  - `generate_reply(db, ticket_id) -> ReplyRecord` — Draft + persist via F3 resolve; one record per ticket (preserves edits, never overwrites sent).
  - `get_reply(db, ticket_id) -> Optional[ReplyRecord]` — Single record lookup.
  - `list_replies(db, skip=0, limit=50) -> Tuple[List[ReplyRecord], int]` — Paginated audit log, newest first.
  - `edit_reply(db, ticket_id, body, edited_by=None) -> ReplyRecord` — Replace final_body of an unsent draft.
  - `send_reply(db, ticket_id, body=None, edited_by=None) -> ReplyRecord` — Freeze as sent, optionally with final edit (idempotent).
  - `compute_reply_stats(db) -> ReplyStats` — Draft/sent/variant counts for the dashboard.
  - Exceptions: `ReplyNotFoundError`, `ReplyAlreadySentError`, `InvalidReplyBodyError`, `ReplyPersistenceError`.
- **API Endpoints**:
  - `POST /api/v1/replies/generate` — Generate + persist reply draft (404 unknown ticket).
  - `GET /api/v1/replies` — Paginated reply log.
  - `GET /api/v1/replies/stats` — Aggregate stats (registered before `{ticket_id}` route).
  - `GET /api/v1/replies/{ticket_id}` — One reply record (404 if none).
  - `PUT /api/v1/replies/{ticket_id}` — Edit unsent draft (409 if already sent).
  - `POST /api/v1/replies/{ticket_id}/send` — Send as-is or with final edit.
- **Data Entities**: New F4-owned `reply_log` table (ORM `ReplyLog`). Models: `GenerateReplyRequest`, `EditReplyRequest`, `SendReplyRequest`, `DraftedReply`, `ReplyRecord`, `ReplyListResponse`, `ReplyStats`; enums `ReplyVariant`, `ReplyStatus`.

## 3. Dependent Features & Integration Points
- **F3 · Resolution Engine** — REQUIRED: `generate_reply` calls `resolution_service.resolve_ticket` for the authoritative decision (action, outcome, similar_tickets, refund_amount); `TicketNotFoundError` → 404.
- **F1 · Data Ingestion & Storage** — Indirect: supplies tickets/orders; **F2 · Similarity Engine** supplies precedent evidence (both flow through F3).
- **F5 · Two-Lane Dashboard** — Downstream consumer of reply records and `GET .../stats`.
- **F6 · Human Override Controls** — Downstream: replies must reflect the final decision after override.

## 4. Key Configuration & Constants
- `STM_REPLY_MIN_QUOTE_CHARS` — Description shorter than this → ACKNOWLEDGMENT variant, default 3.
- `STM_REPLY_MAX_QUOTE_CHARS` — Quote truncation ceiling, default 120.
- `STM_REPLY_MAX_EVIDENCE_CITES` — Max cited evidence ids, default 3.
