---
name: spec-generator
description: Skill for drafting pure non-technical specification documents (1_spec.md) without inspecting code files.
---

# Skill: Non-Technical Spec Generator

## Purpose
Generate business-focused specification documents that describe WHAT a feature does and WHY, never HOW it's built.

## Guidelines

### 1. Strict Non-Technical Boundary
- Focus exclusively on: Problem Statement, Target Personas, Business Value, User Stories, Acceptance Criteria (Given-When-Then), and User-Facing Edge Cases.
- NEVER include API endpoints, SQL schemas, data types, function names, class names, or code snippets in `1_spec.md`.

### 2. Zero Code Inspection
- Do NOT view source code files (`.ts`, `.py`, `.js`, `.dart`, `.go`, `.rs`, `.java`).
- Do NOT view config files (`package.json`, `tsconfig.json`, `pubspec.yaml`).
- If context from other features is needed, read ONLY existing summaries (`features/*/3_summary.md`).

### 3. Quality Standards
- **Minimum 2 User Stories** per spec, each with at least 2 Given-When-Then scenarios.
- **Minimum 2 Edge Cases** in the edge cases table.
- Every acceptance criterion must be **testable** — it should be possible to determine pass/fail.
- Avoid vague language like "should work well" or "fast response times" — quantify where possible.

### 4. Storage Location
- Save specs to `features/<feature-name>/1_spec.md`.

---

## Anti-Patterns (AVOID)

| ❌ Bad Pattern | ✅ Correct Alternative |
|---|---|
| "The API endpoint should return JSON..." | "The system should display results to the user..." |
| "Use PostgreSQL to store tickets..." | "Ticket data should be persisted and retrievable..." |
| "Call the `parseCSV()` function..." | "Process the uploaded file and extract ticket records..." |
| "Given the database contains 5 records..." | "Given 5 existing tickets in the system..." |
| "System should be fast" | "Tickets should appear in dashboard within 3 seconds of upload" |

## Example: Well-Written Given-When-Then

```markdown
### US-01: Automatic Order Context Lookup
- **As a** Support Agent
- **I want** incoming tickets automatically linked to customer order history
- **So that** I have immediate context without manually searching spreadsheets

#### Acceptance Criteria:
- **Scenario 1**: Customer with order history
  - **Given** a new ticket from a customer who has placed 3 orders
  - **When** the ticket is processed by the system
  - **Then** all 3 order summaries should be visible on the ticket detail view

- **Scenario 2**: Customer with no order history
  - **Given** a new ticket from a customer with no recorded orders
  - **When** the ticket is processed by the system
  - **Then** the ticket should display "No order history found" and still be assigned to an agent
```
