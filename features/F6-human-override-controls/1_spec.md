# Non-Technical Specification: Human Override Controls

| Metadata | Details |
|---|---|
| **Feature Name** | Human Override Controls |
| **Feature ID** | FEAT-006 (F6) |
| **Status** | Draft |
| **Author** | Product Manager (AI) |
| **Created Date** | 2026-08-08 |

---

## 1. Executive Summary & Problem Statement

### 1.1 Problem Description
The system automatically resolves routine tickets and escalates uncertain ones to a **Needs Human Review** lane, where each ticket already carries a suggested action (refund / redelivery / coupon), a confidence score, supporting precedent cases, and a drafted customer reply. However, the dashboard is currently **read-only**: a human agent can *look* at the recommendation but cannot *act* on it.

As a result, agents are forced to copy details out of the dashboard and resolve tickets in external tools. This breaks the workflow in two ways:
1. The final decision is never recorded against the ticket, so the organization loses an **audit trail** of what actually happened and why.
2. Good automation suggestions cannot be quickly accepted, and bad ones cannot be corrected in place — every unusual case requires duplicate manual effort.

This feature closes the loop by letting a human agent **approve**, **override**, or **reject** the suggested action directly from the dashboard, with every decision permanently recorded for accountability.

### 1.2 Target Personas
- **Support Agents** — resolve escalated tickets by accepting, changing, or rejecting the system's suggestion.
- **Support Managers** — review the history of human decisions to audit quality, coach agents, and confirm compliance with refund / redelivery policies.

### 1.3 Expected Business Value
- Escalated tickets are resolved in one place, eliminating copy-paste into external tools.
- Every human decision is recorded with who did it and when, creating a complete, auditable resolution history.
- The system's suggestions get continuous, visible validation — agents can accept good suggestions quickly and correct bad ones explicitly.
- Business policy is protected because the system prevents financially harmful or rule-breaking actions (e.g., redelivery on a cancelled order) even during manual override.

---

## 2. User Stories & Acceptance Criteria

### US-01: Approve a Suggested Action
- **As a** Support Agent
- **I want to** approve the suggested action on an escalated ticket
- **So that** the ticket is marked as resolved with the recommended handling and the decision is recorded under my name

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: Approval succeeds
  - **Given** an escalated ticket showing a suggested action (for example, refund) with an attached drafted reply
  - **When** the agent clicks **Approve** and confirms
  - **Then** the ticket moves out of the Needs Human Review lane into the Auto-Resolved view, and the system records the approval along with the agent's identity, the final action, and the timestamp

- **Scenario 2**: Ticket already handled
  - **Given** an escalated ticket that has already been approved or overridden by someone
  - **When** the agent clicks **Approve** on that ticket
  - **Then** the action is not applied a second time, a clear message explains that the ticket has already been handled, and no duplicate record is created

### US-02: Override the Suggested Action and Edit the Reply
- **As a** Support Agent
- **I want to** replace the suggested action with a different one and adjust the drafted reply before confirming
- **So that** unusual or time-sensitive cases get the correct resolution instead of the system's best guess

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: Override succeeds with a new action and edited reply
  - **Given** an escalated ticket whose suggestion is, for example, a coupon
  - **When** the agent chooses **Override**, selects a different action (for example, refund), edits the reply text, and confirms
  - **Then** the ticket moves to the Auto-Resolved view, the new action and the edited reply become the final resolution, and the system records the original suggestion, the new action, the agent's identity, and the timestamp

- **Scenario 2**: Override blocked by a policy constraint
  - **Given** an escalated ticket for an order whose status is **cancelled**
  - **When** the agent tries to override the action to **redelivery**
  - **Then** the system refuses to save the change, shows a clear explanation that redelivery is not allowed for cancelled orders, and the ticket remains in the Needs Human Review lane unchanged

### US-03: Reject a Suggested Action
- **As a** Support Agent
- **I want to** reject the suggested action with a reason
- **So that** a recommendation the agent disagrees with is not applied and the rejection is documented for follow-up

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: Rejection succeeds with a reason
  - **Given** an escalated ticket with a suggested action the agent disagrees with
  - **When** the agent clicks **Reject**, enters a reason, and confirms
  - **Then** the ticket is marked as rejected, the suggested action is never applied, and the system records the rejection, the reason, the agent's identity, and the timestamp

- **Scenario 2**: Rejection without a reason
  - **Given** an escalated ticket
  - **When** the agent clicks **Reject** but leaves the reason blank
  - **Then** the rejection is not saved, and the agent is prompted to provide a reason before the action can complete

### US-04: Audit All Human Decisions
- **As a** Support Manager
- **I want to** view a history of every human decision (approve, override, reject) on escalated tickets
- **So that** I can verify who resolved what, when, and why, and use the record for quality review and policy compliance

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: History is available
  - **Given** one or more escalated tickets that have been acted on by agents
  - **When** the manager opens the decision history
  - **Then** each entry shows the ticket, the original suggested action, the final action (or rejection with reason), which agent acted, and the timestamp, ordered newest first

- **Scenario 2**: No history yet
  - **Given** a system where no human has acted on any escalated ticket
  - **When** the manager opens the decision history
  - **Then** an empty state is shown with a clear message that no human decisions have been recorded yet (not an error)

---

## 3. User Experience & Business Workflows

### 3.1 Workflow: Approving a Suggestion
1. The agent opens the dashboard and sees the **Needs Human Review** lane.
2. The agent clicks a ticket card to open its detail view (full description, suggested action, confidence, top-3 similar past cases, reasoning, drafted reply).
3. The agent reviews the suggestion and clicks **Approve**.
4. The system asks for confirmation; the agent confirms.
5. The ticket moves to the **Auto-Resolved** view and the decision is recorded.

### 3.2 Workflow: Overriding a Suggestion
1. The agent opens an escalated ticket in the Needs Human Review lane.
2. The agent clicks **Override**, which opens the action selector and the editable reply field.
3. The agent picks a different action (refund / redelivery / coupon) and edits the reply if needed.
4. The agent confirms; the system validates the chosen action against the ticket's order context.
5. If valid, the ticket moves to the **Auto-Resolved** view with the new action and edited reply, and the decision is recorded (including the original suggestion for reference).

### 3.3 Workflow: Rejecting a Suggestion
1. The agent opens an escalated ticket.
2. The agent clicks **Reject**, enters a reason, and confirms.
3. The ticket remains visible for manual handling elsewhere, the suggested action is not applied, and the rejection is recorded.

### 3.4 Workflow: Reviewing the Decision History
1. A manager opens the decision history view.
2. The manager sees a newest-first list of human decisions with ticket reference, original suggestion, final action, agent, and timestamp.
3. The manager can read through the entries to audit quality and compliance.

### 3.5 Business Rules
- **Only escalated tickets can be acted on.** Tickets in the Auto-Resolved lane are read-only and show no Approve / Override / Reject controls.
- **One final decision per ticket.** Once a ticket has been approved, overridden, or rejected, no further human action is accepted on it.
- **Override must respect order context.** Actions that contradict the ticket's order status (for example, redelivery on a cancelled order) are blocked even during manual override.
- **Rejection requires a reason.** A rejection without a reason is not saved.
- **Every human decision is recorded.** Approve, override, and reject actions are stored with the agent's identity and the exact timestamp so the record is auditable.
- **Agents must be identifiable.** A human action cannot be recorded without a valid agent identity; the action is refused and the agent is asked to sign in again if identity is missing.

---

## 4. User-Facing Edge Cases & Business Exceptions

| # | Trigger / Condition | Business Impact | Expected Handling |
|---|---|---|---|
| EC-01 | Two agents act on the same escalated ticket at the same time | Double resolution or conflicting final actions; loss of trust in the audit record | The system accepts only the first completed action. The second agent sees a clear message that the ticket was already handled, and no duplicate record is created |
| EC-02 | Agent tries to override to a policy-forbidden action (e.g., redelivery on a cancelled order) | Financial loss and policy violation if the bad action is applied | The system blocks the change, explains the constraint, and leaves the ticket unchanged in the Needs Human Review lane |
| EC-03 | Agent rejects a ticket without entering a reason | Missing audit context; managers cannot understand why a suggestion was rejected | The system does not save the rejection and prompts the agent to enter a reason before completing the action |
| EC-04 | Agent acts on a ticket whose details can no longer be loaded (e.g., the ticket no longer exists) | Agent confusion and possible incorrect handling | The system shows a friendly error explaining the ticket is unavailable, takes no action, and does not record a decision |
| EC-05 | Agent opens the override form and leaves it open for a long time (or closes the browser) before confirming | Partial or phantom decisions; confusion about whether the ticket was resolved | Nothing is recorded until the agent confirms; if the browser is closed, the ticket simply remains actionable in the Needs Human Review lane, and no partial record is left behind |
| EC-06 | The decision history grows large over time | Difficulty finding specific decisions; slow review | The history is ordered newest first and supports browsing page by page so managers can review it in manageable chunks |

---

## 5. Related Features & Summary Dependencies

- **F5 · Two-Lane Dashboard** (REQUIRED dependency) — `features/F5-two-lane-dashboard/3_summary.md`. Provides the Needs Human Review lane and ticket detail view that this feature extends with Approve / Override / Reject controls. Per the F5 summary, F6 is a planned downstream consumer of the Needs Human Review lane; tickets acted on here are expected to surface in the Auto-Resolved view.
- **F3 · Resolution Engine** (interacts via F5) — supplies the original suggested action, confidence score, reasoning, and escalation notes that agents review before acting.
- **F4 · Reply Drafting** (interacts via F5) — provides the drafted customer reply that agents can approve as-is or edit during an override.
- **F1 · Data Ingestion & Storage** (interacts via F5) — supplies the order context used to enforce policy constraints (e.g., no redelivery on cancelled orders) during override.

No other existing feature dependencies identified.
