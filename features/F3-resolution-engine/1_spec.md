# Non-Technical Specification: Resolution Engine

| Metadata | Details |
|---|---|
| **Feature Name** | Resolution Engine |
| **Feature ID** | FEAT-003 (F3) |
| **Status** | Draft |
| **Author** | Product Manager (AI) |
| **Created Date** | 2026-08-08 |

---

## 1. Executive Summary & Problem Statement

### 1.1 Problem Description
A quick-delivery company receives thousands of support tickets daily — "items missing", "order late", "wrong item", "refund not received". Roughly nine out of ten are near-identical to tickets that were already resolved hundreds of times before, yet every single one still waits in a queue for a human agent to apply the same fix as last time. Customers wait hours for answers the business already knows, and agents spend their day re-solving the same problem over and over.

The Resolution Engine removes the human bottleneck for **routine tickets**: it looks at the ticket, checks the most similar past cases, checks the facts of the customer's order, and decides whether it can confidently resolve the ticket the same way history resolved it — or whether a human should look at it first. Every decision is recorded with its reasoning so the business can trust, audit, and continuously improve the system.

### 1.2 Target Personas
- **Support Manager** — wants routine tickets off the human queue and wants full visibility into what the system resolved, why, and with what confidence.
- **Support Agent** — receives only the tickets that genuinely need human judgment, each with past cases and a suggested action already attached, so their time is spent on the hard cases.
- **Customer (End User)** — receives a fast, consistent resolution for routine issues instead of waiting hours for a human.

### 1.3 Expected Business Value
- **Faster resolution**: routine tickets are resolved in seconds instead of hours.
- **Lower cost per ticket**: human agents only handle genuinely uncertain or high-risk cases.
- **Consistent decisions**: the same type of ticket gets the same type of resolution every time, matching what the business did successfully in the past.
- **Zero unsafe actions**: the system never guesses when evidence is weak, and never takes an action that order facts make inappropriate (for example, never sending a replacement for a cancelled order).
- **Full traceability**: every decision is logged with its reasoning, enabling audit and continuous improvement.

---

## 2. User Stories & Acceptance Criteria

### US-01: Auto-Resolve Routine Tickets
- **As a** support manager
- **I want to** have routine tickets resolved automatically when the past cases strongly support one clear action
- **So that** customers get immediate, consistent resolutions and agents are freed to handle complex cases

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: Success Flow — Strong agreement, confident match
  - **Given** a new ticket whose top three similar past cases all resulted in the same action (for example, all three were refunded) and the match confidence is at or above the required level (by default 75%)
  - **When** the system processes the ticket
  - **Then** the ticket is resolved automatically using that same action, and a record of the decision — including the action, the confidence, the past cases used, and the reasoning — is saved for review
- **Scenario 2**: Failure Flow — Weak evidence is never acted on
  - **Given** a new ticket whose best similar past cases are only weakly similar, falling below the required confidence level
  - **When** the system processes the ticket
  - **Then** the ticket is **not** auto-resolved; it is sent to the human review lane with the suggested action and past cases attached, and the decision record explains that confidence was too low

### US-02: Escalate When Precedents Disagree or Order Facts Block the Action
- **As a** support manager
- **I want to** have the system hold a ticket for human review whenever past cases disagree on what to do, or whenever the order's facts make the suggested action unsafe
- **So that** the system never guesses at the right action and never harms a customer's order

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: Conflicting precedent evidence
  - **Given** a new ticket whose top three similar past cases suggest different actions (for example, one was refunded, another got a coupon, a third got a replacement) — even if the overall confidence score is high
  - **When** the system processes the ticket
  - **Then** the ticket is always escalated to the human review lane; the system never picks one of the conflicting actions on its own
- **Scenario 2**: Order context constraint
  - **Given** a new ticket on an order that was already cancelled, and the similar past cases suggest sending a replacement
  - **When** the system processes the ticket
  - **Then** the replacement action is never applied; the ticket is escalated to the human review lane with a note that the action was blocked because the order was cancelled

### US-03: Audit Every Resolution Decision
- **As a** support manager
- **I want to** see a complete record of every decision the system makes — auto-resolved or escalated
- **So that** I can audit actions, understand why each ticket was handled the way it was, and improve the system over time

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: Auto-resolved decision is recorded
  - **Given** a ticket that the system auto-resolves
  - **When** the decision is made
  - **Then** a log entry is saved capturing which ticket it was, the action taken, the confidence level, the past cases used as evidence, the reasoning, the fact that it was auto-resolved, and when it happened
- **Scenario 2**: Escalated decision is recorded
  - **Given** a ticket that the system escalates to a human (due to low confidence, conflicting evidence, a blocked action, or any other reason)
  - **When** the decision is made
  - **Then** a log entry is saved capturing the same details plus the specific reason the ticket was escalated, so the human reviewer and management understand why it needed a human

---

## 3. User Experience & Business Workflows

### 3.1 End-to-End Journey (from ticket arrival to decision)

1. **A new ticket arrives** and is stored in the system along with the link to the customer's order.
2. **Past cases are found** — the system searches its history of resolved tickets and brings back the top three most similar past cases for this ticket.
3. **Order facts are checked** — the system looks up the details of the linked order (what was ordered, its value, its delivery status).
4. **The decision is evaluated** — the system considers three things together:
   - Do the top three past cases agree on the same action?
   - How confident is the match between this ticket and those past cases?
   - Do the order facts allow the suggested action (for example, a replacement is only allowed on an order that was actually delivered)?
5. **The ticket is either auto-resolved or escalated**:
   - **Auto-resolve**: past cases agree, confidence is at or above the required level, and the order facts permit the action. The action (refund, replacement, or coupon) is applied and the customer is on their way to a drafted reply.
   - **Escalate**: weak evidence, conflicting past cases, or blocked action — the ticket moves to the human review lane with the suggested action, the past cases, and the reasoning attached, so an agent can decide quickly.
6. **The decision is recorded** — every outcome is logged with its reasoning for auditability.
7. **A drafted reply is prepared** (handled by the Reply Drafting feature) and the ticket appears on the dashboard in the correct lane (handled by the Two-Lane Dashboard feature).

### 3.2 Business Rules

- **BR-01 — Agree before acting**: The system may only auto-resolve when the top three similar past cases all point to the same action.
- **BR-02 — Confidence bar**: The system may only auto-resolve when confidence is at or above the required level. The business can adjust this bar; the default setting is 75%.
- **BR-03 — Never guess**: If the past cases disagree on the action, the ticket is escalated regardless of how confident the match looks.
- **BR-04 — Order facts override precedent**: If the order's facts make the suggested action inappropriate — for example, the order was cancelled — that action is never applied, and the ticket is escalated.
- **BR-05 — No over-refunding**: Any refund applied must never exceed the value of the customer's order.
- **BR-06 — Act only on evidence**: If no useful past cases exist for a ticket (novel issue), the system never acts on its own; it escalates.
- **BR-07 — Every decision is traceable**: Every auto-resolved or escalated ticket produces a decision record with the action, confidence, evidence used, reasoning, outcome type, and timestamp.

---

## 4. User-Facing Edge Cases & Business Exceptions

| # | Trigger / Condition | Business Impact | Expected Handling |
|---|---|---|---|
| EC-01 | No similar past cases found for the ticket (a genuinely novel issue) | Acting on weak evidence could produce a wrong resolution and a worse customer experience | The system does not act; the ticket is escalated to the human review lane with no suggested action forced |
| EC-02 | Top three past cases disagree on the action | Choosing one on its own risks the wrong outcome and erodes customer trust | The ticket is always escalated; the system never selects a "winning" action |
| EC-03 | Order was cancelled but past cases suggest sending a replacement | Shipping a replacement for a cancelled order wastes inventory and can cause billing disputes | The replacement action is blocked; the ticket is escalated with the reason noted |
| EC-04 | The past case suggests a refund larger than the order's value | Over-refunding loses money directly and invites abuse | The refund is capped at the order value; the ticket is escalated for a human to decide the exact amount |
| EC-05 | System has no resolved-history loaded yet | With no history, any "match" would be meaningless and actions would be ungrounded | No ticket is auto-resolved until history is available; all tickets are escalated |
| EC-06 | Ticket has a blank or unreadable description | Matching and reasoning would be unreliable | The ticket is escalated to the human review lane; no action is taken |
| EC-07 | The ticket's linked order cannot be found in the system | Applying an action without order facts (value, status) could be unsafe | The ticket is escalated; no action is applied until order facts are confirmed |
| EC-08 | Confidence is exactly at the required level | Inconsistent treatment of boundary cases erodes trust in the rules | The ticket is treated as meeting the requirement (auto-resolve if all other rules allow), so behavior is predictable and documented |

---

## 5. Related Features & Summary Dependencies

- **F1 · Data Ingestion & Storage** (`features/F1-data-ingestion/3_summary.md`) — Required dependency: provides the persisted history of resolved tickets and the order facts that the Resolution Engine reads before deciding. The engine can only act once historical data and order context are available.
- **F2 · Similarity Engine** (`features/F2-similarity-engine/3_summary.md`) — Required dependency: supplies the top similar past cases and their confidence ratings that drive the auto-resolve vs. escalate decision. Its "no similar cases / cannot match / no history" outcomes map directly to escalation in the Resolution Engine.
- **F4 · Reply Drafting** (downstream consumer) — Consumes the Resolution Engine's decision to produce a customer-facing drafted reply.
- **F5 · Two-Lane Dashboard** (downstream consumer) — Displays the Resolution Engine's outcome (auto-resolved vs. needs-human) and its supporting decision details on the board.
