---
name: feature-summary-generator
description: Skill for compiling concise feature summaries (3_summary.md) to serve as lightweight AI context memory.
---

# Skill: Feature Summary Generator

## Purpose
Create minimal, high-signal context capsules that future AI agents can load to understand system capabilities without loading full specs or source code. Optimized for context window efficiency.

## Guidelines

### 1. Lightweight Context Capsule
- Produce a short, focused summary of implemented capabilities and exported interfaces.
- Do NOT include full source code, lengthy documentation, or implementation details.
- **HARD LIMIT: 50 lines maximum**. Summaries exceeding this limit are counterproductive.

### 2. Pre-Condition Enforcement
Before writing any summary, verify:
- [ ] `1_spec.md` exists for this feature
- [ ] `2_tech_spec.md` exists for this feature
- [ ] Test files exist in `tests/` directory
- [ ] Implementation source files exist
If any are missing, REFUSE to write the summary and report what's missing.

### 3. Content Rules
| Section | Requirement |
|---|---|
| Capability Overview | 2-3 sentences MAX, describes WHAT not HOW |
| Exported Interfaces | List ALL public functions with signatures (one-line each) |
| Dependencies | Concrete feature names, not vague references |
| Configuration | List env vars / flags with descriptions, or explicitly state "None" |

### 4. What NOT to Include
- ❌ Internal class names or file paths
- ❌ Algorithm descriptions or implementation strategies
- ❌ Full data model definitions (just entity names)
- ❌ Test coverage details
- ❌ Development history or changelog

### 5. Storage Location
- Save summaries to `features/<feature-name>/3_summary.md`.

---

## Example: Good vs. Bad Summary

**❌ BAD — Too detailed, leaks implementation:**
```markdown
## Capability Overview
The ticket ingestion feature uses a streaming CSV parser implemented in `src/services/CSVParserService.ts` 
that reads files line-by-line using Node.js streams. It stores parsed tickets in PostgreSQL using the 
Prisma ORM with a batch insert of 100 records at a time...
```

**✅ GOOD — Concise, interface-focused:**
```markdown
## Capability Overview
Automated batch processing of customer support CSV files, performing entity correlation between incoming 
tickets and customer order histories. Flags unmatched tickets for manual review.
```
