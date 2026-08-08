import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from app.models.similarity_models import SimilarTicket

logger = logging.getLogger(__name__)


class SimilarityEngineError(Exception):
    """Base class for all similarity engine failures."""


class CorpusLoadError(SimilarityEngineError):
    """Raised when the resolved-tickets corpus cannot be read from the database."""


class InvalidTopNError(SimilarityEngineError):
    """Raised when ``top_n`` is not within the inclusive range 1..10."""

    def __init__(self, top_n: int) -> None:
        super().__init__(f"top_n must be between 1 and 10 (got: {top_n})")
        self.top_n = top_n


class CorpusRecord(BaseModel):
    """A single past resolved ticket's identity + description, as fed to the index."""

    ticket_id: str
    description: str


class RankedMatch(BaseModel):
    """A raw ranked match produced by the index (pre-enrichment)."""

    ticket_id: str
    similarity_score: float = Field(..., ge=0.0, le=1.0)


class SearchOutcome(BaseModel):
    """Result of a search over the index."""

    matches: List[RankedMatch]
    short_query_penalty_applied: bool


def preprocess_description(text: str, max_chars: int = 512) -> str:
    """Normalize a raw description for matching.

    Steps: strip whitespace, collapse internal whitespace to single spaces,
    then truncate to the first ``max_chars`` characters (EC-06: long rambling
    descriptions should only let the most relevant part influence the match).

    Args:
        text: Raw description string (may be empty, None is not accepted).
        max_chars: Maximum character length to keep (default 512).

    Returns:
        Normalized description. Returns an empty string ``""`` when ``text``
        is empty, whitespace-only, or truncates to zero characters.

    Raises:
        SimilarityEngineError: If ``text`` is ``None`` (use empty string instead).
    """
    if text is None:
        raise SimilarityEngineError("text must not be None; use an empty string instead")

    normalized = " ".join(text.split())
    if len(normalized) > max_chars:
        normalized = normalized[:max_chars]
    return normalized


def count_tokens(text: str) -> int:
    """Count whitespace-delimited tokens in a preprocessed description.

    Args:
        text: Already-preprocessed description (see ``preprocess_description``).

    Returns:
        Number of tokens. Returns 0 for an empty string.
    """
    if not text:
        return 0
    return len(text.split())


def short_query_penalty(
    raw_score: float,
    token_count: int,
    min_meaningful_tokens: int = 3,
) -> float:
    """Damp a raw similarity score for extremely short queries (EC-03).

    When ``token_count < min_meaningful_tokens``, the score is multiplied by
    ``token_count / min_meaningful_tokens`` so a one-word query like "refund"
    can never present as a confident routine match. When ``token_count`` is 0,
    returns 0.0. Otherwise returns ``raw_score`` unchanged.

    Args:
        raw_score: Raw cosine similarity in [0.0, 1.0].
        token_count: Number of tokens in the preprocessed query.
        min_meaningful_tokens: Token threshold below which damping applies (default 3).

    Returns:
        Adjusted score in [0.0, 1.0].
    """
    if min_meaningful_tokens <= 0:
        return raw_score
    if token_count < min_meaningful_tokens:
        return raw_score * (token_count / min_meaningful_tokens)
    return raw_score


class SimilarityIndex:
    """Immutable, precomputed TF-IDF index over the resolved-ticket corpus.

    Built once via ``fit()`` and reused across queries for performance (US-03).
    Deterministic: the same corpus and query always produce the same ranking.
    """

    def __init__(
        self,
        vectorizer: Any,
        document_matrix: Any,
        doc_ids: List[str],
        descriptions: List[str],
        built_at: str,
    ) -> None:
        """Construct an index.

        Args:
            vectorizer: Fitted ``sklearn.feature_extraction.text.TfidfVectorizer``.
            document_matrix: Sparse TF-IDF document-term matrix (rows align with ``doc_ids``).
            doc_ids: Ticket ids aligned with matrix rows (corpus order).
            descriptions: Preprocessed descriptions aligned with matrix rows.
            built_at: ISO-8601 UTC build timestamp.
        """
        self.vectorizer = vectorizer
        self.document_matrix = document_matrix
        self.doc_ids = list(doc_ids)
        self.descriptions = list(descriptions)
        self.built_at = built_at
        self.duplicates_removed = 0

    @classmethod
    def fit(
        cls,
        records: List[CorpusRecord],
        max_chars: int = 512,
        dedupe_identical: bool = True,
    ) -> "SimilarityIndex":
        """Build an index from a corpus of past resolved tickets.

        Fits a ``TfidfVectorizer`` (default English stop-word removal is
        disabled; token pattern defaults) on all preprocessed descriptions.
        When ``dedupe_identical`` is True (EC-04), only the first record per
        unique normalized description is kept so word-for-word identical past
        tickets do not inflate the top-N with repeats.

        Args:
            records: All resolved tickets to index.
            max_chars: Corpus description truncation length (EC-06).
            dedupe_identical: Drop word-for-word duplicate descriptions (EC-04).

        Returns:
            A ready-to-search ``SimilarityIndex``.

        Raises:
            SimilarityEngineError: If ``records`` is empty.
        """
        if not records:
            raise SimilarityEngineError("cannot fit an index on an empty corpus")

        normalized: List[tuple] = []
        for record in records:
            description = preprocess_description(record.description, max_chars=max_chars)
            if not description:
                logger.warning(
                    "Skipping record %s: description is blank after preprocessing",
                    record.ticket_id,
                )
                continue
            normalized.append((record.ticket_id, description))

        if dedupe_identical:
            seen: set = set()
            unique: List[tuple] = []
            for ticket_id, description in normalized:
                if description in seen:
                    continue
                seen.add(description)
                unique.append((ticket_id, description))
            duplicates_removed = len(normalized) - len(unique)
        else:
            unique = normalized
            duplicates_removed = 0

        if not unique:
            raise SimilarityEngineError(
                "cannot fit an index: no records have a non-empty description"
            )

        doc_ids = [ticket_id for ticket_id, _ in unique]
        descriptions = [description for _, description in unique]

        from sklearn.feature_extraction.text import TfidfVectorizer

        vectorizer = TfidfVectorizer()
        document_matrix = vectorizer.fit_transform(descriptions)
        built_at = datetime.now(timezone.utc).isoformat()

        index = cls(
            vectorizer=vectorizer,
            document_matrix=document_matrix,
            doc_ids=doc_ids,
            descriptions=descriptions,
            built_at=built_at,
        )
        index.duplicates_removed = duplicates_removed
        return index

    def search(
        self,
        query: str,
        top_n: int = 3,
        min_score: float = 0.10,
        min_meaningful_tokens: int = 3,
    ) -> SearchOutcome:
        """Rank the corpus against a preprocessed query.

        Computes cosine similarity between the query TF-IDF vector and every
        corpus row, applies ``short_query_penalty`` when the query is too short
        (EC-03), drops scores below ``min_score``, sorts by
        ``(similarity_score DESC, ticket_id ASC)`` (deterministic tie-break,
        EC-05), and returns the top ``top_n``.

        Args:
            query: Preprocessed query description (may be empty; empty yields zero matches).
            top_n: Number of results to return (1..10).
            min_score: Minimum similarity for a match to be reported (default 0.10).
            min_meaningful_tokens: Threshold for short-query damping (EC-03).

        Returns:
            ``SearchOutcome`` with ranked matches (possibly empty) and the
            ``short_query_penalty_applied`` flag.

        Raises:
            InvalidTopNError: If ``top_n`` is outside 1..10.
            SimilarityEngineError: If the index has no documents.
        """
        if top_n < 1 or top_n > 10:
            raise InvalidTopNError(top_n)

        if not self.doc_ids:
            raise SimilarityEngineError("cannot search an index with no documents")

        token_count = count_tokens(query)
        penalty_applied = token_count < min_meaningful_tokens

        query_matrix = self.vectorizer.transform([query])
        if query_matrix.nnz == 0:
            return SearchOutcome(matches=[], short_query_penalty_applied=penalty_applied)

        from sklearn.metrics.pairwise import cosine_similarity

        similarities = cosine_similarity(query_matrix, self.document_matrix).flatten()

        scored = []
        for row_index, raw_score in enumerate(similarities):
            adjusted = short_query_penalty(
                float(raw_score),
                token_count,
                min_meaningful_tokens,
            )
            # Clamp to the documented [0.0, 1.0] contract: cosine similarity of
            # identical texts can exceed 1.0 by floating-point error
            # (e.g. 1.0000000000000002), which would violate RankedMatch bounds.
            adjusted = min(1.0, max(0.0, adjusted))
            if adjusted >= min_score:
                scored.append((adjusted, self.doc_ids[row_index]))

        # Deterministic ordering: closest -> weakest, ties by ticket_id ascending (EC-05).
        scored.sort(key=lambda item: (-item[0], item[1]))

        matches = [
            RankedMatch(ticket_id=ticket_id, similarity_score=score)
            for score, ticket_id in scored[:top_n]
        ]
        return SearchOutcome(matches=matches, short_query_penalty_applied=penalty_applied)
