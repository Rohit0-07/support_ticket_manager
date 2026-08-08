"""Pure deterministic reply drafting engine (FEAT-004).

This module contains NO I/O: it renders exact customer-facing reply strings
from a ``ResolutionDecision`` (F3). The same decision always produces the
identical reply (BR-04), so it is safe to unit test without a database.

Contracts documented in ``features/F4-reply-drafting/2_tech_spec.md`` §2.2.
"""

from typing import List, Optional

from app.core.config import settings
from app.models.reply_models import DraftedReply, ReplyVariant
from app.models.resolution_models import ResolutionAction, ResolutionDecision, ResolutionOutcome


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
    return "\n\n".join(part for part in parts if part and part.strip())


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
    description = decision.description or ""
    if len(description.strip()) < settings.REPLY_MIN_QUOTE_CHARS:
        return ReplyVariant.ACKNOWLEDGMENT
    if decision.outcome == ResolutionOutcome.AUTO_RESOLVED:
        return ReplyVariant.ACTION_CONFIRMED
    return ReplyVariant.REVIEW_IN_PROGRESS


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
    text = (description or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    cut = text[:max_chars]
    # Prefer a whitespace-safe boundary inside the cut window (EC-06 readability).
    last_space = cut.rfind(" ")
    if last_space > 0:
        cut = cut[:last_space]
    return cut.rstrip() + "…"


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
    if action == ResolutionAction.REFUND:
        return "your order has been refunded"
    if action == ResolutionAction.REDELIVERY:
        return "a replacement delivery has been arranged for your order"
    if action == ResolutionAction.COUPON:
        return "a discount coupon has been added to your account"
    raise ReplyTemplateError(
        f"cannot render action statement for action={action!r}; auto-resolved decisions "
        "must carry a concrete refund/redelivery/coupon action"
    )


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
    if refund_amount is None:
        return ""
    return ACTION_CONFIRMED_REFUND_CLAUSE.format(amount=refund_amount)


def build_evidence_sentence(cited_ids: List[str]) -> str:
    """Render the evidence sentence, or "" when no evidence may be cited (BR-03, US-03).

    Args:
        cited_ids: Evidence past-case ticket ids actually present on the decision.

    Returns:
        ``"This action follows how we have handled similar past cases (reference: {ids})."``
        with ``ids`` comma-separated, or ``""`` when ``cited_ids`` is empty — the reply
        never references past cases that do not exist.
    """
    if not cited_ids:
        return ""
    return ACTION_CONFIRMED_EVIDENCE.format(ids=", ".join(cited_ids))


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
    variant = select_reply_variant(decision)

    if variant == ReplyVariant.ACKNOWLEDGMENT:
        return DraftedReply(
            variant=variant,
            reply_text=_join_paragraphs(
                [ACKNOWLEDGMENT_GREETING, ACKNOWLEDGMENT_BODY, ACKNOWLEDGMENT_CLOSING]
            ),
            cited_ticket_ids=[],
        )

    quote = truncate_quote(decision.description or "", settings.REPLY_MAX_QUOTE_CHARS)

    if variant == ReplyVariant.REVIEW_IN_PROGRESS:
        return DraftedReply(
            variant=variant,
            reply_text=_join_paragraphs(
                [
                    REVIEW_IN_PROGRESS_GREETING.format(quote=quote),
                    REVIEW_IN_PROGRESS_BODY,
                    REVIEW_IN_PROGRESS_CLOSING,
                ]
            ),
            cited_ticket_ids=[],
        )

    # ACTION_CONFIRMED
    action_statement = build_action_statement(decision.action)
    action_paragraph = ACTION_CONFIRMED_ACTION.format(action_statement=action_statement)
    action_paragraph += build_refund_clause(decision.refund_amount)

    cited_ids = [t.ticket_id for t in decision.similar_tickets][: settings.REPLY_MAX_EVIDENCE_CITES]
    evidence_paragraph = build_evidence_sentence(cited_ids)

    return DraftedReply(
        variant=variant,
        reply_text=_join_paragraphs(
            [
                ACTION_CONFIRMED_GREETING.format(quote=quote),
                action_paragraph,
                evidence_paragraph,
                ACTION_CONFIRMED_CLOSING,
            ]
        ),
        cited_ticket_ids=cited_ids,
    )
