from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

from app.models.resolution_models import (
    DecisionInput,
    EscalationReason,
    ResolutionAction,
    ResolutionDecision,
    ResolutionOutcome,
)
from app.models.similarity_models import SimilarityStatus


class ResolutionEngineError(Exception):
    """Base class for all resolution engine failures."""


class TicketNotFoundError(ResolutionEngineError):
    """Raised when the requested new ticket does not exist in F1 ``new_tickets``."""


class ResolutionPersistenceError(ResolutionEngineError):
    """Raised when a decision record cannot be written to ``decision_log``."""


# -- Action normalization -------------------------------------------------

REFUND_SYNONYMS = {"refund", "full_refund", "partial_refund", "refund_reissue"}
REDELIVERY_SYNONYMS = {"redelivery", "replacement", "re-delivery"}
COUPON_SYNONYMS = {"coupon"}


def canonicalize_action(raw_action: str) -> ResolutionAction:
    """Normalize a raw F1 ``action_taken`` string to a canonical ``ResolutionAction``.

    ``full_refund`` / ``partial_refund`` / ``refund_reissue`` / ``refund`` → ``REFUND``;
    ``redelivery`` / ``replacement`` / ``re-delivery`` → ``REDELIVERY``;
    ``coupon`` → ``COUPON``; anything else (including blank) → ``OTHER``.

    Args:
        raw_action: Raw ``action_taken`` value from a F1 resolved ticket.

    Returns:
        The canonical action class used for agreement checks.
    """
    normalized = (raw_action or "").strip().lower()
    if normalized in REFUND_SYNONYMS:
        return ResolutionAction.REFUND
    if normalized in REDELIVERY_SYNONYMS:
        return ResolutionAction.REDELIVERY
    if normalized in COUPON_SYNONYMS:
        return ResolutionAction.COUPON
    return ResolutionAction.OTHER


def precedents_agree(actions: Sequence[ResolutionAction]) -> bool:
    """True iff every canonical action in ``actions`` is identical (BR-01).

    An empty sequence returns True by convention (no disagreement).

    Args:
        actions: Canonicalized actions of the top-N precedents.

    Returns:
        True when ``len(set(actions)) <= 1``.
    """
    return len(set(actions)) <= 1


def most_common_action(actions: Sequence[ResolutionAction]) -> Optional[ResolutionAction]:
    """Return the modal canonical action for suggested-action display.

    Ties are broken deterministically by enum member order
    (REFUND < REDELIVERY < COUPON < OTHER). Returns None for an empty sequence.

    Args:
        actions: Canonicalized actions of the top-N precedents.

    Returns:
        The most frequent action, or None when ``actions`` is empty.
    """
    if not actions:
        return None
    counts: dict = {}
    for action in actions:
        counts[action] = counts.get(action, 0) + 1
    max_count = max(counts.values())
    candidates = [a for a, c in counts.items() if c == max_count]
    # Enum member order is defined declaration order; min() picks the first declared.
    return min(candidates, key=lambda a: list(ResolutionAction).index(a))


# -- Rule gates -----------------------------------------------------------

def confidence_meets_threshold(confidence: float, threshold: float) -> bool:
    """Evaluate the BR-02 confidence bar with the EC-08 boundary rule.

    Args:
        confidence: Match confidence in [0.0, 1.0].
        threshold: Required bar in [0.0, 1.0].

    Returns:
        ``confidence >= threshold`` — exactly-at-threshold counts as meeting
        the requirement (EC-08).
    """
    return confidence >= threshold


def action_allowed_by_order(action: ResolutionAction, order_status: str) -> bool:
    """Check whether order facts permit ``action`` (BR-04).

    Only one rule today: ``REDELIVERY`` is never allowed when the order status
    is ``cancelled`` (case-insensitive). All other actions are unrestricted by
    order status.

    Args:
        action: Canonical action to apply.
        order_status: Raw F1 ``orders_context.status`` string (may be blank).

    Returns:
        False when the action is blocked (EC-03); True otherwise.
    """
    if action == ResolutionAction.REDELIVERY and (order_status or "").strip().lower() == "cancelled":
        return False
    return True


def derive_proposed_refund(source_action: str, order_value: float, partial_ratio: float = 0.5) -> float:
    """Compute the refund amount implied by a precedent's raw action string (BR-05).

    ``full_refund`` / ``refund_reissue`` / ``refund`` → ``round(order_value, 2)``;
    ``partial_refund`` → ``round(order_value * partial_ratio, 2)``;
    any other raw action → ``0.0``.

    Args:
        source_action: Raw ``action_taken`` of a precedent.
        order_value: F1 ``orders_context.value`` in INR.
        partial_ratio: Fraction for partial refunds (default 0.5).

    Returns:
        Proposed refund amount in INR.
    """
    normalized = (source_action or "").strip().lower()
    if normalized in {"full_refund", "refund_reissue", "refund"}:
        return round(float(order_value), 2)
    if normalized == "partial_refund":
        return round(float(order_value) * float(partial_ratio), 2)
    return 0.0


def apply_refund_cap(proposed_refund: float, order_value: float) -> Tuple[float, bool]:
    """Cap a proposed refund at the order value (BR-05, EC-04).

    Args:
        proposed_refund: Refund amount implied by precedent evidence.
        order_value: F1 ``orders_context.value`` — the hard ceiling.

    Returns:
        ``(capped_amount, was_capped)`` where ``capped_amount = min(proposed_refund, order_value)``.
    """
    if proposed_refund > order_value:
        return round(float(order_value), 2), True
    return round(float(proposed_refund), 2), False


def _fmt(value: float) -> str:
    """Format a float with two decimal places for reasoning templates."""
    return f"{value:.2f}"


# -- Decision matrix ------------------------------------------------------

def evaluate_resolution(input: DecisionInput) -> ResolutionDecision:
    """Deterministically decide auto-resolve vs escalate for one ticket.

    Decision matrix (checked in this exact order; the first hit wins):

    1. ``precedent_status`` is ``CANNOT_MATCH``       → escalate ``cannot_match`` (EC-06)
    2. ``precedent_status`` is ``NO_HISTORY``         → escalate ``no_history`` (EC-05)
    3. ``precedent_status`` is ``NO_SIMILAR_CASES``   → escalate ``no_similar_cases`` (EC-01, BR-06)
    4. ``len(precedents) == 0``                       → escalate ``no_similar_cases`` (BR-06 guard)
    5. ``len(precedents) < expected_precedents``      → escalate ``insufficient_precedents`` (BR-01 guard)
    6. canonical actions disagree                     → escalate ``conflicting_precedents`` (US-02 S1, BR-03) —
       never choose a "winning" action; ``action`` = modal action as a suggestion only
    7. agreed action is ``OTHER``                     → escalate ``non_resolvable_action``
    8. ``action_allowed_by_order`` is False           → escalate ``blocked_by_order`` (US-02 S2, EC-03)
    9. ``confidence < threshold``                     → escalate ``low_confidence`` (US-01 S2, BR-02)
    10. action is ``REFUND`` and proposed refund (max across precedents) exceeds
        order value                                  → escalate ``refund_exceeds_order_value`` (EC-04, BR-05);
        ``refund_amount`` = capped amount
    11. otherwise                                    → **auto-resolve** (US-01 S1, BR-01/BR-02/BR-04)
        with ``action`` = agreed canonical action; ``refund_amount`` set for refunds

    ``confidence`` is the top precedent's similarity score. Reasoning strings
    are exact templates (see §3.3) so tests can assert on them.

    Args:
        input: Fully populated ``DecisionInput`` (service-built).

    Returns:
        A ``ResolutionDecision`` with outcome ``AUTO_RESOLVED`` or ``ESCALATED``.

    Raises:
        ResolutionEngineError: If ``input`` is malformed (e.g. confidence outside [0,1]).
    """
    now = input.created_at or datetime.now(timezone.utc).isoformat()
    precedents = list(input.precedents)
    evidence_ids = [p.ticket_id for p in precedents]
    actions = [canonicalize_action(p.action_taken) for p in precedents]
    modal = most_common_action(actions)
    action_value = modal.value if modal else None

    def escalated(reason: EscalationReason, reasoning: str, action=None, refund_amount=None) -> ResolutionDecision:
        return ResolutionDecision(
            ticket_id=input.ticket_id,
            order_id=input.order_id,
            description=input.description,
            outcome=ResolutionOutcome.ESCALATED,
            auto_resolved=False,
            action=action,
            escalation_reason=reason,
            confidence=input.confidence,
            similar_tickets=precedents,
            reasoning=reasoning,
            refund_amount=refund_amount,
            created_at=now,
        )

    # 1. Cannot match (EC-06)
    if input.precedent_status == SimilarityStatus.CANNOT_MATCH:
        return escalated(
            EscalationReason.CANNOT_MATCH,
            "Escalated: ticket description is blank or unreadable",
        )

    # 2. No history (EC-05)
    if input.precedent_status == SimilarityStatus.NO_HISTORY:
        return escalated(
            EscalationReason.NO_HISTORY,
            "Escalated: no resolved history available yet",
        )

    # 3. No similar cases status (EC-01, BR-06)
    if input.precedent_status == SimilarityStatus.NO_SIMILAR_CASES:
        return escalated(
            EscalationReason.NO_SIMILAR_CASES,
            "Escalated: no similar past cases found (novel issue)",
        )

    # 4. No precedent evidence at all (BR-06 guard)
    if not precedents:
        return escalated(
            EscalationReason.NO_SIMILAR_CASES,
            "Escalated: no similar past cases found (novel issue)",
        )

    # 5. Insufficient precedents (BR-01 guard)
    if len(precedents) < input.expected_precedents:
        return escalated(
            EscalationReason.INSUFFICIENT_PRECEDENTS,
            f"Escalated: only {len(precedents)} of {input.expected_precedents} expected precedents available",
        )

    # 6. Conflicting precedents (US-02 S1, BR-03) — always escalate, modal action suggested only
    if not precedents_agree(actions):
        distinct = sorted(set(actions), key=lambda a: list(ResolutionAction).index(a))
        labels = ", ".join(a.value for a in distinct)
        return escalated(
            EscalationReason.CONFLICTING_PRECEDENTS,
            f"Escalated: top {len(precedents)} precedents disagree on action ({labels}); never guessing",
            action=modal,
        )

    agreed_action = actions[0]

    # 7. Non-resolvable action (BR-06)
    if agreed_action == ResolutionAction.OTHER:
        return escalated(
            EscalationReason.NON_RESOLVABLE_ACTION,
            "Escalated: past cases agree on non-resolvable action 'other'",
            action=agreed_action,
        )

    # 8. Order facts block the action (US-02 S2, EC-03, BR-04)
    if not action_allowed_by_order(agreed_action, input.order_status):
        return escalated(
            EscalationReason.BLOCKED_BY_ORDER,
            f"Escalated: action '{agreed_action.value}' blocked because order "
            f"{input.order_id} status is '{input.order_status}'",
            action=agreed_action,
        )

    # 9. Confidence bar (US-01 S2, BR-02; EC-08 boundary handled by >=)
    if not confidence_meets_threshold(input.confidence, input.threshold):
        return escalated(
            EscalationReason.LOW_CONFIDENCE,
            f"Escalated: confidence {_fmt(input.confidence)} below threshold {_fmt(input.threshold)}",
            action=agreed_action,
        )

    # 10. Refund must not exceed the order value (EC-04, BR-05)
    refund_amount = None
    if agreed_action == ResolutionAction.REFUND:
        max_proposed = max(
            derive_proposed_refund(p.action_taken, input.order_value, input.partial_refund_ratio)
            for p in precedents
        )
        if max_proposed > input.order_value:
            capped, _ = apply_refund_cap(max_proposed, input.order_value)
            return escalated(
                EscalationReason.REFUND_EXCEEDS_ORDER_VALUE,
                f"Escalated: proposed refund {_fmt(max_proposed)} exceeds order value "
                f"{_fmt(input.order_value)}; capped at {_fmt(capped)} for human decision",
                action=agreed_action,
                refund_amount=capped,
            )
        refund_amount = round(max_proposed, 2)

    # 11. Auto-resolve (US-01 S1)
    reasoning = (
        f"Auto-resolved with action '{agreed_action.value}' "
        f"(confidence {_fmt(input.confidence)} >= threshold {_fmt(input.threshold)}; "
        f"top {len(precedents)} precedents agree: {', '.join(evidence_ids)})"
    )
    return ResolutionDecision(
        ticket_id=input.ticket_id,
        order_id=input.order_id,
        description=input.description,
        outcome=ResolutionOutcome.AUTO_RESOLVED,
        auto_resolved=True,
        action=agreed_action,
        escalation_reason=None,
        confidence=input.confidence,
        similar_tickets=precedents,
        reasoning=reasoning,
        refund_amount=refund_amount,
        created_at=now,
    )
