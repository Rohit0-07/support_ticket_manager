# Feature Summary: F2 · Similarity Engine

| Metadata | Details |
|---|---|
| **Feature ID** | FEAT-002 (F2) |
| **Status** | Implemented & Verified |
| **Created Date** | 2026-08-08 |
| **Last Updated** | 2026-08-08 |

---

## 1. Capability Overview
- Finds the most similar resolved support tickets for any incoming ticket description, ranked closest match first with a 0.0–1.0 similarity rating per result. Serves as the precedent-lookup brain for auto-resolution: routine tickets match past cases, while novel problems are explicitly flagged rather than forced into a weak match.

## 2. Exported Interfaces & Capabilities
- **API Endpoints**:
  - `POST /api/v1/similarity/match` — Accepts `{description, top_n?}`; returns top-N ranked `SimilarTicket` matches plus status and stats.
  - `POST /api/v1/similarity/rebuild-index` — Forces a fresh index build; returns `corpus_size`, `built_at`, `duplicates_removed`.
- **Service Functions**:
  - `find_similar(db, description, top_n=3) -> SimilarityResponse` — Main entry; status is `MATCHED | NO_SIMILAR_CASES | CANNOT_MATCH | NO_HISTORY`.
  - `rebuild_index(db) -> IndexStatusResponse` — Rebuilds the index from persisted history.
  - `IndexCache.get_bundle(db) / invalidate()` — Process-wide cached index with staleness detection (auto-rebuild after F1 re-seed).
  - `load_resolved_corpus(db) -> List[ResolvedTicket]` — Reads all resolved history rows.
- **Pure Engine**:
  - `SimilarityIndex.fit(records, max_chars=512, dedupe_identical=True)` — Builds index from corpus; raises on empty corpus.
  - `SimilarityIndex.search(query, top_n=3, min_score=0.10, ...) -> SearchOutcome` — Ranked matches; deterministic tie-break by `(score DESC, ticket_id ASC)`.
  - `preprocess_description(text, max_chars=512) -> str` — Normalize/truncate; `count_tokens(text) -> int`; `short_query_penalty(raw_score, token_count, ...) -> float` — damp short-query scores.
  - Exceptions: `SimilarityEngineError` (base), `CorpusLoadError` (→ 500), `InvalidTopNError` (→ 400).
- **Status Semantics**: `matched` (use as precedents) · `no_similar_cases` (novel → human lane) · `cannot_match` (blank → human review) · `no_history` (no data yet → human review).
- **Data Entities**: `SimilarityQuery`, `SimilarTicket` (`ticket_id`, `category`, `description`, `action_taken`, `resolution_note`, `similarity_score`), `SimilarityResponse`, `SimilarityStats`, `IndexStatusResponse`, `SimilarityStatus` enum. Reads F1's `resolved_tickets` table; introduces no new tables.

## 3. Dependent Features & Integration Points
- **F1 · Data Ingestion & Storage** — REQUIRED dependency: reads the F1-persisted `resolved_tickets` table; returns `no_history` until F1 seeding runs.
- **F3 · Resolution Engine** — Downstream consumer: consumes `status` + `matches` to decide auto-resolve vs. escalate.
- **F5 · Two-Lane Dashboard** — Downstream consumer: renders matched past cases with similarity ratings.

## 4. Key Configuration & Constants
- `STM_SIMILARITY_TOP_N_DEFAULT` — Default match count (3).
- `STM_SIMILARITY_TOP_N_MAX` — Upper bound for `top_n` (10).
- `STM_SIMILARITY_MIN_SCORE` — Min similarity threshold; below → `no_similar_cases` (0.10).
- `STM_SIMILARITY_MIN_MEANINGFUL_TOKENS` — Short-query damping threshold (3).
- `STM_SIMILARITY_MAX_QUERY_CHARS` — Description truncation length (512).
- `STM_SIMILARITY_DEDUPE_IDENTICAL` — Drop word-for-word duplicate descriptions (true).
- Dependency added: `scikit-learn>=1.4.0`.
