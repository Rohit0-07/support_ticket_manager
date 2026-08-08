# Agent Harness Capabilities & Unbiased TDD Architecture

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12+ · FastAPI · Uvicorn |
| AI/ML | scikit-learn (TF-IDF) · sentence-transformers (optional embeddings) |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Frontend | HTML + Vanilla JS + CSS (minimal, no framework) |
| Testing | pytest · httpx (async test client) |
| Package Manager | uv |

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
└── Q3-Design.md                 # Problem statement
```

---

## 3-Document Feature Architecture

Each feature lives in `features/<feature-name>/` with 3 docs:

| Doc | Purpose | Reads Code? |
|---|---|---|
| `1_spec.md` | Non-technical spec (user stories, acceptance criteria) | ❌ |
| `2_tech_spec.md` | Technical design (API contracts, function signatures) | ⚠️ Conventions only |
| `3_summary.md` | Post-implementation context capsule (≤50 lines) | ✅ |

## Feature Pipeline & Command Triggers

```
/plan-features → /generate-spec → /generate-tech-spec → /generate-tests → /implement-feature → /validate-feature → /generate-summary
```

### Available Harness Commands & Definitions

Whenever a user requests one of these slash commands or steps, execute the exact process defined below:

1. **`/plan-features [project-name]`**
   - **Agent**: `feature-planner`
   - **Action**: Read `Q3-Design.md` / user conversation and decompose into discrete features.
   - **Output**: `features/INDEX.md`
   - **Restriction**: Do NOT read code files.

2. **`/generate-spec [feature-name]`**
   - **Agent**: `spec-writer`
   - **Action**: Write non-technical feature specification based on user stories & acceptance criteria.
   - **Output**: `features/<feature-name>/1_spec.md`
   - **Restriction**: Do NOT read source code or technical files.

3. **`/generate-tech-spec [feature-name]`**
   - **Agent**: `tech-architect`
   - **Action**: Translate `1_spec.md` into technical interfaces, signatures, API contracts, and Mermaid sequence diagrams.
   - **Output**: `features/<feature-name>/2_tech_spec.md`

4. **`/generate-tests [feature-name]`**
   - **Agent**: `test-engineer`
   - **Action**: Generate black-box pytest unit/integration tests matching `2_tech_spec.md` signatures.
   - **Output**: `features/<feature-name>/tests/test_<feature_name>.py`
   - **Restriction**: Do NOT read implementation source code.

5. **`/implement-feature [feature-name]`**
   - **Agent**: Implementation Engineer
   - **Action**: Write FastAPI / Python source code satisfying test cases in `features/<feature-name>/tests/`.
   - **Output**: `backend/app/...`

6. **`/validate-feature [feature-name]`**
   - **Agent**: Pipeline Validator
   - **Action**: Run test suite and check pipeline stage completion.

7. **`/generate-summary [feature-name]`**
   - **Agent**: `summary-writer`
   - **Action**: Draft a ≤50-line context capsule of exported interfaces & dependencies.
   - **Output**: `features/<feature-name>/3_summary.md`

---

## Isolation Rules

| Agent | Reads Code? | Reads Specs? | Reads Summaries? |
|---|---|---|---|
| `feature-planner` | ❌ | ❌ | ✅ `3_summary.md` only |
| `spec-writer` | ❌ | Own output | ✅ Deps from `INDEX.md` |
| `tech-architect` | ⚠️ Conventions | ✅ `1_spec.md` | ✅ Deps from `INDEX.md` |
| `test-engineer` | ❌ | ✅ `1_spec.md` + `2_tech_spec.md` | ❌ |
| `summary-writer` | ✅ | ✅ Both | ✅ All |

## Test Output Convention
- Python signatures → `test_<feature_name>.py` (pytest)
- Path: `features/<feature-name>/tests/test_<feature_name>.py`

## Harness Configs

| Harness | Config Location |
|---|---|
| OpenCode | `.opencode/` (commands, agents, skills, mcp.json) |
| Gemini / Antigravity | `.gemini/` (`AGENTS.md` symlink + settings) |
| Claude Code | `.claude/` (`CLAUDE.md` + commands) |
