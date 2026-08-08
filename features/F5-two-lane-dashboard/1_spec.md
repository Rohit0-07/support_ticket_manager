# Non-Technical Specification: Two-Lane Dashboard

| Metadata | Details |
|---|---|
| **Feature Name** | Two-Lane Dashboard |
| **Feature ID** | FEAT-005 (F5) |
| **Status** | Draft |
| **Author** | Product Manager (AI) |
| **Created Date** | 2026-08-08 |

---

## 1. Executive Summary & Problem Statement

### 1.1 Problem Description
- Support managers currently have no single place to see what the system did with incoming tickets. When a ticket is processed, the outcome — whether it was resolved automatically or needs human attention — exists in the background, but the manager cannot see it at a glance.
- Without a visible view of decisions, managers cannot tell how many tickets were handled automatically, which tickets are waiting for a human, how confident the system was, or why a particular action was taken. This makes it impossible to trust, verify, or oversee the automated process.
- The dashboard exists to make every decision visible and auditable: one screen showing every processed ticket, split into two lanes — **Auto-Resolved** and **Needs Human Review** — with enough detail on each ticket for a manager to review and verify the system's work.

### 1.2 Target Personas
- **Support Managers** — oversee the ticket-handling process, verify automated decisions, and ensure no ticket slips through without attention.
- **Human Support Agents** — review tickets in the Needs Human Review lane and use the displayed evidence (similar past cases, confidence, reasoning, drafted reply) to respond to customers.
- **Executives / Demo Viewers** — observe the system's behavior in real time and assess how much of the workload is being automated.

### 1.3 Expected Business Value
- Managers can assess automation coverage at a glance (how many tickets were auto-resolved vs. escalated).
- Every ticket becomes transparent and auditable: the evidence, confidence, action, and drafted reply are one click away.
- Escalated tickets are surfaced prominently so no customer request is left waiting in a hidden queue.
- Trust in automation increases because the reasoning behind every decision is visible and verifiable.

---

## 2. User Stories & Acceptance Criteria

### US-01: See All Processed Tickets in Two Clear Lanes
- **As a** Support Manager
- **I want to** view every processed ticket grouped into an "Auto-Resolved" lane and a "Needs Human Review" lane
- **So that** I can instantly see how many tickets were handled automatically and which ones still require human attention

#### Acceptance Criteria (Given-When-Then):

- **Scenario 1**: Tickets in both lanes
  - **Given** the system has processed tickets that were auto-resolved and tickets that were escalated to humans
  - **When** I open the dashboard
  - **Then** I see two clearly labeled lanes, each ticket appears in the lane matching its processing outcome, and each lane shows a count badge of how many tickets it contains

- **Scenario 2**: One lane is empty
  - **Given** the system has processed tickets but none of them were escalated (or none auto-resolved)
  - **When** I open the dashboard
  - **Then** the empty lane shows a friendly "no tickets here" message instead of looking broken, and the populated lane displays its tickets normally

### US-02: Scan Ticket Cards Without Opening Every Ticket
- **As a** Support Manager
- **I want to** see a summary on each ticket card — a short description, the action taken (or suggested), and a confidence score
- **So that** I can quickly triage the board and spot unusual or risky tickets without opening each one

#### Acceptance Criteria (Given-When-Then):

- **Scenario 1**: Card shows a complete summary
  - **Given** a ticket has been processed by the system
  - **When** its card is displayed on the dashboard
  - **Then** the card shows a short description, the action (such as refund, redelivery, or coupon — or a clear "needs human review" label), and a confidence score that is color-coded so high and low confidence are visually distinct

- **Scenario 2**: Very long ticket description
  - **Given** a ticket's description is extremely long
  - **When** its card is displayed on the dashboard
  - **Then** the description on the card is shortened with an ellipsis so the card stays readable, and the full description remains available in the detail view

### US-03: Review Full Ticket Details Before Acting
- **As a** Human Support Agent
- **I want to** click any ticket card to see the full details — complete description, the top 3 similar past cases with their scores, the action, the reasoning, and the drafted reply
- **So that** I can verify the system's decision and respond to the customer with confidence instead of blindly trusting or redoing the work

#### Acceptance Criteria (Given-When-Then):

- **Scenario 1**: Full details available
  - **Given** a processed ticket with similar past cases
  - **When** I click the ticket's card on the dashboard
  - **Then** a detail view shows the full description, the top 3 similar past cases with their similarity scores, the action taken or suggested, the plain-language reasoning, and the drafted customer reply

- **Scenario 2**: No similar past cases found
  - **Given** a processed ticket that has no similar past cases (for example, a novel issue)
  - **When** I open the ticket's detail view
  - **Then** the detail view clearly states that no similar past cases were found, while still showing the action, reasoning, and drafted reply so I can proceed with the review

### US-04: See New Decisions Reflected on the Board
- **As a** Support Manager
- **I want to** have the dashboard reflect the latest decisions when I open or refresh it
- **So that** I am always reviewing current information and never acting on stale or incomplete data

#### Acceptance Criteria (Given-When-Then):

- **Scenario 1**: Newly processed ticket appears
  - **Given** the system has just finished processing a new ticket
  - **When** I open or refresh the dashboard
  - **Then** the ticket appears in the correct lane with its summary, and the lane count badges are updated to include it

- **Scenario 2**: Data source temporarily unavailable
  - **Given** the system's data cannot be reached at the moment
  - **When** I open the dashboard
  - **Then** I see a clear message explaining that the board could not be loaded and offering a retry, instead of a broken or partially filled board

---

## 3. User Experience & Business Workflows

### 3.1 User Journey: Reviewing the Dashboard

1. The manager opens the dashboard. The screen shows two side-by-side lanes: **Auto-Resolved** and **Needs Human Review**, each with a count badge.
2. The manager scans the cards. Each card shows a shortened description, the action taken or suggested, and a color-coded confidence score.
3. For a ticket in the Needs Human Review lane, the manager clicks the card to open the detail view. The detail view shows:
   - The full ticket description.
   - The top 3 similar past cases, each with its similarity score.
   - The action suggested (refund, redelivery, or coupon) or the reason it was escalated.
   - The plain-language reasoning behind the decision.
   - The drafted customer reply.
4. The manager verifies the evidence, adjusts or finalizes their response, and marks the ticket handled.
5. For an auto-resolved ticket, the manager can likewise click through to confirm the system's action was appropriate before the reply is considered final.

### 3.2 Business Rules Governing Visibility and Actions

- **BR-01 (Lane Assignment)**: A ticket belongs to exactly one lane. It is shown in **Auto-Resolved** if and only if the system resolved it automatically; otherwise it appears in **Needs Human Review**. The dashboard does not make its own judgment — it reflects the outcome determined by the resolution process.
- **BR-02 (Confidence Display)**: The confidence score shown on a card and in the detail view is the same score the system used when making its decision. The dashboard never recomputes or changes it.
- **BR-03 (Evidence Fidelity)**: The top 3 similar past cases, action, reasoning, and drafted reply shown in the detail view are the exact items used in the decision — never recreated or paraphrased at display time.
- **BR-04 (Empty State)**: A lane with zero tickets always displays a clear empty-state message; it is never hidden or collapsed, so the manager always sees both lanes and their counts.
- **BR-05 (Read-Only View)**: In this feature, the dashboard is a viewing and reviewing surface. It does not change a ticket's lane, action, or reply. (Changing decisions is handled by a separate feature, Human Override Controls.)

---

## 4. User-Facing Edge Cases & Business Exceptions

| # | Trigger / Condition | Business Impact | Expected Handling |
|---|---|---|---|
| EC-01 | No tickets have been processed yet | The board appears empty and managers may think the system is broken | Both lanes show clear "no tickets here" empty-state messages with lane labels and zero count badges |
| EC-02 | A ticket was escalated because no similar past cases exist (novel issue) | Manager may see a detail view with missing evidence and distrust the escalation | The detail view explicitly states "no similar past cases found," and still shows the action, reasoning, and drafted reply so the review can continue |
| EC-03 | A ticket's description is very long | Cards become unreadable and the board is hard to scan | Cards show a shortened description with an ellipsis; the full text is available in the detail view |
| EC-04 | Confidence score sits exactly at the decision boundary | A manager may question why the ticket landed in a particular lane | Lane placement follows the resolution outcome exactly; the score is displayed unmodified and color-coded so boundary scores are clearly visible |
| EC-05 | Very high volume of processed tickets | The board becomes cluttered and important escalated tickets get buried | Cards remain compact with truncated descriptions, each lane shows a running count badge, and full details require a single click |
| EC-06 | The system's data is temporarily unavailable when the dashboard is opened | The manager sees stale or missing information and may act on outdated data | The dashboard shows a clear "could not load" message with a retry option instead of a partial or misleading board |

---

## 5. Related Features & Summary Dependencies

This feature is a downstream consumer of two existing features, as identified in `features/INDEX.md` ("Depends On: F3, F4"):

- **F3 · Resolution Engine** (`features/F3-resolution-engine/3_summary.md`) — Provides the processing outcome for every ticket (whether it was auto-resolved or escalated), the action taken, the confidence score, the top similar past cases, and the plain-language reasoning. The dashboard displays this information without modifying it.
- **F4 · Reply Drafting** (`features/F4-reply-drafting/3_summary.md`) — Provides the drafted customer reply for every ticket, shown in the detail view.

No other existing feature summaries are relevant to this feature. Future interactions:
- **F6 · Human Override Controls** (planned) — Will consume this dashboard's Needs Human Review lane and allow agents to change decisions from the card level.
- **F7 · Live Ticket Simulation** (planned) — Will feed new tickets into the board so they visibly land in the correct lane.
