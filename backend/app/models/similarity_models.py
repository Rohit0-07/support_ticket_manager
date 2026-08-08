from enum import Enum
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class SimilarityStatus(str, Enum):
    """Lifecycle status of a similarity match request.

    MATCHED          - at least one past case met the minimum similarity threshold
    NO_SIMILAR_CASES - corpus exists but no past case is similar enough (US-01 S2)
    CANNOT_MATCH     - query description is empty/blank after preprocessing (EC-01)
    NO_HISTORY       - no resolved tickets exist in history yet (EC-02)
    """

    MATCHED = "matched"
    NO_SIMILAR_CASES = "no_similar_cases"
    CANNOT_MATCH = "cannot_match"
    NO_HISTORY = "no_history"


class SimilarityQuery(BaseModel):
    """Request body for the similarity match endpoint."""

    description: str = Field(
        ...,
        min_length=1,
        examples=["milk packet missing from order"],
        description="Full free-text description of the new/incoming ticket.",
    )
    top_n: int = Field(
        default=3,
        ge=1,
        le=10,
        examples=[3],
        description="Number of most-similar past cases to return. Defaults to 3.",
    )


class SimilarTicket(BaseModel):
    """A single matched past resolved ticket with its similarity rating."""

    model_config = ConfigDict(from_attributes=True)

    ticket_id: str = Field(..., examples=["H-1000"])
    category: str = Field(..., examples=["missing_item"])
    description: str = Field(..., examples=["milk packet missing from my order"])
    action_taken: str = Field(..., examples=["redelivery"])
    resolution_note: str = Field(..., examples=["missing item re-sent"])
    similarity_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        examples=[0.93],
        description="Cosine similarity between query and this past case, 0.0 (no similarity) to 1.0 (perfect match).",
    )


class SimilarityStats(BaseModel):
    """Engine diagnostics returned with every match response."""

    corpus_size: int = Field(..., description="Number of distinct past cases in the index.")
    elapsed_ms: float = Field(..., description="Wall-clock time for the request, in milliseconds.")
    min_score_threshold: float = Field(..., description="Minimum similarity threshold applied.")
    short_query_penalty_applied: bool = Field(
        ..., description="True when the query was too short and scores were damped (EC-03)."
    )


class SimilarityResponse(BaseModel):
    """Response for a similarity match request."""

    query: str = Field(..., description="Echo of the original request description.")
    status: SimilarityStatus
    matches: List[SimilarTicket] = Field(
        default_factory=list,
        description="Ranked past cases, most similar first. Empty for non-MATCHED statuses.",
    )
    stats: SimilarityStats


class IndexStatusResponse(BaseModel):
    """Response from the rebuild-index endpoint."""

    corpus_size: int = Field(..., description="Number of distinct past cases now in the index.")
    built_at: str = Field(..., description="ISO-8601 UTC timestamp of when the index was built.")
    duplicates_removed: int = Field(
        ..., description="Number of word-for-word identical descriptions dropped during fit (EC-04)."
    )
