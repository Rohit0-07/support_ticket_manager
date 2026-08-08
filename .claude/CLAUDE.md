# Project: Support Ticket Manager

## Tech Stack
- **Backend**: Python 3.12+ / FastAPI / Uvicorn
- **Frontend**: Vanilla HTML + JS + CSS (no framework)
- **Testing**: pytest + httpx
- **AI/ML**: scikit-learn (TF-IDF), sentence-transformers (optional)
- **Data**: CSV files in `sample_data/`

## Architecture Rules

Read `AGENTS.md` at project root for the full 3-Document Feature Architecture.

### Key Constraints
1. **Feature pipeline**: All features go through `/plan-features → /generate-spec → /generate-tech-spec → /generate-tests → /implement-feature → /validate-feature → /generate-summary`
2. **Isolation**: When generating specs, NEVER read implementation code. When generating tests, ONLY read `1_spec.md` + `2_tech_spec.md`.
3. **Feature docs live in** `features/<feature-name>/` with `1_spec.md`, `2_tech_spec.md`, `3_summary.md`
4. **Context loading**: Read `features/INDEX.md` first → load ONLY dependency summaries listed there
5. **Test files**: `test_<feature_name>.py` using pytest, placed in `features/<feature-name>/tests/`

## Project Layout
```
backend/app/          → FastAPI application
backend/tests/        → Integration tests
frontend/             → Static HTML/JS/CSS
sample_data/          → CSV datasets (resolved_tickets, new_tickets, orders_context)
features/             → Spec-driven feature documents
features/INDEX.md     → Feature registry & dependency graph
```

## Commands (OpenCode equivalents — run manually)
- **Plan features**: Decompose problem → `features/INDEX.md`
- **Generate spec**: Write `1_spec.md` (no tech, no code)
- **Generate tech spec**: Write `2_tech_spec.md` (from 1_spec)
- **Generate tests**: Write `test_*.py` (from specs only, NO code reading)
- **Implement**: Write code to pass tests
- **Validate**: Check pipeline integrity
- **Generate summary**: Write `3_summary.md` (≤50 lines)
