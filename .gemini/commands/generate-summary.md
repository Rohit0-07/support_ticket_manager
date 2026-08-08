---
description: Generate a concise post-implementation summary (3_summary.md) for a completed feature to serve as AI context memory.
agent: summary-writer
subtask: true
---

# Command: /generate-summary [feature-name]

Generates a concise **Post-Implementation Summary** (`3_summary.md`) for a completed feature.

## Pre-Execution Validation

> [!IMPORTANT]
> **MANDATORY CHECKS**: Before generating, verify ALL of the following:
> 1. `features/<feature-name>/1_spec.md` **EXISTS**
> 2. `features/<feature-name>/2_tech_spec.md` **EXISTS**
> 3. Test files exist in `features/<feature-name>/tests/`
> 4. Implementation source files exist that export the functions from `2_tech_spec.md`
>
> If ANY check fails → **STOP** and tell the user what's missing. A summary for an unimplemented feature is a **context poison pill** that will mislead all future feature development.

## Purpose & Context Management

> [!NOTE]
> `3_summary.md` acts as a lightweight context capsule. Other AI agents working on future features will read **ONLY** this summary to understand what capabilities exist. This keeps context windows clean and prevents bloat.

## Context Window Budget
- **Maximum 50 lines**. This is a strict limit. Summaries that are too long defeat their purpose.
- Focus on WHAT the feature does and HOW to interface with it, not implementation details.

---

## Output Target
- Path: `features/<feature-name>/3_summary.md`

---

## Summary Template Format (`3_summary.md`)

```markdown
# Feature Summary: [Feature Name]

| Metadata | Details |
|---|---|
| **Feature ID** | FEAT-[NUMBER] |
| **Status** | Implemented & Verified |
| **Created Date** | YYYY-MM-DD |
| **Last Updated** | YYYY-MM-DD |

---

## 1. Capability Overview
- Brief 2-3 sentence summary of what this feature accomplishes in the system.

## 2. Exported Interfaces & Capabilities
- **Functions**:
  - `functionName(param: Type): ReturnType` — One-line description
- **API Endpoints**:
  - `METHOD /api/path` — One-line description
- **Data Entities**: Primary data models managed or modified by this feature.

## 3. Dependent Features & Integration Points
- [Feature Name] — How this feature connects with it
- If no dependencies: "Standalone feature, no cross-feature dependencies."

## 4. Key Configuration & Constants
- `ENV_VAR_NAME` — Description of what it controls
- If no configuration: "No environment variables or configuration introduced."
```

## Quality Validation Before Saving:
- [ ] All sections from the template are present (even if marked "None")
- [ ] Exported interfaces match `2_tech_spec.md` exactly
- [ ] Total line count ≤ 50
- [ ] No implementation details (no file paths, no internal class names, no algorithm descriptions)
- [ ] Status is `Implemented & Verified` ONLY if tests exist and implementation is present
