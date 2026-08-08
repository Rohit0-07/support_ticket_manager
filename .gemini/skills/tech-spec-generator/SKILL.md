---
name: tech-spec-generator
description: Skill for crafting technical details documents (2_tech_spec.md) from non-technical specs (1_spec.md).
---

# Skill: Technical Spec Generator

## Purpose
Translate business specifications into precise technical blueprints with function signatures, data models, API contracts, and sequence diagrams that enable unbiased test generation.

## Guidelines

### 1. Derived Architecture
- Read `features/<feature-name>/1_spec.md` as the PRIMARY input.
- Translate every business user story into technical components, schemas, and API contracts.
- Read existing code (if present) ONLY for naming conventions and consistency — NOT for requirements.

### 2. Function Signature Precision
- Explicitly document ALL exported function signatures with full type annotations.
- Include parameter descriptions, return type descriptions, and error throw conditions.
- Use JSDoc/docstring format so test generators have complete contract information.

```typescript
// ✅ GOOD: Complete, testable signature
/**
 * Ingests a batch of support tickets from CSV content.
 * @param csvContent - Raw CSV string containing ticket rows
 * @returns Promise resolving to ingestion result with counts
 * @throws {InvalidCSVError} When csvContent is malformed or empty
 * @throws {DatabaseError} When persistence fails
 */
export function ingestTicketBatch(csvContent: string): Promise<IngestionResult>;

// ❌ BAD: Incomplete signature, no error types, no descriptions
export function ingestTicketBatch(csv: any): Promise<any>;
```

### 3. Traceability Requirement
Every User Story from `1_spec.md` MUST appear in a **Spec-to-Component Traceability** table:

```markdown
| User Story | Technical Component | Function/Endpoint |
|---|---|---|
| US-01: Order Context Linking | TicketOrderMatcher | matchOrderContext() |
| US-02: SLA Tracking | ResolutionAnalytics | computeSLAMetrics() |
```

### 4. Error Type Completeness
Every edge case from `1_spec.md` Section 4 must have a corresponding error type:

```typescript
export class InvalidCSVError extends Error {
  constructor(public readonly rowNumber: number, message: string) {
    super(message);
  }
}
```

### 5. Storage Location
- Save technical specs to `features/<feature-name>/2_tech_spec.md`.

---

## Anti-Patterns (AVOID)

| ❌ Bad Pattern | ✅ Correct Alternative |
|---|---|
| Using `any` types in signatures | Use precise types: `string`, `number`, specific interfaces |
| Missing error type definitions | Define error classes for each edge case |
| No traceability to user stories | Include Spec-to-Component table |
| Vague response schemas: `data: object` | Explicit: `data: { tickets: Ticket[], count: number }` |
| No sequence diagram | At least 1 Mermaid sequence diagram for primary flow |
