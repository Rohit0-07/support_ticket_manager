---
description: Generate a non-technical Specification Document (1_spec.md) for a new feature. Does NOT inspect code files.
agent: spec-writer
subtask: true
---

# Command: /generate-spec [feature-name]

Generates a pure, **Non-Technical Specification Document** (`1_spec.md`) for a feature.

## Critical Rules & Isolation Instructions

> [!CAUTION]
> ### ABSOLUTE PROHIBITIONS
> 1. **DO NOT READ OR INSPECT CODE FILES** (`.js`, `.ts`, `.py`, `.dart`, `.go`, `.rs`, `.java`, etc.).
> 2. **DO NOT READ** `package.json`, `tsconfig.json`, `pubspec.yaml`, `requirements.txt`, or any config/build files.
> 3. **DO NOT READ** `src/`, `lib/`, `app/`, `bin/`, `server/`, `api/`, `backend/`, `frontend/` directories.
> 4. **NO TECHNICAL DETAILS**: Do NOT include code snippets, API endpoints, SQL schemas, data types, function names, or system implementation choices.

## Allowed Context Sources
- `features/INDEX.md` — Read this FIRST to identify which features this feature depends on.
- `features/<dependency>/3_summary.md` — Read ONLY the summaries listed in the "Depends On" column for this feature in `INDEX.md`. Do NOT load all summaries.
- User-provided requirements from conversation.
- Non-code documentation in `docs/` (`.md` files only).

## Pre-Execution Check (Mandatory)
Before generating the spec:
1. Read `features/INDEX.md` — verify this feature is listed. If not, tell the user to run `/plan-features` first.
2. From `INDEX.md`, find the **"Depends On"** column for this feature. Load ONLY those specific `3_summary.md` files.
3. Check if `features/<feature-name>/1_spec.md` already exists. If yes, **warn the user** and ask if they want to overwrite.

> [!TIP]
> **Context Window Optimization**: By reading INDEX.md first, you load only the 1-3 relevant summaries instead of ALL summaries. This keeps your context window clean as the project grows to 20+ features.

---

## Output Target
- Path: `features/<feature-name>/1_spec.md`

---

## Specification Template Format (`1_spec.md`)

```markdown
# Non-Technical Specification: [Feature Name]

| Metadata | Details |
|---|---|
| **Feature Name** | [Feature Name] |
| **Feature ID** | FEAT-[NUMBER] |
| **Status** | Draft |
| **Author** | Product Manager (AI) |
| **Created Date** | YYYY-MM-DD |

---

## 1. Executive Summary & Problem Statement
### 1.1 Problem Description
- What user pain point or business problem does this feature solve?

### 1.2 Target Personas
- Who will use this feature (e.g., Support Agents, Admins, End Users)?

### 1.3 Expected Business Value
- What is the expected impact or outcome?

---

## 2. User Stories & Acceptance Criteria

### US-01: [User Story Title]
- **As a** [user persona]
- **I want to** [action/capability]
- **So that** [business benefit]

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: Success Flow
  - **Given** [initial state/context]
  - **When** [user performs action]
  - **Then** [expected result]
- **Scenario 2**: Validation / Warning
  - **Given** [invalid context]
  - **When** [user performs action]
  - **Then** [appropriate error message displayed]

### US-02: [Second User Story Title]
- **As a** [user persona]
- **I want to** [action/capability]
- **So that** [business benefit]

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: [...]
- **Scenario 2**: [...]

---

## 3. User Experience & Business Workflows
- Step-by-step description of the user journey from start to finish.
- Business rules governing data visibility and actions.

---

## 4. User-Facing Edge Cases & Business Exceptions
| # | Trigger / Condition | Business Impact | Expected Handling |
|---|---|---|---|
| EC-01 | [condition] | [impact] | [handling] |
| EC-02 | [condition] | [impact] | [handling] |

---

## 5. Related Features & Summary Dependencies
- Features referenced from existing `features/*/3_summary.md` files that interact with this feature.
- If no related features exist, state: "No existing feature dependencies identified."
```

## Minimum Quality Requirements
- At least **2 User Stories** with Given-When-Then criteria
- At least **2 Edge Cases** in Section 4
- **Zero** code-related terms (no function names, API paths, database references)
- Created Date must be filled with today's date
