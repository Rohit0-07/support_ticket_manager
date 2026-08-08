---
name: feature-planner
description: Skill for strategic decomposition of problem statements into discrete features with dependency graphs and build ordering.
---

# Skill: Feature Planner & Decomposition

## Purpose
Analyze a problem statement or design brief and produce a structured feature index — a registry of discrete features, their dependencies, and the optimal order to build them.

## Guidelines

### 1. Problem Statement Analysis
Before decomposing, answer these questions internally:
- Who are the **users/personas**? (Each persona often implies different feature sets)
- What are the **core workflows**? (Each workflow is a candidate for 1-2 features)
- What are the **data entities**? (Each entity's CRUD lifecycle is a candidate feature)
- What are the **integration points**? (External systems, APIs, file formats)

### 2. Feature Decomposition Patterns

| Pattern | When to Apply | Example |
|---|---|---|
| **By Workflow** | A user journey has distinct phases | "Ticket Ingestion" vs "Ticket Resolution" vs "SLA Reporting" |
| **By Persona** | Different users need different capabilities | "Agent Dashboard" vs "Manager Analytics" |
| **By Data Entity** | Core entities need independent lifecycle management | "Customer Management" vs "Order Management" |
| **By Integration** | External data sources need dedicated handling | "CSV Import" vs "API Webhook Receiver" |

### 3. Feature Naming Convention
- Use lowercase kebab-case: `ticket-ingestion`, `sla-tracking`, `agent-dashboard`
- Names should describe the CAPABILITY, not the implementation: `order-context-lookup` NOT `database-join-service`

### 4. Dependency Classification

```
HARD dependency:
  Feature B cannot even be SPEC'D without Feature A existing.
  Example: "SLA Tracking" HARD-depends on "Ticket Ingestion" (needs ticket timestamps)

SOFT dependency:
  Feature B can be SPEC'D and CODED independently, just needs Feature A at INTEGRATION time.
  Example: "Agent Dashboard" SOFT-depends on "Ticket Ingestion" (just needs to display ticket data)
```

### 5. Anti-Patterns (AVOID)

| ❌ Bad Decomposition | ✅ Better Decomposition |
|---|---|
| One mega-feature: "Support Ticket System" | Split: "Ticket Ingestion" + "Order Matching" + "SLA Tracking" + "Agent Dashboard" |
| Feature with 10+ user stories | Split into 2-3 features with 2-5 stories each |
| Feature named "Database Setup" | Infrastructure is NOT a feature — features are user-facing capabilities |
| Circular deps: A→B→A | Refactor: extract shared logic into a third feature C, then A→C, B→C |

### 6. Index Output Format
Store the feature index at `features/INDEX.md` using the standardized format defined in the `/plan-features` command.
