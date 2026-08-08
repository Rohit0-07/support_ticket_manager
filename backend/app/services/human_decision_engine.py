"""Pure, I/O-free decision helpers for the Human Override Controls feature (FEAT-006).

Contracts documented in ``features/F6-human-override-controls/2_tech_spec.md`` §2.2.
The human lane reuses F3's order-context policy (``action_allowed_by_order``) and
refund cap (``apply_refund_cap``) so a manual override can never violate the
constraints the engine already enforces (US-02 S2 / EC-02, BR-05).
"""

from typing import Optional

from app.models.resolution_models import ResolutionAction
from app.services.resolution_engine import action_allowed_by_order, apply_refund_cap


class HumanDecisionEngineError(Exception):
    """Base class for all F6 human-decision engine errors."""


class HumanDecisionPolicyBlockedError(HumanDecisionEngineError):
    """Raised when an override action violates order-context policy (→ 422, EC-02/US-02 S2)."""


class HumanDecisionInvalidReasonError(HumanDecisionEngineError):
    """Raised when a rejection has no reason (→ 422, EC-03/US-03 S2)."""


class HumanDecisionInvalidActionError(HumanDecisionEngineError):
    """Raised when an override action is not refund/redelivery/coupon (→ 422, ERR_HUM_008)."""


def normalize_override_action(action: str) -> ResolutionAction:
    """Validate and canonicalize an override action string (US-02).

    Only the three applicable actions are accepted: 'refund', 'redelivery',
    'coupon'. F3's 'other' is a history-only marker that a human can never
    select as a final action.

    Args:
        action: Raw action string from the override request.

    Returns:
        The canonical ResolutionAction.

    Raises:
        HumanDecisionInvalidActionError: If ``action`` is not one of
            refund/redelivery/coupon (case-insensitive), including 'other'.
    """
    normalized = (action or "").strip().lower()
    for candidate in (
        ResolutionAction.REFUND,
        ResolutionAction.REDELIVERY,
        ResolutionAction.COUPON,
    ):
        if normalized == candidate.value:
            return candidate
    raise HumanDecisionInvalidActionError(
        "invalid override action: choose 'refund', 'redelivery', or 'coupon'"
    )


def validate_override_policy(action: ResolutionAction, order_status: str) -> None:
    """Enforce order-context policy on a manual override (US-02 S2, EC-02).

    Delegates to the F3 rule ``action_allowed_by_order`` so the human lane
    honors exactly the same constraint the engine enforces at decision time:
    ``redelivery`` is never allowed when the order status is ``cancelled``.

    Args:
        action: The override's final action.
        order_status: Raw F1 ``orders_context.status`` string (may be blank).

    Raises:
        HumanDecisionPolicyBlockedError: When the action is not allowed for
            this order (e.g. redelivery on a cancelled order).
    """
    if not action_allowed_by_order(action, order_status):
        raise HumanDecisionPolicyBlockedError(
            "redelivery is not allowed for cancelled orders"
        )


def validate_rejection_reason(reason: str) -> None:
    """Require a non-blank reason for a rejection (US-03 S2, EC-03).

    Args:
        reason: The agent-supplied rejection reason.

    Raises:
        HumanDecisionInvalidReasonError: If ``reason`` is None, empty, or
            whitespace-only.
    """
    if reason is None or not reason.strip():
        raise HumanDecisionInvalidReasonError(
            "a reason is required to reject a suggestion"
        )


def final_refund_for(
    action: ResolutionAction,
    order_value: float,
    refund_ratio: float = 1.0,
) -> Optional[float]:
    """Derive the refund amount for a final action (US-02 S1).

    A human-chosen ``refund`` applies ``round(order_value * refund_ratio, 2)``
    capped at the order value via F3 ``apply_refund_cap`` (BR-05). Any other
    action yields None.

    Args:
        action: The final action (approve or override).
        order_value: F1 ``orders_context.value`` in INR (0.0 when unknown).
        refund_ratio: Fraction of order value applied to a manual refund
            (config ``STM_HUMAN_OVERRIDE_REFUND_RATIO``, default 1.0 → full refund).

    Returns:
        The capped refund amount in INR for ``refund``, else None.
    """
    if action != ResolutionAction.REFUND:
        return None
    proposed = round(float(order_value) * float(refund_ratio), 2)
    capped, _ = apply_refund_cap(proposed, float(order_value))
    return capped
