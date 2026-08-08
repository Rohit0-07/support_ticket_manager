---
name: unbiased-test-generator
description: Skill for generating unbiased TDD unit/integration tests from spec & signature documents while hiding source code.
---

# Skill: Unbiased Black-Box Test Generator

## Purpose
Generate tests that validate spec correctness, NOT implementation correctness. Tests written from this skill should pass for ANY correct implementation of the specification, not just one specific implementation.

## Guidelines

### 1. Context Isolation & Zero Code Bias
- MUST NOT read or view implementation source code files under any circumstance.
- Use ONLY `features/<feature-name>/1_spec.md` (acceptance criteria) and `features/<feature-name>/2_tech_spec.md` (function signatures and contracts).
- Do NOT read `3_summary.md`, `package.json`, or any non-spec file.

### 2. Test-Driven Development (TDD) Alignment
- Write tests that assert expected BEHAVIORS and CONTRACT guarantees.
- Create test suites BEFORE or independently of implementation code.
- Tests represent the GROUND TRUTH from specs — if tests fail, the implementation is wrong, not the test.

### 3. Coverage Requirements
| Source | Test Coverage Rule |
|---|---|
| Each Given-When-Then scenario | ≥ 1 test case |
| Each Edge Case from Section 4 | ≥ 1 test case |
| Each exported function | ≥ 1 happy path + 1 failure test |
| Each error type in tech spec | ≥ 1 test case |
| Boundary values (null, empty, max) | ≥ 1 test per function parameter |

### 4. Test Structure Pattern

```typescript
describe('Feature: [Feature Name from spec]', () => {
  
  describe('US-01: [User Story title from spec]', () => {
    it('Scenario 1: should [expected behavior from Given-When-Then]', async () => {
      // Arrange — set up the "Given" state
      const input = { /* matches interface from tech spec */ };
      
      // Act — perform the "When" action
      const result = await exportedFunction(input);
      
      // Assert — verify the "Then" expectation
      expect(result.success).toBe(true);
    });

    it('Scenario 2: should [failure behavior from Given-When-Then]', async () => {
      // Arrange — set up the invalid "Given" state
      const invalidInput = { /* boundary/invalid values */ };
      
      // Act & Assert
      await expect(exportedFunction(invalidInput)).rejects.toThrow(ErrorType);
    });
  });

  describe('Edge Cases', () => {
    it('EC-01: should [handle edge case] when [trigger from spec]', () => {
      // Map directly from Edge Case table in 1_spec.md
    });
  });
});
```

### 5. Storage Location
- Save tests to `features/<feature-name>/tests/<feature-name>.test.ts` (or equivalent for project language).

---

## Anti-Patterns (AVOID)

| ❌ Biased Test | ✅ Unbiased Test |
|---|---|
| Tests internal helper functions | Tests only public/exported functions |
| Mocks specific internal modules | Mocks only external dependencies (DB, HTTP) |
| `expect(parser._regex.test(x))` | `expect(result.processedCount).toBe(5)` |
| Adjusts test to match failing code | Reports test failure as implementation bug |
| Tests file structure or imports | Tests behavior and contracts |
| Hardcodes implementation-specific values | Uses spec-defined expectations |

## Example: Mapping Spec → Test

**From `1_spec.md`:**
```markdown
### US-01: Automated Ticket & Order Context Linking
- **Scenario 2**: Missing Customer / Order Reference
  - **Given** a ticket CSV entry with an unknown Customer ID
  - **When** the ingestion process runs
  - **Then** the ticket status should be set to `UNMATCHED`
```

**From `2_tech_spec.md`:**
```typescript
export function ingestTicketBatch(csvContent: string): Promise<IngestionResult>;
export interface IngestionResult { unmatchedCount: number; }
```

**Resulting Test:**
```typescript
it('should set tickets with unknown Customer ID to UNMATCHED status', async () => {
  const csvWithUnknownCustomer = 'ticket_id,customer_id,issue\nT001,UNKNOWN_999,Billing';
  const result = await ingestTicketBatch(csvWithUnknownCustomer);
  expect(result.unmatchedCount).toBeGreaterThan(0);
});
```
