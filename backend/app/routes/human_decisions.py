"""API router for the Human Override Controls feature (FEAT-006).

Endpoints documented in ``features/F6-human-override-controls/2_tech_spec.md`` §2.4 / §4.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.human_decision_models import (
    ApproveRequest,
    HumanDecisionListResponse,
    HumanDecisionRecord,
    OverrideRequest,
    RejectRequest,
)
from app.services import human_decision_service
from app.services.human_decision_engine import (
    HumanDecisionInvalidActionError,
    HumanDecisionInvalidReasonError,
    HumanDecisionPolicyBlockedError,
)

router = APIRouter(prefix="/api/v1", tags=["human-decisions"])


@router.post("/human-decisions/{ticket_id}/approve", response_model=HumanDecisionRecord)
async def approve_human_decision_endpoint(
    ticket_id: str,
    payload: ApproveRequest,
    db: AsyncSession = Depends(get_db),
) -> HumanDecisionRecord:
    """Approve the suggested action on an escalated ticket (US-01)."""
    try:
        return await human_decision_service.approve_ticket(db, ticket_id, payload.agent_id)
    except human_decision_service.HumanDecisionTicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except human_decision_service.HumanDecisionNotActionableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except human_decision_service.HumanDecisionAlreadyHandledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except human_decision_service.HumanDecisionInvalidAgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except human_decision_service.HumanDecisionNoSuggestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except human_decision_service.HumanDecisionPersistenceError as exc:
        raise HTTPException(status_code=500, detail=f"Human decision failed: {exc}") from exc


@router.post("/human-decisions/{ticket_id}/override", response_model=HumanDecisionRecord)
async def override_human_decision_endpoint(
    ticket_id: str,
    payload: OverrideRequest,
    db: AsyncSession = Depends(get_db),
) -> HumanDecisionRecord:
    """Override the suggested action with a new one (US-02)."""
    try:
        return await human_decision_service.override_ticket(
            db, ticket_id, payload.agent_id, payload.action, payload.reply_body
        )
    except human_decision_service.HumanDecisionTicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except human_decision_service.HumanDecisionNotActionableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except human_decision_service.HumanDecisionAlreadyHandledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (
        human_decision_service.HumanDecisionInvalidAgentError,
        HumanDecisionInvalidActionError,
        HumanDecisionPolicyBlockedError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except human_decision_service.HumanDecisionPersistenceError as exc:
        raise HTTPException(status_code=500, detail=f"Human decision failed: {exc}") from exc


@router.post("/human-decisions/{ticket_id}/reject", response_model=HumanDecisionRecord)
async def reject_human_decision_endpoint(
    ticket_id: str,
    payload: RejectRequest,
    db: AsyncSession = Depends(get_db),
) -> HumanDecisionRecord:
    """Reject the suggested action with a reason (US-03)."""
    try:
        return await human_decision_service.reject_ticket(db, ticket_id, payload.agent_id, payload.reason)
    except human_decision_service.HumanDecisionTicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except human_decision_service.HumanDecisionNotActionableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except human_decision_service.HumanDecisionAlreadyHandledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (
        human_decision_service.HumanDecisionInvalidAgentError,
        HumanDecisionInvalidReasonError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except human_decision_service.HumanDecisionPersistenceError as exc:
        raise HTTPException(status_code=500, detail=f"Human decision failed: {exc}") from exc


# NOTE: registered BEFORE /human-decisions/{ticket_id} so a literal path never
# collides with the {ticket_id} parameter (F4 convention, §8 note 2).
@router.get("/human-decisions", response_model=HumanDecisionListResponse)
async def list_human_decisions_endpoint(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> HumanDecisionListResponse:
    """List the human-decision audit history, newest first (US-04, EC-06)."""
    try:
        items, total = await human_decision_service.list_human_decisions(db, skip, limit)
    except human_decision_service.HumanDecisionPersistenceError as exc:
        raise HTTPException(status_code=500, detail=f"Human decision failed: {exc}") from exc
    return HumanDecisionListResponse(total=total, skip=skip, limit=limit, items=items)


@router.get("/human-decisions/{ticket_id}", response_model=HumanDecisionRecord)
async def get_human_decision_endpoint(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
) -> HumanDecisionRecord:
    """Return the human decision for one ticket (handled-status check)."""
    try:
        record = await human_decision_service.get_human_decision(db, ticket_id)
    except human_decision_service.HumanDecisionPersistenceError as exc:
        raise HTTPException(status_code=500, detail=f"Human decision failed: {exc}") from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"no human decision for ticket {ticket_id}")
    return record
