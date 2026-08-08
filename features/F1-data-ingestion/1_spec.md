# F1 · Data Ingestion & Storage — Feature Specification

> **Feature ID**: F1
> **Status**: Spec Draft
> **Dependencies**: None (foundational feature)
> **Downstream consumers**: F2 (Similarity Engine), F3 (Resolution Engine), F5 (Dashboard)

---

## 1. Overview

The support ticket system needs a reliable data foundation before any intelligence can be built on top. This feature covers loading the three provided CSV datasets into a persistent store, making that data available through a clean API, and establishing the data shapes that every downstream feature will depend on.

This is the bedrock of the entire system — nothing else works without it.

---

## 2. User Stories

### US-1: Initial Data Seeding
**As a** system administrator,
**I want** the system to automatically load the three CSV datasets (`resolved_tickets.csv`, `new_tickets.csv`, `orders_context.csv`) when initialized,
**So that** all historical and incoming data is immediately available for the resolution pipeline.

### US-2: Idempotent Re-seeding
**As a** system administrator,
**I want** to re-run the data loading process without creating duplicate records,
**So that** I can safely restart or re-deploy the system without corrupting the data.

### US-3: Graceful Handling of Bad Data
**As a** system administrator,
**I want** malformed or incomplete rows in the CSV files to be skipped with a logged warning (not a crash),
**So that** one bad row does not prevent the rest of the dataset from loading.

### US-4: Browsing Resolved Tickets
**As a** support manager,
**I want** to retrieve a list of all resolved tickets (with optional pagination),
**So that** I can review the historical data the system is learning from.

### US-5: Browsing New (Incoming) Tickets
**As a** support manager,
**I want** to retrieve a list of all new/incoming tickets,
**So that** I can see the queue of tickets waiting to be processed.

### US-6: Viewing Order Context
**As a** support agent or the resolution engine,
**I want** to look up the order details linked to a ticket (items, value, delivery time, status),
**So that** resolution decisions can be constrained by real order facts (e.g., a cancelled order cannot be redelivered).

### US-7: Retrieving a Single Record
**As a** consumer of the API (human or system),
**I want** to retrieve a single resolved ticket, new ticket, or order by its ID,
**So that** I can inspect individual records in detail.

---

## 3. Acceptance Criteria

### Data Loading

| # | Criterion | Verification |
|---|---|---|
| AC-1 | All rows from `resolved_tickets.csv` are persisted and retrievable after system startup. | Count of stored records matches valid rows in CSV. |
| AC-2 | All rows from `new_tickets.csv` are persisted and retrievable after system startup. | Count of stored records matches valid rows in CSV. |
| AC-3 | All rows from `orders_context.csv` are persisted and retrievable after system startup. | Count of stored records matches valid rows in CSV. |
| AC-4 | Running the data load process a second time does not create duplicate records. | Record count is unchanged after a second load. |
| AC-5 | A malformed row (missing required fields, wrong types) is skipped. A warning is logged identifying the row number and reason. The rest of the file loads successfully. | Introduce a bad row, verify it is skipped and logged. |

### Data Retrieval

| # | Criterion | Verification |
|---|---|---|
| AC-6 | A list endpoint for resolved tickets returns all records with default pagination. | Response contains expected number of records. |
| AC-7 | A list endpoint for new tickets returns all records. | Response contains expected number of records. |
| AC-8 | A list endpoint for orders returns all records. | Response contains expected number of records. |
| AC-9 | A single-record endpoint for each entity returns the correct record when given a valid ID. | Field values match source CSV. |
| AC-10 | A single-record endpoint returns a clear "not found" response for an invalid ID. | 404-style response with descriptive message. |

### Data Integrity

| # | Criterion | Verification |
|---|---|---|
| AC-11 | Each resolved ticket record contains at minimum: id, description, action taken, resolution note, and CSAT score. | Inspect stored records. |
| AC-12 | Each new ticket record contains at minimum: id, description, and linked order ID. | Inspect stored records. |
| AC-13 | Each order context record contains at minimum: order ID, items, value, delivery time, and status. | Inspect stored records. |
| AC-14 | Data persists across server restarts (stored in SQLite, not just in-memory). | Restart the server, verify data is still accessible. |

---

## 4. Data Entities

> *These are the business-level data shapes. Technical schema details belong in the tech spec.*

### Resolved Ticket
| Field | Description | Example |
|---|---|---|
| ID | Unique identifier for the ticket | 1 |
| Description | Free-text description of the customer's issue | "Milk packet missing from order" |
| Action Taken | The resolution action that was applied | "refund" |
| Resolution Note | Human-written note about how it was resolved | "Refunded Rs 40 for missing milk packet" |
| CSAT Score | Customer satisfaction score after resolution | 4.5 |

### New Ticket
| Field | Description | Example |
|---|---|---|
| ID | Unique identifier for the ticket | 101 |
| Description | Free-text description of the customer's issue | "Received wrong item — ordered paneer, got tofu" |
| Order ID | Link to the associated order | 5023 |

### Order Context
| Field | Description | Example |
|---|---|---|
| Order ID | Unique identifier for the order | 5023 |
| Items | Items in the order | "Paneer 200g, Bread, Eggs x6" |
| Value | Total order value in Rs | 320.00 |
| Delivery Time | Actual delivery time | "12 mins" |
| Status | Current order status | "delivered" / "cancelled" / "in_transit" |

---

## 5. Business Rules

1. **No duplicates on re-seed**: The system must be safe to re-initialize. Running the CSV loader twice produces the same data state as running it once.
2. **Fail gracefully**: A single corrupt row must never prevent the rest of the dataset from loading. Warnings are logged, not errors.
3. **Data is persistent**: All data must survive a process restart. In-memory-only storage is not acceptable.
4. **Order linkage**: New tickets reference orders by order ID. If a new ticket references a non-existent order ID, the ticket is still loaded — the missing order context is handled at resolution time, not at ingestion time.

---

## 6. Out of Scope

The following are explicitly **not** part of this feature:

- Similarity computation or TF-IDF indexing (→ F2)
- Resolution logic or confidence scoring (→ F3)
- Reply generation (→ F4)
- Any frontend rendering (→ F5)
- Creating, updating, or deleting tickets through the API (this feature is read-only + bulk load)
- Authentication or authorization
- PostgreSQL production setup (SQLite is sufficient for this phase)

---

## 7. Open Questions

| # | Question | Impact |
|---|---|---|
| OQ-1 | What are the exact CSV column headers? Need to confirm against actual files before tech spec. | Column mapping in loader |
| OQ-2 | Should pagination be cursor-based or offset-based? | API design in tech spec |
| OQ-3 | Are there any tickets in `new_tickets.csv` that reference order IDs not present in `orders_context.csv`? If so, is that valid? | Validation rules |
