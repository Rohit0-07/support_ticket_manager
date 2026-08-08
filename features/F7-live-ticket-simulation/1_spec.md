# Non-Technical Specification: Live Ticket Simulation

| Metadata | Details |
|---|---|
| **Feature Name** | Live Ticket Simulation |
| **Feature ID** | FEAT-007 (F7) |
| **Status** | Draft |
| **Author** | Product Manager (AI) |
| **Created Date** | 2026-08-08 |

---

## 1. Executive Summary & Problem Statement

### 1.1 Problem Description
- The dashboard currently displays tickets only after they have already been processed as a batch. When a support manager or stakeholder wants to see the system in action — how a fresh ticket enters, gets analyzed, and lands in the correct lane — there is no way to demonstrate this live.
- Reviewing a static, pre-populated board makes it hard to convey throughput, confidence-based routing, and the "real-time" nature of the tool. A demo viewer must manually refresh or reload to see changes, which is slow and unconvincing.
- This feature introduces a **live ticket simulation**: a controlled, one-at-a-time stream of queued tickets that visibly animate into the correct lane on the dashboard, so the full processing journey can be watched in real time.

### 1.2 Target Personas
- **Demo viewers** — support managers, product stakeholders, and prospective users watching a live demonstration of the system.
- **Support agents** — agents who want to observe how incoming tickets are routed as they arrive.
- **Support manager / administrator** — the person who starts, paces, pauses, and stops the simulation for the audience.

### 1.3 Expected Business Value
- Enables compelling, accurate live demos of the full ticket journey without pre-recorded videos or manual screen sharing.
- Builds stakeholder confidence in automated resolution by showing tickets being routed to the Auto-Resolved or Needs Human Review lanes in real time.
- Provides a natural "dry run" mechanism to validate that the processing pipeline handles all queued tickets correctly before going live.
- Gives viewers a clear sense of system throughput and queue processing progress.

---

## 2. User Stories & Acceptance Criteria

### US-01: Start a Live Ticket Simulation
- **As a** support manager / demo viewer
- **I want to** start a simulation that feeds queued tickets into the dashboard one at a time
- **So that** I can watch each ticket flow through processing and visibly land in the correct lane

#### Acceptance Criteria (Given-When-Then):

- **Scenario 1: Simulation starts with tickets available**
  - **Given** the dashboard is open and there is at least one ticket remaining in the simulation queue
  - **When** I click the "Start Simulation" button
  - **Then** tickets begin appearing on the board one at a time at the configured pace, and each ticket lands in either the "Auto-Resolved" or "Needs Human Review" lane according to its processing outcome

- **Scenario 2: Simulation requested when the queue is empty**
  - **Given** every ticket in the simulation queue has already been processed
  - **When** I click the "Start Simulation" button
  - **Then** the system informs me that there are no tickets left to simulate, and no tickets are processed

- **Scenario 3: Ticket appears with full detail after landing**
  - **Given** a simulation is running and a ticket has just landed in a lane
  - **When** I click on the newly arrived ticket card
  - **Then** the ticket detail view opens and shows the full description, similar past cases, suggested action, confidence, and the drafted reply — consistent with how other tickets are viewed on the dashboard

### US-02: Control the Simulation Pace and Lifecycle
- **As a** support manager / demo viewer
- **I want to** set the pace and pause, resume, or stop the simulation at any time
- **So that** I can control the demonstration and match it to the audience's attention

#### Acceptance Criteria (Given-When-Then):

- **Scenario 1: Configure the pace before starting**
  - **Given** the dashboard is open and no simulation is currently running
  - **When** I set the delay between tickets (for example, a number of seconds between arrivals) and click "Start Simulation"
  - **Then** the simulation honors the chosen pace, and the arrival gap is respected between consecutive tickets

- **Scenario 2: Pause and resume the simulation**
  - **Given** a simulation is actively processing tickets
  - **When** I click "Pause"
  - **Then** no further tickets are processed, the progress indicator holds at its current value, and when I click "Resume" the simulation continues processing the remaining tickets from where it left off

- **Scenario 3: Stop the simulation early**
  - **Given** a simulation is actively processing tickets
  - **When** I click "Stop"
  - **Then** processing halts immediately, the remaining tickets stay in the queue unprocessed, and the controls return to a ready state so I can start again later

### US-03: Track Simulation Progress
- **As a** support manager / demo viewer
- **I want to** see a live progress indicator of how many tickets have been processed
- **So that** I know how far along the demonstration is and how many tickets remain

#### Acceptance Criteria (Given-When-Then):

- **Scenario 1: Progress updates on each ticket**
  - **Given** a simulation is running with a total queue of, for example, 20 tickets
  - **When** each ticket finishes processing and lands in a lane
  - **Then** the progress indicator updates to reflect the number processed out of the total (for example, "12 of 20"), including a per-lane count in each lane's badge

- **Scenario 2: Completion state**
  - **Given** the last ticket in the queue has just been processed
  - **When** the simulation finishes
  - **Then** the progress indicator shows the full total processed, the simulation automatically reaches a completed state, and I am notified that the simulation has finished

---

## 3. User Experience & Business Workflows

### 3.1 Workflow: Running a Live Simulation

1. The viewer opens the dashboard and sees the existing two-lane board.
2. The viewer configures the simulation pace by selecting the delay between ticket arrivals (e.g., 2, 3, or 5 seconds).
3. The viewer clicks **Start Simulation**.
4. The system picks the next unprocessed ticket from the simulation queue.
5. The ticket is processed through the full resolution pipeline (assessing similar past cases, applying order context, deciding on auto-resolution or escalation, and preparing a drafted reply).
6. A ticket card appears on the board, animates into its lane — **Auto-Resolved** or **Needs Human Review** — and the lane count badge increments.
7. The progress indicator updates.
8. Steps 4–7 repeat at the configured pace until the queue is empty, or until the viewer pauses or stops the simulation.
9. On completion, the viewer sees a summary of the processed tickets and can restart the simulation if desired.

### 3.2 Business Rules
- Only tickets that have not yet been processed by the simulation may be queued and sent through the pipeline.
- A ticket may be routed to either lane only according to its processing outcome; the simulation must not force a ticket into a lane.
- Only one simulation may run at a time. Starting a second simulation while one is active must be prevented.
- The simulation is a demonstration tool: it must not delete, duplicate, or permanently alter tickets that have already been processed.
- All tickets processed during the simulation must be visible in the standard dashboard lanes and detail views afterward, consistent with how tickets processed outside the simulation appear.
- The pace setting must respect a sensible minimum delay so that tickets do not flood the board faster than a viewer can follow.

---

## 4. User-Facing Edge Cases & Business Exceptions

| # | Trigger / Condition | Business Impact | Expected Handling |
|---|---|---|---|
| EC-01 | The viewer clicks "Start Simulation" while a simulation is already running | Two streams could interleave, corrupting lane counts and confusing the demonstration | The system prevents a second simulation from starting and shows a clear message that a simulation is already in progress |
| EC-02 | A queued ticket is missing a description or has unreadable content | The ticket cannot be meaningfully processed, and a garbled card could mislead the audience | The system skips that ticket with a visible warning in the progress area, continues with the remaining tickets, and reports the skipped count at the end |
| EC-03 | The processing pipeline becomes unavailable mid-simulation (e.g., data cannot be loaded) | Tickets silently stop landing on the board, making the demo appear broken | The system pauses the simulation, shows a clear error message, and offers a way to retry or stop; progress up to that point is preserved |
| EC-04 | The viewer refreshes the page while a simulation is running | The in-memory simulation state is lost, and the audience sees an abrupt restart | The system indicates that the previous simulation cannot be resumed, preserves already-processed tickets on the board, and offers the viewer the option to start a new simulation |
| EC-05 | The viewer sets the arrival delay to zero or an extremely small value | Tickets could flood the board so fast the audience cannot follow, undermining the demo | The system enforces a minimum allowed delay and adjusts any invalid value to that minimum, with a brief note to the viewer |
| EC-06 | All tickets in the queue have already been processed in a previous run | The viewer clicks "Start" expecting new activity, but nothing happens | The system clearly states the queue is empty, shows final counts from the last run, and offers no further processing until new tickets become available |

---

## 5. Related Features & Summary Dependencies

- **F5 · Two-Lane Dashboard** — `features/F5-two-lane-dashboard/3_summary.md`
  - Direct dependency (per `features/INDEX.md`). The simulation is a downstream consumer of the dashboard board: tickets processed by the simulation must appear in the same two-lane board and open the same ticket detail view. The dashboard's lane assignment, confidence color-coding, and card/detail rendering behavior are reused as-is.

- **F2 · Similarity Engine, F3 · Resolution Engine, F4 · Reply Drafting** — upstream pipeline participants referenced in `features/INDEX.md`
  - While not direct dependencies of this feature, every ticket fed by the simulation is processed through the standard resolution pipeline (similarity analysis → resolution decision → reply drafting) before landing on the dashboard. This feature relies on those existing capabilities and does not introduce new processing behavior.

- **F6 · Human Override Controls** — `features/F6-human-override-controls/3_summary.md`
  - Adjacent bonus feature sharing the same dashboard. If both features are active, tickets that land in the "Needs Human Review" lane during a simulation must remain available for the same approve/reject/override actions as any other ticket.

---

*End of Specification — FEAT-007 (F7) Live Ticket Simulation*
