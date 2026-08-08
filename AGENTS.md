# Agent Harness Capabilities & Unbiased TDD Architecture

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12+ · FastAPI · Uvicorn |
| AI/ML | scikit-learn (TF-IDF) · sentence-transformers (optional embeddings) |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Frontend | HTML + Vanilla JS + CSS (minimal, no framework) |
| Testing | pytest · httpx (async test client) |
| Package Manager | uv 

## Project Structure

```
support_ticket_manager/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry
│   │   ├── models/              # Pydantic models
│   │   ├── routes/              # API endpoints
│   │   ├── services/            # Business logic
│   │   └── core/                # Config, DB, shared utils
│   ├── tests/                   # pytest test files
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── sample_data/                 # CSV datasets
├── features/                    # Spec-driven feature docs
│   └── INDEX.md
├── docs/                        # Design docs
├── AGENTS.md                    # ← This file
└── Q3-Design.pdf                # Problem statement
```

---

## 3-Document Feature Architecture

Each feature lives in `features/<feature-name>/` with 3 docs:

| Doc | Purpose | Reads Code? |
|---|---|---|
| `1_spec.md` | Non-technical spec (user stories, acceptance criteria) | ❌ |
| `2_tech_spec.md` | Technical design (API contracts, function signatures) | ⚠️ Conventions only |
| `3_summary.md` | Post-implementation context capsule (≤50 lines) | ✅ |

## Feature Pipeline

```
/plan-features → /generate-spec → /generate-tech-spec → /generate-tests → /implement-feature → /validate-feature → /generate-summary
```

## Isolation Rules

| Agent | Reads Code? | Reads Specs? | Reads Summaries? |
|---|---|---|---|
| feature-planner | ❌ | ❌ | ✅ 3_summary only |
| spec-writer | ❌ | Own output | ✅ Deps from INDEX |
| tech-architect | ⚠️ Conventions | ✅ 1_spec | ✅ Deps from INDEX |
| test-engineer | ❌ | ✅ 1_spec + 2_tech_spec | ❌ |
| summary-writer | ✅ | ✅ Both | ✅ All |

## Test Output Convention
- Python signatures → `test_<feature_name>.py` (pytest)
- Path: `features/<feature-name>/tests/test_<feature_name>.py`

## Harness Configs

| Harness | Config Location |
|---|---|
| OpenCode | `.opencode/` (commands, agents, skills, mcp.json) |
| Gemini / Antigravity | `.gemini/` (AGENTS.md symlink + settings) |
| Claude Code | `.claude/` (CLAUDE.md + commands) |
