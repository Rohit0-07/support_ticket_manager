# Non-Technical Specification: Similarity Engine

| Metadata | Details |
|---|---|
| **Feature Name** | Similarity Engine |
| **Feature ID** | FEAT-002 (F2) |
| **Status** | Draft |
| **Author** | Product Manager (AI) |
| **Created Date** | 2026-08-08 |

---

## 1. Executive Summary & Problem Statement

### 1.1 Problem Description
A 10-minute-delivery company receives thousands of support tickets a day — "items missing", "order late", "wrong item", "refund not received". The overwhelming majority are near-identical to tickets that support agents have already resolved hundreds of times before, yet every single one still sits in a queue until a human agent reads it and re-applies the same fix.

Before this system, there was no way to automatically recognise "we have seen this exact problem before and here is what we did." The **Similarity Engine** provides that recognition: for every incoming ticket, it searches the complete history of resolved tickets and returns the most similar past cases, ranked by how closely they match, so that routine problems can be handled the way history handled them and unusual problems can be spotted early.

### 1.2 Target Personas
- **Automated Resolution System (primary)**: The next stage of the pipeline consumes the matching results to decide whether to auto-resolve a ticket or send it to a human.
- **Support Agents**: Indirectly benefit — they receive tickets only when genuinely needed, and when they do receive one, it arrives with relevant past cases already attached.
- **Support Managers / Demo Viewers**: Observe the match results and confidence on the dashboard to understand *why* the system acted the way it did.

### 1.3 Expected Business Value
- Routine, repetitive tickets stop waiting behind humans and get handled in the same way history handled them — almost instantly.
- Support agents focus their time on genuinely new or unusual tickets instead of re-solving the same 10 issues thousands of times.
- Every decision is traceable: past cases shown alongside a new ticket explain the reasoning, which builds trust in the system.

---

## 2. User Stories & Acceptance Criteria

### US-01: Find the Most Similar Past Cases for Any New Ticket
- **As a** Automated Resolution System
- **I want to** retrieve the most similar resolved tickets for any incoming ticket description, ranked from closest match to weakest
- **So that** routine tickets can be resolved exactly the way history already resolved them, without waiting for a human

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: Ticket matches well-known past cases
  - **Given** a new ticket saying "milk packet missing from order" and a history containing several previously resolved "missing item" tickets
  - **When** the resolution system requests similar past cases for this ticket
  - **Then** the three most similar resolved tickets are returned, ranked from most similar to least similar
- **Scenario 2**: Ticket has no meaningful matches in history
  - **Given** a new ticket describing a completely novel problem never seen in the resolved history
  - **When** the resolution system requests similar past cases for this ticket
  - **Then** the result clearly indicates that no sufficiently similar past cases exist, so the ticket will not be treated as routine

### US-02: See How Closely Each Past Case Matches
- **As a** Support Manager
- **I want to** see a similarity rating next to each matched past case shown on a ticket
- **So that** I can judge how confident the system's match really is before trusting an automated decision

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: Past case is a strong match
  - **Given** a ticket whose description closely resembles a past resolved ticket
  - **When** the match results are displayed to me
  - **Then** the past ticket is shown with a high similarity rating (near the top of the possible range)
- **Scenario 2**: Past case is only a loose match
  - **Given** a ticket that shares only a few words with a past resolved ticket
  - **When** the match results are displayed to me
  - **Then** the past ticket is shown with a low similarity rating, and the low rating is visually obvious so the weak match is not mistaken for a strong one

### US-03: Get Match Results Quickly Enough to Be Useful in Real Time
- **As a** Automated Resolution System
- **I want to** receive the matching results almost immediately after submitting a new ticket
- **So that** customers get a response (auto-resolution or human review) without a noticeable delay

#### Acceptance Criteria (Given-When-Then):
- **Scenario 1**: Typical ticket processed at normal volume
  - **Given** a single new ticket submitted against a full history of resolved tickets
  - **When** similar past cases are requested
  - **Then** the ranked results are returned within half a second
- **Scenario 2**: Large volume of tickets processed back-to-back
  - **Given** several new tickets submitted in quick succession
  - **When** similar past cases are requested for each one
  - **Then** each request still returns its results promptly without degrading noticeably from the first to the last

---

## 3. User Experience & Business Workflows

### 3.1 End-to-End Journey
1. A new support ticket arrives and is registered in the system with its description.
2. The Automated Resolution System asks the Similarity Engine to find the past resolved tickets that most closely match the new ticket's description.
3. The Similarity Engine examines the full history of resolved tickets, ranks them by how closely their descriptions match the new ticket, and returns the top three along with a similarity rating for each.
4. The results are handed to the next stage (Resolution Engine), which uses them — together with order facts — to decide whether to auto-resolve or escalate to a human.
5. On the dashboard, any viewer can open a ticket and see the past cases it was matched against, with their similarity ratings, making the reasoning visible.

### 3.2 Business Rules Governing Results
- Exactly the three closest past cases are returned per ticket (the top three), never more and never fewer when at least three matches exist.
- Results are ordered from closest match to weakest match — the number-one result is the single most similar past case in history.
- Every returned past case carries a similarity rating between "no similarity" and "perfect match", so downstream stages and viewers can judge confidence consistently.
- If no past case is similar enough to be meaningful, the system must say so explicitly rather than forcing a weak match to the top.
- The matching behaviour is consistent and repeatable: the same ticket description always produces the same ranked results.

---

## 4. User-Facing Edge Cases & Business Exceptions

| # | Trigger / Condition | Business Impact | Expected Handling |
|---|---|---|---|
| EC-01 | A new ticket arrives with an empty or blank description | The system cannot tell what the problem is; auto-resolution would be reckless | Return no match results and flag the ticket as "cannot be matched" so it goes straight to a human agent for review |
| EC-02 | No resolved tickets exist in history yet (fresh system) | There is nothing to match against; every ticket would appear routine by default | Return an empty result with a clear "no history available" status so every ticket is routed to a human until history accumulates |
| EC-03 | A ticket description is extremely short (e.g., a single word like "refund") | Match quality is unreliable; the results may look stronger than they really are | Return whatever matches exist with appropriately low similarity ratings, so downstream logic does not treat the ticket as a confident routine case |
| EC-04 | Two or more past resolved tickets are word-for-word identical to each other | The top three results may all be the same case repeated, inflating the apparent number of supporting precedents | Show distinct past cases in the top three rather than the same case repeated, so the results reflect genuinely different precedents |
| EC-05 | Several unrelated past tickets tie at the same similarity level | It is unclear which past cases should rank higher, and results may feel arbitrary | Break ties in a fixed, predictable way so the same ticket always yields the same ordering, and no past case is favoured by chance |
| EC-06 | A ticket description is extremely long and rambling | Matching quality can be diluted by irrelevant words, and processing may slow down | Only the most relevant part of the description should influence the match so the results stay accurate for long-winded tickets |

---

## 5. Related Features & Summary Dependencies

- **F1 · Data Ingestion & Storage** (`features/F1-data-ingestion/3_summary.md`) — **Required dependency.** The Similarity Engine reads from the persisted store of resolved tickets that F1 loads. If the history is not loaded, the Similarity Engine has nothing to match against (see EC-02).
- **F3 · Resolution Engine** — **Downstream consumer** (per `features/INDEX.md` dependency graph). Consumes the top-three match results to decide auto-resolve vs. escalate. No `3_summary.md` exists yet.
- **F4 · Reply Drafting** — **Indirect downstream consumer.** Cites the matched past cases in drafted replies to customers. No `3_summary.md` exists yet.
- **F5 · Two-Lane Dashboard** — **Indirect downstream consumer.** Displays the matched past cases and their similarity ratings on ticket cards. No `3_summary.md` exists yet.

> No other existing feature summaries interact with this feature at this time.
