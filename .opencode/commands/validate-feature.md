---
description: Validate the pipeline status and document integrity of a feature across all stages (spec → tech-spec → tests → implementation → summary).
agent: spec-architect
subtask: false
---

# Command: /validate-feature [feature-name]

Validates the pipeline integrity and document completeness for a specific feature.

## What This Command Does

Performs a comprehensive check across all pipeline stages to determine feature readiness and identify gaps or broken dependencies.

---

## Validation Checklist

Run the following checks **in order** and report a status table:

### Stage 1: Specification (`1_spec.md`)
- [ ] File exists at `features/<feature-name>/1_spec.md`
- [ ] Contains **Metadata table** with Feature ID and Status
- [ ] Contains at least **1 User Story** with Given-When-Then acceptance criteria
- [ ] Contains **Edge Cases** section with at least 1 entry
- [ ] Contains **NO technical implementation details** (no code blocks, no API routes, no SQL schemas)

### Stage 2: Technical Specification (`2_tech_spec.md`)
- [ ] File exists at `features/<feature-name>/2_tech_spec.md`
- [ ] Contains `Derived From` metadata pointing to the correct `1_spec.md`
- [ ] Contains **Interface Definitions** with typed function signatures
- [ ] Contains **API Contracts** with request/response structures
- [ ] Every User Story from `1_spec.md` has a corresponding technical component

### Stage 3: Tests
- [ ] Test file exists at `features/<feature-name>/tests/` directory
- [ ] Tests import from function signatures defined in `2_tech_spec.md`
- [ ] Tests cover **all** acceptance criteria scenarios from `1_spec.md`
- [ ] Tests include edge case coverage matching Section 4 of `1_spec.md`

### Stage 4: Implementation
- [ ] Source files exist that export the functions defined in `2_tech_spec.md`
- [ ] All exported signatures match the contract in `2_tech_spec.md`

### Stage 5: Summary (`3_summary.md`)
- [ ] File exists at `features/<feature-name>/3_summary.md`
- [ ] Contains all required sections: Capability Overview, Exported Interfaces, Dependencies, Configuration
- [ ] Status is set to `Implemented & Verified`
- [ ] Exported interfaces listed match those in `2_tech_spec.md`

---

## Output Format

Generate a **Feature Pipeline Status Report** in this format:

```markdown
# Feature Pipeline Status: [Feature Name]

| Stage | Status | Issues |
|---|---|---|
| 1. Specification | ✅ Pass / ⚠️ Warn / ❌ Fail | [details] |
| 2. Tech Spec | ✅ Pass / ⚠️ Warn / ❌ Fail | [details] |
| 3. Tests | ✅ Pass / ⚠️ Warn / ❌ Fail | [details] |
| 4. Implementation | ✅ Pass / ⚠️ Warn / ❌ Fail | [details] |
| 5. Summary | ✅ Pass / ⚠️ Warn / ❌ Fail | [details] |

**Overall Readiness**: [READY / NOT READY]
**Next Action**: [What needs to be done next]
```
