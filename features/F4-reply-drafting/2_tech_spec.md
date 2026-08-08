# Technical Specification: Reply Drafting

| Metadata | Details |
|---|---|
| **Feature Name** | Reply Drafting |
| **Feature ID** | FEAT-004 (F4) |
| **Derived From** | `features/F4-reply-drafting/1_spec.md` |
| **Status** | Draft |
| **Author** | Technical Architect (AI) |
| **Created Date** | 2026-08-08 |

---

## 1. System Architecture & Components

### 1.1 Component Overview

The Reply Drafting feature is the customer-communication layer between the Resolution Engine (F3) and the Two-Lane Dashboard (F5). For every processed ticket it:

1. Obtains the authoritative **resolution decision** for the ticket from **F3** (`resolution_service.resolve_ticket`) — the chosen or suggested action, auto-resolve vs escalate outcome, evidence precedents, refund amount, and reasoning.
2. Selects a **deterministic reply template variant** based on the decision: `ACTION_CONFIRMED` (auto-resolved with evidence), `REVIEW_IN_PROGRESS` (escalated / no usable evidence), or `ACKNOWLEDGMENT` (ticket text missing or too short to reference).
3. Renders a **pure, deterministic customer-facing reply string** from exact templates (no external LLM dependency — BR-06 consistency).
4. Persists the reply to a new `reply_log` table that **preserves the original draft and any human edits** for audit (US-02 S1, EC-04).
5. Exposes edit / send endpoints so agents can send the draft as-is or edit it before sending.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Consumers: F5 Two-Lane Dashboard, F6 Human Override, test harness       │
└───────────────────────────────────┬──────────────────────────────────────┘
                                    │ POST /api/v1/replies/generate
                                    │ GET  /api/v1/replies
                                    │ GET  /api/v1/replies/{ticket_id}
                                    │ PUT  /api/v1/replies/{ticket_id}
                                    │ POST /api/v1/replies/{ticket_id}/send
                                    │ GET  /api/v1/replies/stats
┌───────────────────────────────────▼──────────────────────────────────────┐
│  routes/replies.py                    FastAPI router (thin)               │
└───────────────────────────────────┬──────────────────────────────────────┘
┌───────────────────────────────────▼──────────────────────────────────────┐
│  services/reply_service.py         Orchestration + persistence            │
│    - generate_reply(db, ticket_id) -> ReplyRecord                         │
│    - get_reply / list_replies / edit_reply / send_reply                   │
│    - compute_reply_stats(db) -> ReplyStats                                │
└───────────────────────────────────┬──────────────────────────────────────┘
┌───────────────────────────────────▼──────────────────────────────────────┐
│  services/reply_engine.py         Pure template logic (no I/O)            │
│    - select_reply_variant(decision) -> ReplyVariant                       │
│    - build_action_statement / build_refund_clause                         │
│    - build_evidence_sentence / truncate_quote                             │
│    - draft_reply(decision) -> DraftedReply                                │
└───────────────────────────────────┬──────────────────────────────────────┘
                                    │  depends on (reads / writes)
┌───────────────────────────────────▼──────────────────────────────────────┐
│  F3 service: resolution_service.resolve_ticket(db, ticket_id)             │
│  New table: reply_log (write)                                             │
└───────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Component Responsibility Matrix

| Component | File (convention) | Responsibility |
|---|---|---|
| Pydantic Models | `backend/app/models/reply_models.py` | Contracts: `GenerateReplyRequest`, `EditReplyRequest`, `SendReplyRequest`, `DraftedReply`, `ReplyRecord`, `ReplyListResponse`, `ReplyStats`; enums `ReplyVariant`, `ReplyStatus` |
| Reply Engine (pure) | `backend/app/services/reply_engine.py` | Deterministic template selection + rendering (US-01..US-03, EC-01..EC-06); no DB dependency; exact reply templates |
| Reply Service (orchestration) | `backend/app/services/reply_service.py` | Calls F3 `resolve_ticket`, invokes `draft_reply`, persists `reply_log` records, applies agent edits / sends, serves list/stats |
| API Router | `backend/app/routes/replies.py` | HTTP endpoints listed in §1.1 |
| ORM Model | `backend/app/models/db_models.py` | Add `ReplyLog` table |
| App Wiring | `backend/app/main.py` | Register `replies.router` |
| Config | `backend/app/core/config.py` | Add `REPLY_*` settings (env prefix `STM_`) |

### 1.3 Design Decisions (mapping business rules to mechanism)

| Business Rule (from `1_spec.md` §3) | Technical Mechanism |
|---|---|
| **BR-01** Every ticket gets a reply | `generate_reply()` re-runs F3's idempotent `resolve_ticket()` so a decision always exists before drafting; both `auto_resolved` and `escalated` decisions render a reply |
| **BR-02** Replies never over-promise | Escalated decisions (any `escalation_reason`) render `REVIEW_IN_PROGRESS` — the reply states a specialist is reviewing and explicitly says "No action has been finalized yet"; no action is stated or implied |
| **BR-03** Replies never invent evidence | Evidence sentence is rendered only for `ACTION_CONFIRMED` and only from the decision's actual `similar_tickets`; escalated decisions never cite past cases; empty evidence → evidence paragraph omitted entirely |
| **BR-04** Consistency (determinism) | `draft_reply` is a pure function over exact templates with exact parameter rules — the same `ResolutionDecision` always yields the identical reply string |
| **BR-05** Human edits are preserved | `reply_log` keeps immutable `original_draft` + `draft_history`; `generate_reply` never overwrites an agent's `final_body` once edited (EC-04); `send_reply` freezes `status = sent` |

### 1.4 Naming Consistency Notes

- **Reply variants** use the `action_confirmed | review_in_progress | acknowledgment` vocabulary defined in §2.1 (`ReplyVariant` enum), mirroring F2/F3's enum-per-decision style.
- **Ticket ids** reuse the F3 `ResolutionDecision.ticket_id` (`N-000` style) as the `reply_log` primary key — one reply per ticket, matching F3's `decision_log` idempotency convention.
- **Evidence ids** reuse the F2 `SimilarTicket.ticket_id` values (`H-1000` style) carried through `ResolutionDecision.similar_tickets`.
- **Timestamps** use ISO-8601 UTC strings (`created_at`, `edited_at`, `sent_at`), matching F1/F3 conventions.
- **JSON-string columns** (`cited_ticket_ids`, `draft_history`) use the same JSON-encoding style as F3's `decision_log.similar_ticket_ids`.
- **Money** uses INR with the `₹` symbol and two-decimal formatting (`f"{amount:.2f}"`), consistent with F1 `orders_context.value` (INR) and F3 `refund_amount`.

---

## 2. Interface Definitions & Function Signatures

> [!IMPORTANT]
> These signatures are the **CONTRACT** used by test-generators for unbiased TDD. They must be implemented exactly as documented.

### 2.1 Pydantic Models — `backend/app/models/reply_models.py`

```python
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ReplyVariant(str, Enum):
    """Deterministic template family selected from a resolution decision.

    ACTION_CONFIRMED  - auto-resolved ticket: reply states the action taken and,
                        when evidence exists, that it matches similar past cases (US-01 S1, US-03 S1)
    REVIEW_IN_PROGRESS - escalated ticket: reply states a specialist is reviewing and
                        does not promise/imply an action (US-01 S2, US-02 S2, US-03 S2,
                        EC-01, EC-02, EC-05)
    ACKNOWLEDGMENT    - ticket text missing or too short to reference: polite, complete
                        acknowledgment without pretending to know details (EC-03)
    """

    ACTION_CONFIRMED = "action_confirmed"
    REVIEW_IN_PROGRESS = "review_in_progress"
    ACKNOWLEDGMENT = "acknowledgment"


class ReplyStatus(str, Enum):
    """Lifecycle of a reply record in ``reply_log``."""

    DRAFT = "draft"   # not yet sent to the customer; agent may edit
    SENT = "sent"     # customer-facing version finalized (agent's edit or the draft as-is)


class GenerateReplyRequest(BaseModel):
    """Request body for the generate-reply endpoint."""

    ticket_id: str = Field(
        ...,
        min_length=1,
        examples=["N-002"],
        description="Id of the new/incoming ticket to draft a reply for (F1 new_tickets.ticket_id).",
    )


class EditReplyRequest(BaseModel):
    """Request body for editing an unsent reply draft (US-02 S1)."""

    body: str = Field(
        ...,
        min_length=1,
        examples=["Thank you for your patience — your replacement is on its way."],
        description="Agent's replacement reply wording. Must be non-empty.",
    )
    edited_by: Optional[str] = Field(
        None,
        examples=["agent-7"],
        description="Optional agent identifier recorded for audit (edited_at set alongside).",
    )


class SendReplyRequest(BaseModel):
    """Request body for sending a reply to the customer (US-02 S1)."""

    body: Optional[str] = Field(
        None,
        min_length=1,
        examples=["Thank you for your patience — your replacement is on its way."],
        description="Optional final wording. When provided, the reply is edited then sent in one step.",
    )
    edited_by: Optional[str] = Field(
        None,
        examples=["agent-7"],
        description="Optional agent identifier recorded for audit when a final edit is applied.",
    )


class DraftedReply(BaseModel):
    """Pure-engine output: the deterministic reply plus template metadata (no DB fields)."""

    variant: ReplyVariant = Field(..., description="Template family selected for this decision.")
    reply_text: str = Field(..., description="Full customer-facing reply string (exact template rendering).")
    cited_ticket_ids: List[str] = Field(
        default_factory=list,
        description="Evidence past-case ids actually referenced inside reply_text (empty for escalated/acknowledgment).",
    )


class ReplyRecord(BaseModel):
    """Full reply-log record exposed by the API (US-02 S1 audit trail)."""

    ticket_id: str = Field(..., description="FK to new_tickets.ticket_id; one reply per ticket.")
    variant: ReplyVariant
    original_draft: str = Field(
        ...,
        description="Immutable deterministic draft from the last generation (audit trail — EC-04).",
    )
    final_body: str = Field(
        ...,
        description="Customer-facing version: the agent's edit if edited, otherwise the original draft.",
    )
    status: ReplyStatus
    cited_ticket_ids: List[str] = Field(
        default_factory=list,
        description="Evidence ids referenced by the current original_draft.",
    )
    draft_history: List[str] = Field(
        default_factory=list,
        description="Chronological list of prior original_draft values superseded by re-generation (EC-04 audit).",
    )
    edited_by: Optional[str] = Field(None, description="Agent id that last edited final_body.")
    edited_at: Optional[str] = Field(None, description="ISO-8601 UTC timestamp of the last edit.")
    sent_at: Optional[str] = Field(None, description="ISO-8601 UTC timestamp when status became SENT.")
    created_at: str = Field(..., description="ISO-8601 UTC timestamp of record creation / last generation.")


class ReplyListResponse(BaseModel):
    """Offset-paginated reply log (matches F1/F3 pagination convention)."""

    total: int
    skip: int
    limit: int
    items: List[ReplyRecord]


class ReplyStats(BaseModel):
    """Aggregate counts for the dashboard / audit view."""

    total_replies: int
    draft_count: int
    sent_count: int
    by_variant: Dict[str, int] = Field(default_factory=dict, description="Counts keyed by ReplyVariant value.")
```

### 2.2 Pure Engine — `backend/app/services/reply_engine.py`

```python
from typing import List, Optional

from app.models.reply_models import DraftedReply, ReplyVariant
from app.models.resolution_models import ResolutionAction, ResolutionDecision


class ReplyEngineError(Exception):
    """Base class for all reply drafting engine failures."""


class ReplyTemplateError(ReplyEngineError):
    """Raised when a decision cannot be rendered under its selected variant.

    E.g. ``ACTION_CONFIRMED`` selected but ``decision.action`` is None/OTHER, or
    an unknown action cannot be mapped to a customer statement.
    """


# -- Exact, deterministic reply templates (BR-04) -------------------------

ACTION_CONFIRMED_GREETING = 'Thank you for contacting us about "{quote}".'
ACTION_CONFIRMED_ACTION = "We have resolved your issue: {action_statement}."
ACTION_CONFIRMED_REFUND_CLAUSE = " The amount of ₹{amount:.2f} has been returned to your original payment method."
ACTION_CONFIRMED_EVIDENCE = "This action follows how we have handled similar past cases (reference: {ids})."
ACTION_CONFIRMED_CLOSING = "We apologize for any inconvenience and appreciate your patience."

REVIEW_IN_PROGRESS_GREETING = 'Thank you for contacting us about "{quote}".'
REVIEW_IN_PROGRESS_BODY = (
    "We are currently reviewing your issue, and a support specialist will follow up "
    "with you shortly. No action has been finalized yet."
)
REVIEW_IN_PROGRESS_CLOSING = "We appreciate your patience while we look into this."

ACKNOWLEDGMENT_GREETING = "Thank you for contacting us."
ACKNOWLEDGMENT_BODY = (
    "We have received your ticket, and a support specialist is reviewing it. "
    "We will get back to you as soon as we have an update."
)
ACKNOWLEDGMENT_CLOSING = "We appreciate your patience."


def _join_paragraphs(parts: List[str]) -> str:
    """Join non-empty ``parts`` with a blank line (``\\n\\n``) — used by all templates."""
    ...


def select_reply_variant(decision: ResolutionDecision) -> ReplyVariant:
    """Choose the deterministic reply template family for a decision.

    Selection order (first hit wins):
      1. Description is missing or too short to reference
         (``len(description.strip()) < STM_REPLY_MIN_QUOTE_CHARS``) → ``ACKNOWLEDGMENT`` (EC-03)
      2. ``decision.outcome == AUTO_RESOLVED`` → ``ACTION_CONFIRMED`` (US-01 S1, US-03 S1)
      3. otherwise (any escalated decision, incl. no_similar_cases / conflicting_precedents /
         blocked_by_order / low_confidence / order_not_found) → ``REVIEW_IN_PROGRESS``
         (US-01 S2, US-02 S2, US-03 S2, EC-01, EC-02, EC-05)

    Args:
        decision: The full ``ResolutionDecision`` produced by F3.

    Returns:
        The ``ReplyVariant`` to render.
    """
    ...


def truncate_quote(description: str, max_chars: int = 120) -> str:
    """Prepare the short customer-facing quote of the ticket description (EC-06).

    Blank input returns "". Inputs at or below ``max_chars`` are returned trimmed.
    Longer inputs are cut at ``max_chars`` (on a whitespace-safe boundary, else hard
    cut), trailing whitespace removed, and an ellipsis ``…`` appended.

    Args:
        description: Raw ticket description text.
        max_chars: Hard ceiling for the quote length (default 120).

    Returns:
        The truncated quote, or "" when input is blank.
    """
    ...


def build_action_statement(action: Optional[ResolutionAction]) -> str:
    """Map a canonical action to the exact customer-facing action phrase (US-01 S1).

    Args:
        action: The canonical resolution action.

    Returns:
        One of:
          REFUND     → "your order has been refunded"
          REDELIVERY → "a replacement delivery has been arranged for your order"
          COUPON     → "a discount coupon has been added to your account"

    Raises:
        ReplyTemplateError: If ``action`` is None or ``OTHER`` — auto-resolved decisions
            must always carry a concrete action (BR-02/BR-03 guard).
    """
    ...


def build_refund_clause(refund_amount: Optional[float]) -> str:
    """Render the refund sentence fragment, or "" when no amount is available (EC-05).

    Args:
        refund_amount: Computed refund amount from the decision (may be None when
            the order value was unavailable or the action is not a refund).

    Returns:
        ``" The amount of ₹{amount:.2f} has been returned to your original payment method."``
        when ``refund_amount is not None``, else ``""`` — so the reply never invents
        order facts that are not confirmed.
    """
    ...


def build_evidence_sentence(cited_ids: List[str]) -> str:
    """Render the evidence sentence, or "" when no evidence may be cited (BR-03, US-03).

    Args:
        cited_ids: Evidence past-case ticket ids actually present on the decision.

    Returns:
        ``"This action follows how we have handled similar past cases (reference: {ids})."``
        with ``ids`` comma-separated, or ``""`` when ``cited_ids`` is empty — the reply
        never references past cases that do not exist.
    """
    ...


def draft_reply(decision: ResolutionDecision) -> DraftedReply:
    """Deterministically draft the customer-facing reply for a resolution decision.

    Variant behavior (see ``select_reply_variant`` for selection):

    - ``ACKNOWLEDGMENT``: renders the three acknowledgment paragraphs; no quote,
      no action, no evidence.
    - ``REVIEW_IN_PROGRESS``: renders greeting (quoted description), review body,
      and closing. Never cites evidence and never promises an action.
    - ``ACTION_CONFIRMED``: renders greeting (quoted description), the action
      sentence ``We have resolved your issue: {statement}.`` plus the refund clause
      when a refund amount is confirmed, the evidence sentence when at least one
      precedent exists, and the closing. Evidence ids are limited to
      ``STM_REPLY_MAX_EVIDENCE_CITES`` (default 3), in decision order.

    Paragraphs are joined with ``\\n\\n`` and empty optional paragraphs are omitted.
    The same decision always produces the exact same string (BR-04).

    Args:
        decision: The full ``ResolutionDecision`` produced by F3
            (``resolution_service.resolve_ticket``).

    Returns:
        A ``DraftedReply`` with ``variant``, the exact ``reply_text``, and the
        ``cited_ticket_ids`` referenced in the text.

    Raises:
        ReplyTemplateError: If ``ACTION_CONFIRMED`` is selected but the decision has
            no concrete action (None/OTHER) — invariant of F3 that should never fire.
    """
    ...
```

### 2.3 Orchestration Service — `backend/app/services/reply_service.py`

```python
import json
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import init_db
from app.models.db_models import ReplyLog
from app.models.reply_models import (
    DraftedReply,
    ReplyListResponse,
    ReplyRecord,
    ReplyStatus,
    ReplyStats,
    ReplyVariant,
)
from app.services import resolution_service
from app.services.reply_engine import (
    ReplyEngineError,
    ReplyTemplateError,
    draft_reply,
)
from app.services.resolution_engine import (
    ResolutionEngineError,
    TicketNotFoundError,
)
from app.services.similarity_engine import CorpusLoadError, SimilarityEngineError


class ReplyNotFoundError(ReplyEngineError):
    """Raised when no ``reply_log`` record exists for the requested ticket (→ 404)."""


class ReplyAlreadySentError(ReplyEngineError):
    """Raised when an agent tries to edit a reply that has already been sent (→ 409)."""


class InvalidReplyBodyError(ReplyEngineError):
    """Raised when an edit/send body is empty or whitespace-only (→ 422)."""


class ReplyPersistenceError(ReplyEngineError):
    """Raised when a ``reply_log`` record cannot be written (→ 500)."""


async def generate_reply(db: AsyncSession, ticket_id: str) -> ReplyRecord:
    """Draft (or re-draft) the reply for one ticket and persist it (US-01..US-03).

    Pipeline:
      1. Call ``resolution_service.resolve_ticket(db, ticket_id)`` to obtain the
         authoritative ``ResolutionDecision`` (idempotent; re-runs F2+F3 so a
         decision always exists — BR-01). ``TicketNotFoundError`` propagates (→ 404).
      2. ``draft_reply(decision)`` → deterministic ``DraftedReply``.
      3. Upsert a ``ReplyLog`` row keyed on ``ticket_id`` (one reply per ticket):
         - no existing row → create with ``original_draft = final_body = draft``,
           ``status = draft``;
         - existing row with ``status = sent`` → **return unchanged** — the
           customer-facing reply must keep reflecting the agent's final version (EC-04);
         - existing row with ``status = draft`` → append the prior ``original_draft``
           to ``draft_history`` (audit), refresh ``original_draft``/``variant``/cited ids;
           if never edited (``edited_by is None``) also refresh ``final_body``; if edited,
           **preserve ``final_body`` and the edit metadata** (EC-04).
      4. Persist and return the ``ReplyRecord``.

    Args:
        db: Async DB session.
        ticket_id: F1 ``new_tickets.ticket_id``.

    Returns:
        The persisted ``ReplyRecord`` (status ``draft`` unless already sent).

    Raises:
        TicketNotFoundError: If the ticket does not exist (→ 404).
        ResolutionEngineError / CorpusLoadError / SimilarityEngineError: On F2/F3
            dependency failure (→ 500).
        ReplyTemplateError / ReplyPersistenceError: On render or write failure (→ 500).
    """
    ...


async def get_reply(db: AsyncSession, ticket_id: str) -> Optional[ReplyRecord]:
    """Return a single reply record by ticket id, or None if never generated.

    Args:
        db: Async DB session.
        ticket_id: F1 ``new_tickets.ticket_id``.

    Returns:
        The ``ReplyRecord`` or None.
    """
    ...


async def list_replies(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[List[ReplyRecord], int]:
    """Return (items, total_count) for the reply log, newest first (US-02 audit).

    Args:
        db: Async DB session.
        skip: Offset for pagination.
        limit: Page size.

    Returns:
        A tuple of ``ReplyRecord`` rows (newest first) and the total count.
    """
    ...


async def edit_reply(
    db: AsyncSession,
    ticket_id: str,
    body: str,
    edited_by: Optional[str] = None,
) -> ReplyRecord:
    """Replace the customer-facing wording of an unsent draft (US-02 S1).

    Rules:
      - No record → ``ReplyNotFoundError`` (→ 404).
      - Empty/whitespace ``body`` → ``InvalidReplyBodyError`` (→ 422).
      - Already sent (``status == SENT``) → ``ReplyAlreadySentError`` (→ 409):
        sent replies are immutable to keep the audit trail intact.
      - Otherwise set ``final_body = body``, ``edited_by``, ``edited_at``; the
        ``original_draft`` and ``draft_history`` are untouched (BR-05). Status
        remains ``draft`` until ``send_reply``.

    Args:
        db: Async DB session.
        ticket_id: F1 ``new_tickets.ticket_id``.
        body: Agent's replacement wording (non-empty).
        edited_by: Optional agent identifier for audit.

    Returns:
        The updated ``ReplyRecord`` (status ``draft``).

    Raises:
        ReplyNotFoundError: No reply record (→ 404).
        InvalidReplyBodyError: Empty body (→ 422).
        ReplyAlreadySentError: Reply already sent (→ 409).
        ReplyPersistenceError: Write failure (→ 500).
    """
    ...


async def send_reply(
    db: AsyncSession,
    ticket_id: str,
    body: Optional[str] = None,
    edited_by: Optional[str] = None,
) -> ReplyRecord:
    """Send a reply to the customer, optionally applying a final edit (US-02 S1).

    Rules:
      - No record → ``ReplyNotFoundError`` (→ 404).
      - When ``body`` is provided it is validated and applied exactly like
        ``edit_reply`` (final edit) before sending.
      - When ``body`` is None the current ``final_body`` is sent as-is (draft or
        prior edit).
      - Already sent → return the record unchanged (idempotent).
      - Otherwise set ``status = sent`` and ``sent_at``; freeze the record.

    Args:
        db: Async DB session.
        ticket_id: F1 ``new_tickets.ticket_id``.
        body: Optional final wording (edit + send in one step).
        edited_by: Optional agent identifier for audit.

    Returns:
        The sent ``ReplyRecord`` (status ``sent``).

    Raises:
        ReplyNotFoundError: No reply record (→ 404).
        InvalidReplyBodyError: Empty ``body`` (→ 422).
        ReplyAlreadySentError: Not raised — sending an already-sent reply is idempotent.
        ReplyPersistenceError: Write failure (→ 500).
    """
    ...


async def compute_reply_stats(db: AsyncSession) -> ReplyStats:
    """Aggregate counts for the dashboard (F5 consumer).

    Args:
        db: Async DB session.

    Returns:
        ``ReplyStats`` with totals and per-variant breakdowns.
    """
    ...
```

### 2.4 API Router — `backend/app/routes/replies.py`

```python
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.reply_models import (
    EditReplyRequest,
    GenerateReplyRequest,
    ReplyListResponse,
    ReplyRecord,
    ReplyStats,
    SendReplyRequest,
)
from app.services import reply_service
from app.services.reply_engine import ReplyEngineError, ReplyTemplateError
from app.services.resolution_engine import ResolutionEngineError, TicketNotFoundError
from app.services.similarity_engine import CorpusLoadError, SimilarityEngineError

router = APIRouter(prefix="/api/v1", tags=["replies"])


@router.post("/replies/generate", response_model=ReplyRecord)
async def generate_reply_endpoint(
    payload: GenerateReplyRequest,
    db: AsyncSession = Depends(get_db),
) -> ReplyRecord:
    """Generate (and persist) the deterministic reply draft for one ticket."""
    try:
        return await reply_service.generate_reply(db, payload.ticket_id)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (CorpusLoadError, SimilarityEngineError, ResolutionEngineError, ReplyEngineError) as exc:
        raise HTTPException(status_code=500, detail=f"Reply drafting failed: {exc}") from exc


@router.get("/replies", response_model=ReplyListResponse)
async def list_replies_endpoint(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> ReplyListResponse:
    """List the full reply log, newest first (US-02 audit)."""
    try:
        items, total = await reply_service.list_replies(db, skip, limit)
    except ReplyEngineError as exc:
        raise HTTPException(status_code=500, detail=f"Reply drafting failed: {exc}") from exc
    return ReplyListResponse(total=total, skip=skip, limit=limit, items=items)


# NOTE: registered BEFORE /replies/{ticket_id} so the literal path "stats" is
# not captured by the {ticket_id} path parameter (see §8 note 5).
@router.get("/replies/stats", response_model=ReplyStats)
async def reply_stats_endpoint(
    db: AsyncSession = Depends(get_db),
) -> ReplyStats:
    """Return aggregate reply statistics for the dashboard (F5)."""
    try:
        return await reply_service.compute_reply_stats(db)
    except ReplyEngineError as exc:
        raise HTTPException(status_code=500, detail=f"Reply drafting failed: {exc}") from exc


@router.get("/replies/{ticket_id}", response_model=ReplyRecord)
async def get_reply_endpoint(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
) -> ReplyRecord:
    """Return the reply record for one ticket (US-02 detail view)."""
    try:
        record = await reply_service.get_reply(db, ticket_id)
    except ReplyEngineError as exc:
        raise HTTPException(status_code=500, detail=f"Reply drafting failed: {exc}") from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"no reply record for ticket {ticket_id}")
    return record


@router.put("/replies/{ticket_id}", response_model=ReplyRecord)
async def edit_reply_endpoint(
    ticket_id: str,
    payload: EditReplyRequest,
    db: AsyncSession = Depends(get_db),
) -> ReplyRecord:
    """Edit the customer-facing wording of an unsent draft (US-02 S1)."""
    try:
        return await reply_service.edit_reply(db, ticket_id, payload.body, payload.edited_by)
    except ReplyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReplyAlreadySentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidReplyBodyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ReplyEngineError as exc:
        raise HTTPException(status_code=500, detail=f"Reply drafting failed: {exc}") from exc


@router.post("/replies/{ticket_id}/send", response_model=ReplyRecord)
async def send_reply_endpoint(
    ticket_id: str,
    payload: Optional[SendReplyRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> ReplyRecord:
    """Send a reply to the customer (as-is or with a final edit)."""
    body = payload.body if payload else None
    edited_by = payload.edited_by if payload else None
    try:
        return await reply_service.send_reply(db, ticket_id, body, edited_by)
    except ReplyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidReplyBodyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ReplyEngineError as exc:
        raise HTTPException(status_code=500, detail=f"Reply drafting failed: {exc}") from exc
```

> [!IMPORTANT]
> Route ordering note: `GET /api/v1/replies/stats` must be registered **before**
> `GET /api/v1/replies/{ticket_id}` so the literal `stats` path is not captured by
> the `{ticket_id}` path parameter.

---

## 3. Data Models & Schemas

### 3.1 Database Table — `reply_log` (new, F4-owned)

Added to `backend/app/models/db_models.py` as `ReplyLog`:

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `ticket_id` | String | No (PK) | FK to `new_tickets.ticket_id`; one reply per ticket (re-generate upserts) |
| `variant` | String | No | `action_confirmed` \| `review_in_progress` \| `acknowledgment` |
| `original_draft` | String | No | Deterministic draft from the last generation (immutable audit record of the draft) |
| `final_body` | String | No | Customer-facing version: agent's edit if edited, else the draft |
| `status` | String | No | `draft` \| `sent` |
| `cited_ticket_ids` | String | No | JSON-encoded array of evidence ids, e.g. `["H-1000","H-1001","H-1002"]` |
| `edited_by` | String | Yes | Agent id that last edited `final_body` |
| `edited_at` | String | Yes | ISO-8601 UTC |
| `sent_at` | String | Yes | ISO-8601 UTC; set when `status` becomes `sent` |
| `draft_history` | String | Yes | JSON-encoded array of prior `original_draft` values superseded by re-generation (EC-04 audit) |
| `created_at` | String | No | ISO-8601 UTC |

### 3.2 JSON Response Schema (`ReplyRecord`)

```json
{
  "ticket_id": "N-002",
  "variant": "action_confirmed",
  "original_draft": "Thank you for contacting us about \"milk packet missing from my order\".\n\nWe have resolved your issue: your order has been refunded. The amount of ₹249.50 has been returned to your original payment method.\n\nThis action follows how we have handled similar past cases (reference: H-1000, H-1001, H-1002).\n\nWe apologize for any inconvenience and appreciate your patience.",
  "final_body": "Thank you for your patience — your replacement is on its way.",
  "status": "sent",
  "cited_ticket_ids": ["H-1000", "H-1001", "H-1002"],
  "draft_history": [],
  "edited_by": "agent-7",
  "edited_at": "2026-08-08T11:00:00.123456+00:00",
  "sent_at": "2026-08-08T11:01:00.123456+00:00",
  "created_at": "2026-08-08T10:20:00.123456+00:00"
}
```

| Field | Type | Nullable | Constraints |
|---|---|---|---|
| `ticket_id` | string | No | FK to `new_tickets.ticket_id` |
| `variant` | enum | No | `action_confirmed` \| `review_in_progress` \| `acknowledgment` |
| `original_draft` | string | No | Immutable per generation; appended to `draft_history` on re-generation |
| `final_body` | string | No | Non-empty; preserves agent edits (EC-04) |
| `status` | enum | No | `draft` \| `sent` |
| `cited_ticket_ids` | array[string] | No | Evidence ids referenced in `original_draft`; empty for escalated/acknowledgment |
| `draft_history` | array[string] | No | Prior drafts, oldest first |
| `edited_by` | string | Yes | Present iff an agent edited `final_body` |
| `edited_at` | string | Yes | ISO-8601 UTC |
| `sent_at` | string | Yes | ISO-8601 UTC; present iff `status == sent` |
| `created_at` | string | No | ISO-8601 UTC |

### 3.3 Reply Templates (exact, deterministic)

All paragraphs are joined with `\n\n`; empty optional paragraphs are omitted (`_join_paragraphs`).

**ACTION_CONFIRMED** (`variant = action_confirmed`)

| Paragraph | Template |
|---|---|
| 1. Greeting | `Thank you for contacting us about "{quote}".` |
| 2. Action (+ refund) | `We have resolved your issue: {action_statement}.` + ` The amount of ₹{amount:.2f} has been returned to your original payment method.` (refund clause omitted when `refund_amount` is None) |
| 3. Evidence (optional) | `This action follows how we have handled similar past cases (reference: {ids}).` (omitted when no evidence ids) |
| 4. Closing | `We apologize for any inconvenience and appreciate your patience.` |

Where:
- `{quote}` = `truncate_quote(description, STM_REPLY_MAX_QUOTE_CHARS)` — max 120 chars, `…` ellipsis when truncated (EC-06).
- `{action_statement}` = `build_action_statement(action)` → `your order has been refunded` | `a replacement delivery has been arranged for your order` | `a discount coupon has been added to your account`.
- `{ids}` = comma-separated evidence ticket ids, in decision order, limited to `STM_REPLY_MAX_EVIDENCE_CITES` (3).
- `{amount:.2f}` = `refund_amount` with two decimal places (only when present — EC-05).

**REVIEW_IN_PROGRESS** (`variant = review_in_progress`)

| Paragraph | Template |
|---|---|
| 1. Greeting | `Thank you for contacting us about "{quote}".` |
| 2. Review body | `We are currently reviewing your issue, and a support specialist will follow up with you shortly. No action has been finalized yet.` |
| 3. Closing | `We appreciate your patience while we look into this.` |

Never cites evidence, never states or implies an action (US-01 S2, US-02 S2, US-03 S2, EC-01, EC-02, EC-05).

**ACKNOWLEDGMENT** (`variant = acknowledgment`)

| Paragraph | Template |
|---|---|
| 1. Greeting | `Thank you for contacting us.` |
| 2. Body | `We have received your ticket, and a support specialist is reviewing it. We will get back to you as soon as we have an update.` |
| 3. Closing | `We appreciate your patience.` |

Used when the ticket description is missing or too short to reference (`len(description.strip()) < STM_REPLY_MIN_QUOTE_CHARS`) — polite, complete, and free of invented specifics (EC-03).

### 3.4 Configuration Additions — `backend/app/core/config.py`

```python
# Reply Drafting settings (env prefix: STM_)
REPLY_MIN_QUOTE_CHARS: int = 3      # EC-03: below this → ACKNOWLEDGMENT variant (no description quote)
REPLY_MAX_QUOTE_CHARS: int = 120    # EC-06: truncate long description quotes with "…"
REPLY_MAX_EVIDENCE_CITES: int = 3   # cite at most this many evidence ids (aligned to F3 top-N)
```

---

## 4. API Contracts

### 4.1 `POST /api/v1/replies/generate`

- **Purpose**: Generate and persist the deterministic customer-facing reply draft for one ticket. Ensures a resolution decision exists by re-running F3's idempotent `resolve_ticket`.
- **Request Body** (`GenerateReplyRequest`):
  ```json
  { "ticket_id": "N-002" }
  ```
  | Param | Type | Required | Constraints |
  |---|---|---|---|
  | `ticket_id` | string | Yes | `min_length=1`; must exist in `new_tickets` |

- **Response (200 OK)** — `ReplyRecord`
  - Auto-resolved example (see §3.2 with `variant: "action_confirmed"`, `status: "draft"`).
  - Escalated example:
    ```json
    {
      "ticket_id": "N-000",
      "variant": "review_in_progress",
      "original_draft": "Thank you for contacting us about \"fruits were rotten\".\n\nWe are currently reviewing your issue, and a support specialist will follow up with you shortly. No action has been finalized yet.\n\nWe appreciate your patience while we look into this.",
      "final_body": "Thank you for contacting us about \"fruits were rotten\".\n\nWe are currently reviewing your issue, and a support specialist will follow up with you shortly. No action has been finalized yet.\n\nWe appreciate your patience while we look into this.",
      "status": "draft",
      "cited_ticket_ids": [],
      "draft_history": [],
      "edited_by": null,
      "edited_at": null,
      "sent_at": null,
      "created_at": "2026-08-08T10:20:00.123456+00:00"
    }
    ```
  - If the ticket already has a **sent** reply, the existing record is returned unchanged (EC-04).
  - All spec edge cases are **business outcomes encoded in the reply text/variant** (a 200 response), not HTTP errors: EC-01..EC-06 map per §6.2.

- **Response (404 Not Found)**:
  ```json
  { "detail": "ticket not found: N-9999" }
  ```
  Raised when `ticket_id` does not exist in `new_tickets` (`TicketNotFoundError` from F3).

- **Response (422 Unprocessable Entity)** — FastAPI automatic validation: missing/empty `ticket_id`; malformed JSON body.
  ```json
  { "detail": [ { "loc": ["body", "ticket_id"], "msg": "...", "type": "..." } ] }
  ```

- **Response (500 Internal Server Error)**:
  ```json
  { "detail": "Reply drafting failed: <message>" }
  ```
  Raised on `CorpusLoadError` / `SimilarityEngineError` / `ResolutionEngineError` (F2/F3 dependency failure), `ReplyTemplateError` (render failure), or `ReplyPersistenceError` (write failure).

### 4.2 `GET /api/v1/replies?skip=0&limit=50`

- **Purpose**: List the full reply log, newest first (US-02 audit).
- **Query Params**: `skip` int ≥ 0 (default 0); `limit` int 1..500 (default 50).
- **Response (200 OK)** — `ReplyListResponse`:
  ```json
  {
    "total": 4,
    "skip": 0,
    "limit": 50,
    "items": [ { "ticket_id": "N-002", "variant": "action_confirmed", "...": "..." } ]
  }
  ```
- **Response (400)**: Not applicable (invalid query params → 422).
- **Response (404)**: Not applicable.
- **Response (500)**: Same shape as §4.1 on engine/db failure.

### 4.3 `GET /api/v1/replies/{ticket_id}`

- **Purpose**: Fetch the reply record for one ticket (US-02 detail view for F5).
- **Path Param**: `ticket_id` string.
- **Response (200 OK)** — `ReplyRecord` (single item shape from §4.1).
- **Response (404 Not Found)**:
  ```json
  { "detail": "no reply record for ticket N-9999" }
  ```
- **Response (500)**: Same shape as §4.1.

### 4.4 `PUT /api/v1/replies/{ticket_id}`

- **Purpose**: Edit the customer-facing wording of an **unsent** draft (US-02 S1). The deterministic `original_draft` is preserved for audit (BR-05).
- **Path Param**: `ticket_id` string.
- **Request Body** (`EditReplyRequest`):
  ```json
  { "body": "Thank you for your patience — your replacement is on its way.", "edited_by": "agent-7" }
  ```
  | Param | Type | Required | Constraints |
  |---|---|---|---|
  | `body` | string | Yes | `min_length=1`; non-empty |
  | `edited_by` | string | No | Agent identifier for audit |

- **Response (200 OK)** — `ReplyRecord` with `final_body` replaced, `edited_by`/`edited_at` set, `status` still `draft`, `original_draft` unchanged.
- **Response (404 Not Found)**:
  ```json
  { "detail": "no reply record for ticket N-9999" }
  ```
- **Response (409 Conflict)**:
  ```json
  { "detail": "reply already sent for ticket N-002" }
  ```
  Raised when the reply has `status == sent` — sent replies are immutable.
- **Response (422 Unprocessable Entity)**:
  - FastAPI validation for empty/missing `body`.
  - `InvalidReplyBodyError` → `{ "detail": "reply body must not be empty" }`.
- **Response (500)**: Same shape as §4.1.

### 4.5 `POST /api/v1/replies/{ticket_id}/send`

- **Purpose**: Send a reply to the customer — as-is (US-02 "send as-is") or with a final edit applied in one step (US-02 S1).
- **Path Param**: `ticket_id` string.
- **Request Body** (`SendReplyRequest`, optional):
  ```json
  { "body": "Thank you for your patience — your replacement is on its way.", "edited_by": "agent-7" }
  ```
  | Param | Type | Required | Constraints |
  |---|---|---|---|
  | `body` | string | No | When present, `min_length=1`; applies a final edit before sending |
  | `edited_by` | string | No | Agent identifier for audit |

  Sending with an empty body `{}` or `null` body sends the current `final_body` as-is.

- **Response (200 OK)** — `ReplyRecord` with `status: "sent"` and `sent_at` set. Idempotent: re-sending an already-sent reply returns the record unchanged.
- **Response (404 Not Found)**:
  ```json
  { "detail": "no reply record for ticket N-9999" }
  ```
- **Response (422 Unprocessable Entity)**:
  - FastAPI validation for empty `body` when provided.
  - `InvalidReplyBodyError` → `{ "detail": "reply body must not be empty" }`.
- **Response (500)**: Same shape as §4.1.

### 4.6 `GET /api/v1/replies/stats`

- **Purpose**: Aggregate counts for F5 lane/dashboard badges.
- **Response (200 OK)** — `ReplyStats`:
  ```json
  {
    "total_replies": 4,
    "draft_count": 3,
    "sent_count": 1,
    "by_variant": { "action_confirmed": 1, "review_in_progress": 3 }
  }
  ```
- **Response (400/404)**: Not applicable.
- **Response (500)**: Same shape as §4.1.

---

## 5. Error Types & Handling

```python
class ReplyEngineError(Exception):
    """Base class for all reply drafting failures."""


class ReplyTemplateError(ReplyEngineError):
    """Raised when a decision cannot be rendered under its selected variant
    (e.g. ACTION_CONFIRMED with action None/OTHER)."""


class ReplyNotFoundError(ReplyEngineError):
    """Raised when no reply_log record exists for the requested ticket."""


class ReplyAlreadySentError(ReplyEngineError):
    """Raised when an agent tries to edit a reply that has already been sent."""


class InvalidReplyBodyError(ReplyEngineError):
    """Raised when an edit/send body is empty or whitespace-only."""


class ReplyPersistenceError(ReplyEngineError):
    """Raised when a reply_log record cannot be written."""
```

| Error Code | Trigger | HTTP Status | User Message |
|---|---|---|---|
| ERR_001 | `TicketNotFoundError` (F3) — `ticket_id` not in `new_tickets` | 404 | `ticket not found: {ticket_id}` |
| ERR_002 | `ReplyNotFoundError` — no reply record for the ticket | 404 | `no reply record for ticket {ticket_id}` |
| ERR_003 | `ReplyAlreadySentError` — edit attempt on a sent reply | 409 | `reply already sent for ticket {ticket_id}` |
| ERR_004 | `ReplyPersistenceError` — `reply_log` write failure | 500 | `Reply drafting failed: {message}` |
| ERR_005 | `CorpusLoadError` / `SimilarityEngineError` / `ResolutionEngineError` — F2/F3 dependency failure | 500 | `Reply drafting failed: {message}` |
| ERR_006 | `ReplyTemplateError` / other `ReplyEngineError` — unexpected render failure | 500 | `Reply drafting failed: {message}` |
| ERR_007 | `InvalidReplyBodyError` — empty edit/send body | 422 | `reply body must not be empty` |
| ERR_008 | FastAPI validation — missing/empty `ticket_id`, empty `body`, malformed JSON, invalid query params | 422 | FastAPI-generated `detail` array |

> Business edge cases **EC-01..EC-06 are not HTTP errors**; they are encoded in the
> generated reply text and `variant` of a `200 OK` response so downstream consumers
> (F5/F6) and the audit log can act on them. See §6.2.

---

## 6. Spec-to-Component Traceability

### 6.1 User Stories

| User Story (from `1_spec.md`) | Technical Component | Function/Endpoint |
|---|---|---|
| US-01 · Receive a Clear, Empathetic Reply (S1: auto-resolved with strong precedent evidence) | Reply Engine | `select_reply_variant()` → `ACTION_CONFIRMED` · `build_action_statement()` · `build_evidence_sentence()` · `draft_reply()` · `POST /api/v1/replies/generate` |
| US-01 · Receive a Clear, Empathetic Reply (S2: escalated for human review — no action implied) | Reply Engine | `select_reply_variant()` → `REVIEW_IN_PROGRESS` · `draft_reply()` (never states/implies an action) |
| US-02 · Send a Ready-to-Use Draft (S1: edit and send; original draft preserved) | Reply Service + ORM | `edit_reply()` · `send_reply()` · `generate_reply()` preserving `original_draft`/`draft_history` · `PUT /api/v1/replies/{id}` · `POST /api/v1/replies/{id}/send` |
| US-02 · Send a Ready-to-Use Draft (S2: no usable precedent evidence — honest acknowledgment) | Reply Engine | `select_reply_variant()` → `REVIEW_IN_PROGRESS` · `draft_reply()` (no invented reason/action) |
| US-03 · Every Reply Explains Its Reasoning (S1: relevant past cases exist) | Reply Engine | `build_evidence_sentence()` citing `decision.similar_tickets` inside `ACTION_CONFIRMED` |
| US-03 · Every Reply Explains Its Reasoning (S2: past cases disagree / no strong match — no single-case citation) | Reply Engine | `select_reply_variant()` → `REVIEW_IN_PROGRESS` (no evidence sentence, no action promise) |

### 6.2 Edge Cases & Business Exceptions

| Edge Case (from `1_spec.md` §4) | Technical Component | Function/Mechanism |
|---|---|---|
| EC-01 · Escalated because no similar past cases found | Reply Engine | `select_reply_variant()` → `REVIEW_IN_PROGRESS`; no past-case mention, states specialist reviewing |
| EC-02 · Similar past cases conflict on action | Reply Engine | `REVIEW_IN_PROGRESS`; no action stated/implied, no case cited — "No action has been finalized yet" |
| EC-03 · Ticket text missing or too short to reference | Reply Engine | `select_reply_variant()` step 1 → `ACKNOWLEDGMENT`; polite acknowledgment with no invented specifics |
| EC-04 · Agent edits draft, ticket later re-processed | Reply Service + ORM | `generate_reply()` preserves `final_body`/`edited_by`/`edited_at` when edited; prior draft appended to `draft_history`; sent replies returned unchanged |
| EC-05 · Order details not available | Reply Engine | `build_refund_clause(None)` → `""`; escalated `order_not_found` decisions render `REVIEW_IN_PROGRESS` — no unavailable order facts cited |
| EC-06 · Very long description | Reply Engine | `truncate_quote(description, STM_REPLY_MAX_QUOTE_CHARS=120)` — reply stays short and readable |

### 6.3 Business Rules

| Business Rule (from `1_spec.md` §3) | Technical Component |
|---|---|
| BR-01 · Every ticket gets a reply | `generate_reply()` ensures a decision via F3 `resolve_ticket`, then always drafts + persists |
| BR-02 · Replies never over-promise | `REVIEW_IN_PROGRESS` template (no finalized action language) for every escalated decision |
| BR-03 · Replies never invent evidence | `build_evidence_sentence()` only for `ACTION_CONFIRMED` and only from real `similar_tickets`; empty → omitted |
| BR-04 · Consistency (same ticket → same reply) | Pure `draft_reply()` over exact templates — fully deterministic |
| BR-05 · Human edits are preserved | `original_draft` immutable per generation; `draft_history` audit trail; `edit_reply`/`send_reply` never mutate `original_draft` |

---

## 7. Sequence Diagrams

### 7.1 Primary Workflow — Generate a Reply (auto-resolve and escalate paths)

```mermaid
sequenceDiagram
    autonumber
    actor Consumer as F5/F6 / Test Harness
    participant API as FastAPI (routes/replies.py)
    participant SVC as reply_service
    participant F3 as resolution_service (F3)
    participant ENG as reply_engine (pure)
    participant LOG as SQLite (reply_log)

    Consumer->>API: POST /api/v1/replies/generate {ticket_id}
    API->>SVC: generate_reply(db, ticket_id)
    SVC->>F3: resolve_ticket(db, ticket_id)  (idempotent; ensures a decision — BR-01)
    alt ticket not found (ERR_001)
        F3-->>SVC: raise TicketNotFoundError
        SVC-->>API: propagate
        API-->>Consumer: 404 ticket not found
    end
    F3-->>SVC: ResolutionDecision(outcome, action, similar_tickets, refund_amount, ...)

    SVC->>ENG: draft_reply(decision)
    alt description blank/too short (EC-03)
        ENG-->>SVC: DraftedReply(variant=acknowledgment)
    else outcome = auto_resolved (US-01 S1, US-03 S1)
        ENG-->>SVC: DraftedReply(variant=action_confirmed, cited_ticket_ids=[H-1000,...])
    else outcome = escalated (US-01 S2 / EC-01 / EC-02 / EC-05)
        ENG-->>SVC: DraftedReply(variant=review_in_progress, cited_ticket_ids=[])
    end

    alt existing reply_log row status = sent (EC-04)
        LOG-->>SVC: existing sent row
        SVC-->>API: ReplyRecord (unchanged)
    else existing row status = draft (edited or not)
        SVC->>LOG: append prior original_draft to draft_history; refresh draft
        alt agent edited (edited_by set) (EC-04)
            LOG-->>SVC: preserve final_body + edit metadata
        else never edited
            LOG-->>SVC: final_body = new draft
        end
    else no existing row
        SVC->>LOG: insert ReplyLog(original_draft=final_body=draft, status=draft)
    end
    LOG-->>SVC: commit ok
    SVC-->>API: ReplyRecord
    API-->>Consumer: 200 ReplyRecord
```

### 7.2 Agent Workflow — Edit and Send a Draft (US-02 S1)

```mermaid
sequenceDiagram
    autonumber
    actor Agent as Support Agent
    participant API as FastAPI (routes/replies.py)
    participant SVC as reply_service
    participant LOG as SQLite (reply_log)

    Agent->>API: PUT /api/v1/replies/N-002 {"body": "...", "edited_by": "agent-7"}
    API->>SVC: edit_reply(db, "N-002", body, "agent-7")
    SVC->>LOG: SELECT * FROM reply_log WHERE ticket_id = 'N-002'
    alt no record (ERR_002)
        LOG-->>SVC: None
        SVC-->>API: raise ReplyNotFoundError
        API-->>Agent: 404 no reply record for ticket N-002
    end
    LOG-->>SVC: row (status=draft)
    SVC->>LOG: UPDATE final_body, edited_by, edited_at (original_draft untouched — BR-05)
    LOG-->>SVC: commit ok
    SVC-->>API: ReplyRecord(status=draft, final_body="...", edited_by="agent-7")
    API-->>Agent: 200 updated draft

    Agent->>API: POST /api/v1/replies/N-002/send {}
    API->>SVC: send_reply(db, "N-002", body=None, edited_by=None)
    SVC->>LOG: SELECT * FROM reply_log WHERE ticket_id = 'N-002'
    LOG-->>SVC: row (status=draft, final_body=edited)
    SVC->>LOG: UPDATE status='sent', sent_at=now
    LOG-->>SVC: commit ok
    SVC-->>API: ReplyRecord(status=sent, final_body=edited version, original_draft=deterministic draft)
    API-->>Agent: 200 sent reply (customer receives edited version; original draft preserved)
```

### 7.3 Edge Case — Re-generation Preserves Agent Edits (EC-04)

```mermaid
sequenceDiagram
    autonumber
    actor System as Re-process trigger (F7 / F6 override)
    participant SVC as reply_service
    participant F3 as resolution_service (F3)
    participant ENG as reply_engine (pure)
    participant LOG as SQLite (reply_log)

    System->>SVC: generate_reply(db, "N-002")  (ticket re-processed)
    SVC->>F3: resolve_ticket(db, "N-002")
    F3-->>SVC: ResolutionDecision (possibly changed)
    SVC->>ENG: draft_reply(decision)
    ENG-->>SVC: DraftedReply(variant, reply_text)
    SVC->>LOG: SELECT * FROM reply_log WHERE ticket_id = 'N-002'
    LOG-->>SVC: row (status=draft, edited_by="agent-7", final_body="agent wording")
    SVC->>LOG: draft_history += [old original_draft]; original_draft = new reply_text
    SVC->>LOG: final_body stays "agent wording"; edited_by/edited_at preserved
    LOG-->>SVC: commit ok
    SVC-->>System: ReplyRecord(original_draft=new, final_body=agent wording, draft_history=[old])
```

---

## 8. Implementation Notes for Downstream Stages

1. **Dependencies**: F4 requires **F3** (`resolution_service.resolve_ticket`), which transitively requires **F1** (ticket/order tables) and **F2** (`similarity_service.find_similar`). `generate_reply` calls F3's service function **in-process** (no HTTP hop) — same convention as F3 calling F2. If F1 seeding has not run, F3 escalates every ticket (`no_history`) and F4 renders `REVIEW_IN_PROGRESS` replies (acceptable and honest).
2. **New table**: `reply_log` (ORM `ReplyLog`) is F4-owned. Use plain `String` columns and JSON-string encoding for `cited_ticket_ids` and `draft_history`, matching F1/F3 SQLite conventions (no native JSON column type).
3. **Determinism guarantee**: `draft_reply` is a pure function with exact template constants (§3.3), a fixed variant-selection order, and precise formatting rules. The same `ResolutionDecision` always produces the identical reply string (BR-04). Tests may assert exact substrings such as `"We have resolved your issue: your order has been refunded."`, `"reference: H-1000, H-1001, H-1002"`, and `"No action has been finalized yet."`.
4. **Config**: `REPLY_*` settings live in `backend/app/core/config.py` under the existing `STM_` env prefix, alongside the `SIMILARITY_*` and `RESOLUTION_*` blocks.
5. **Route ordering**: register `GET /api/v1/replies/stats` before `GET /api/v1/replies/{ticket_id}` so the literal `stats` path is not captured by the path parameter.
6. **Downstream consumers**:
   - **F5 · Two-Lane Dashboard** reads `GET /api/v1/replies/{ticket_id}` (or the reply list) to display the drafted reply on each ticket card, and `GET /api/v1/replies/stats` for lane badges.
   - **F6 · Human Override Controls** re-invokes `POST /api/v1/replies/generate` after a decision changes; EC-04 guarantees an agent's already-edited/sent reply is never silently overwritten.
7. **Idempotency**: `generate_reply` upserts `reply_log` keyed on `ticket_id`; `send_reply` is idempotent for already-sent replies; `edit_reply` rejects edits to sent replies (409) to protect the audit trail. This supports F7 live simulation re-runs.
