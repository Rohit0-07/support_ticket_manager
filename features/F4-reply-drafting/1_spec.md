# Non-Technical Specification: Reply Drafting

| Metadata | Details |
|---|---|
| **Feature Name** | Reply Drafting |
| **Feature ID** | FEAT-004 (F4) |
| **Status** | Draft |
| **Author** | Product Manager (AI) |
| **Created Date** | 2026-08-08 |

---

## 1. Executive Summary & Problem Statement

### 1.1 Problem Description
Customers who submit a support ticket get no immediate acknowledgment of what is happening with their issue. When a reply does arrive, it is written from scratch by an agent who has to retype the same explanation hundreds of times a day — "your refund has been processed", "we are sending the missing item again", "we are looking into this". The result is slow, inconsistent, and impersonal communication.

Every ticket — whether automatically resolved or sent for human review — should receive a clear, empathetic, professionally worded reply that explains what is being done and why. The reply must draw on the specific past cases that informed the decision, so the customer sees the reasoning behind the action and trusts the process.

### 1.2 Target Personas
- **Customers** — end users who submitted a ticket and expect a prompt, clear explanation of the outcome or next steps.
- **Support Agents** — staff who handle the human-review lane and need a ready-to-send draft so they spend seconds, not minutes, on each reply.
- **Support Managers** — supervisors who want consistent, professional, and explainable customer communication across all tickets.

### 1.3 Expected Business Value
- Every ticket receives a reply automatically, eliminating silent waiting and follow-up pressure.
- Agent time per escalated ticket is reduced because a usable draft is already prepared.
- Customer communication becomes consistent, transparent, and empathetic — every reply explains the action and cites the evidence behind it.
- The same ticket information always produces the same reply, keeping communication predictable and auditable.

---

## 2. User Stories & Acceptance Criteria

### US-01: Receive a Clear, Empathetic Reply for Every Ticket
- **As a** customer
- **I want to** receive a drafted reply that explains what is happening with my ticket and why
- **So that** I understand the outcome or the next steps without having to chase support

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: Auto-resolved ticket with strong precedent evidence
  - **Given** my ticket was automatically resolved with a specific action (for example, a refund) based on similar past cases
  - **When** the reply is drafted for my ticket
  - **Then** the reply clearly states the action being taken, explains that this matches how similar past cases were handled, and uses professional, empathetic language

- **Scenario 2**: Ticket escalated for human review
  - **Given** my ticket was sent to human review because past cases were weak or conflicting
  - **When** the reply is drafted for my ticket
  - **Then** the reply clearly states that a support specialist is reviewing the issue and does not promise or imply that any action has already been taken

### US-02: Send a Ready-to-Use Draft Without Starting From Scratch
- **As a** support agent
- **I want to** see a pre-drafted reply attached to every ticket I handle that I can edit or send as-is
- **So that** I respond to customers quickly without retyping the same explanation repeatedly

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: Edit and send the draft
  - **Given** a ticket under human review with a drafted reply visible on its detail view
  - **When** I edit the wording and send the reply
  - **Then** the customer receives my edited version, and the original draft is preserved in the ticket history for audit purposes

- **Scenario 2**: Ticket with no usable precedent evidence
  - **Given** a ticket where no similar past cases were found
  - **When** the draft reply is generated for this ticket
  - **Then** the reply honestly acknowledges the ticket without inventing a reason or action, and states that a specialist is reviewing it

### US-03: Every Reply Explains Its Reasoning With Evidence
- **As a** support manager
- **I want to** ensure every customer reply references the similar past cases that informed the decision
- **So that** customers receive a transparent "why" behind each action, and communication remains explainable and auditable

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: Relevant past cases exist
  - **Given** a ticket where the decision was based on similar past cases
  - **When** the reply is drafted
  - **Then** the reply mentions that the action follows how similar past cases were handled, giving the customer confidence in the outcome

- **Scenario 2**: Past cases disagree or no strong match exists
  - **Given** a ticket where similar past cases do not all point to the same action, or none match closely enough
  - **When** the reply is drafted
  - **Then** the reply does not cite a single past case as the reason, does not promise a specific action, and instead explains that a specialist is reviewing the ticket

---

## 3. User Experience & Business Workflows

### Workflow A: Auto-Resolved Ticket (Customer Perspective)
1. The customer submits a ticket about an issue with their order.
2. The system processes the ticket and determines it can be resolved automatically with high confidence.
3. A reply is drafted that tells the customer, in plain language, what action was taken (for example, a refund or a redelivery) and explains that this matches how similar past cases were resolved.
4. The reply is attached to the ticket and becomes visible to the customer without any human involvement.

### Workflow B: Escalated Ticket (Agent Perspective)
1. The system determines the ticket needs human review (weak or conflicting evidence, or a blocked action).
2. A draft reply is generated that acknowledges the ticket and states that a specialist is reviewing it — it must not promise a specific outcome.
3. The agent opens the ticket, sees the draft alongside the suggested action and the similar past cases, edits the wording if needed, and sends the reply.
4. If the agent changes the outcome later (for example, approves or overrides the suggestion), the reply is updated to reflect the final action before it goes to the customer.

### Business Rules
- **Every ticket gets a reply**: both auto-resolved and escalated tickets receive a drafted reply.
- **Replies never over-promise**: if no action has been finalized, the reply must not imply one has been taken.
- **Replies never invent evidence**: the reply may only reference similar past cases that actually exist and were actually used in the decision.
- **Consistency**: the same ticket information must always produce the same reply wording.
- **Human edits are preserved**: an agent's edits never replace the audit trail of the original draft.

---

## 4. User-Facing Edge Cases & Business Exceptions

| # | Trigger / Condition | Business Impact | Expected Handling |
|---|---|---|---|
| EC-01 | Ticket escalated because no similar past cases were found | Reply could fabricate a fake reason, eroding customer trust | Reply must not mention past cases; it should acknowledge the ticket and state a specialist is reviewing it |
| EC-02 | Similar past cases conflict on which action to take | Reply could promise an action that was never finalized, creating liability | Reply must not state or imply a specific action; it should say the ticket is under review |
| EC-03 | Ticket text is missing or too short to reference | Reply could reference content that does not exist, confusing the customer | Reply should still be a polite, complete acknowledgment without pretending to know specific details |
| EC-04 | Agent edits a draft and the ticket is later re-processed | The agent's final wording could be silently overwritten | The customer-facing reply must reflect the agent's final version; the original draft is kept in history for audit |
| EC-05 | Order details referenced by the ticket are not available | Reply could cite order facts that do not exist, causing inaccuracies | Reply should avoid referencing unavailable order details and stick to the confirmed outcome or review status |
| EC-06 | Ticket has a very long description | Reply could become an unreadable wall of text | Reply should stay short and readable, giving the customer the outcome and the reason without dumping the full history |

---

## 5. Related Features & Summary Dependencies

- **F3 · Resolution Engine** (`features/F3-resolution-engine/3_summary.md`) — **Required dependency.** Reply Drafting consumes the resolution decision produced for each ticket — the chosen or suggested action, whether it was auto-resolved or escalated, and the reasoning behind it. Without F3's decision output, no reply can be drafted.
- **F1 · Data Ingestion & Storage** — Indirect: provides the historical tickets and order facts that give a reply its evidence and context.
- **F2 · Similarity Engine** — Indirect: supplies the similar past cases that a reply cites as evidence.
- **F5 · Two-Lane Dashboard** *(planned, no summary yet)* — Downstream: displays the drafted reply on each ticket card so agents can review and send it.
- **F6 · Human Override Controls** *(planned, no summary yet)* — Downstream: when an agent approves, rejects, or overrides a suggested action, the reply is expected to reflect the final decision.
