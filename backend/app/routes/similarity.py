from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.similarity_models import IndexStatusResponse, SimilarityQuery, SimilarityResponse
from app.services import similarity_service
from app.services.similarity_engine import CorpusLoadError, InvalidTopNError, SimilarityEngineError

router = APIRouter(prefix="/api/v1", tags=["similarity"])


@router.post("/similarity/match", response_model=SimilarityResponse)
async def match_similar_tickets(
    payload: SimilarityQuery,
    db: AsyncSession = Depends(get_db),
) -> SimilarityResponse:
    """Return the top-N most similar resolved tickets for a ticket description.

    Args:
        payload: Request body (description + optional top_n).
        db: Async DB session dependency.

    Returns:
        A SimilarityResponse (200). See API contract §4.1 for statuses.

    Raises:
        HTTPException(400): On InvalidTopNError (service-level guard, ERR_001).
        HTTPException(500): On CorpusLoadError / SimilarityEngineError.
    """
    try:
        return await similarity_service.find_similar(db, payload.description, payload.top_n)
    except InvalidTopNError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CorpusLoadError, SimilarityEngineError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Similarity engine failed: {exc}",
        ) from exc


@router.post("/similarity/rebuild-index", response_model=IndexStatusResponse)
async def rebuild_similarity_index(
    db: AsyncSession = Depends(get_db),
) -> IndexStatusResponse:
    """Force a rebuild of the in-memory similarity index from persisted history.

    Returns:
        Index status with corpus size, build time, and duplicate count (200).

    Raises:
        HTTPException(500): On CorpusLoadError / SimilarityEngineError.
    """
    try:
        return await similarity_service.rebuild_index(db)
    except (CorpusLoadError, SimilarityEngineError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Similarity engine failed: {exc}",
        ) from exc
