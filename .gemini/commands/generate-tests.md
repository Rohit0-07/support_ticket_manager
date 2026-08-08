---
description: Generate unbiased TDD unit & integration tests from 1_spec.md and 2_tech_spec.md signatures WITHOUT reading implementation code.
agent: test-engineer
subtask: true
---

# Command: /generate-tests [feature-name]

Generates unbiased, black-box unit and integration tests for a feature based **exclusively** on its specification (`1_spec.md`) and technical signatures (`2_tech_spec.md`).

## Pre-Execution Validation

> [!IMPORTANT]
> **MANDATORY CHECKS**: Before generating, verify:
> 1. `features/<feature-name>/1_spec.md` **EXISTS**. If not → STOP and tell the user to run `/generate-spec <feature-name>` first.
> 2. `features/<feature-name>/2_tech_spec.md` **EXISTS**. If not → STOP and tell the user to run `/generate-tech-spec <feature-name>` first.
> 3. `2_tech_spec.md` contains **Interface Definitions** with at least one function signature. If not → STOP and report the tech spec is incomplete.
> 4. Check if `features/<feature-name>/tests/` already has test files. If yes → **warn the user** and ask if they want to overwrite.

## Strict Unbiased Testing Rules

> [!CAUTION]
> ### ABSOLUTE CODE ISOLATION
> 1. **IMPLEMENTATION CODE IS STRICTLY HIDDEN**: You MUST NOT open, view, list, or grep implementation source files (`src/`, `lib/`, `app/`, `bin/`, `server/`, `api/`, `backend/`, `frontend/`).
> 2. **INPUT SOURCES — EXHAUSTIVE LIST**: You may ONLY read:
>    - `features/<feature-name>/1_spec.md` (Acceptance criteria, user stories, edge cases)
>    - `features/<feature-name>/2_tech_spec.md` (Exported function names, signatures, types, and input/output contracts)
> 3. **NO CODE BIAS**: Tests must be written purely against the contracts and acceptance criteria defined in the specs, ensuring true Test-Driven Development (TDD).
> 4. **NO OTHER FILES**: Do NOT read `3_summary.md`, other feature specs, `package.json`, or any non-spec file.

---

## Output Target
- Path: `features/<feature-name>/tests/test_<feature_name>.py` (pytest)

## Language:
- This project uses **Python/pytest**
- Output: `test_<feature_name>.py`
- Use `httpx.AsyncClient` for API tests, `@pytest.mark.asyncio` for async

---

## Instructions for the Test Engineer Agent

### Phase 1: Scenario Extraction from `1_spec.md`
1. List ALL Given-When-Then scenarios from every User Story
2. List ALL edge cases from Section 4 (Edge Cases table)
3. Identify implicit boundary conditions (empty input, max length, null values)

### Phase 2: Contract Extraction from `2_tech_spec.md`
1. List ALL exported function signatures with parameter and return types
2. List ALL API endpoint contracts with request/response shapes
3. List ALL error types and their trigger conditions
4. Note the traceability matrix (Section 6) to verify full coverage

### Phase 3: Test Construction
For each function/endpoint, create:
- **Happy path tests**: One per success scenario from acceptance criteria
- **Failure tests**: One per failure/edge case scenario
- **Boundary tests**: Null input, empty input, max values based on type constraints
- **Error type tests**: One per error type defined in tech spec

### Phase 4: Self-Validation
Before saving, verify:
- [ ] Every Given-When-Then scenario from `1_spec.md` has ≥1 test
- [ ] Every edge case from `1_spec.md` Section 4 has ≥1 test
- [ ] Every exported function from `2_tech_spec.md` has ≥1 test
- [ ] Every error type from `2_tech_spec.md` Section 5 has ≥1 test
- [ ] Tests use ONLY public function signatures (no internal/private access)
- [ ] Tests would pass for ANY correct implementation of the spec
- [ ] Test descriptions use business language from the spec, not implementation jargon
