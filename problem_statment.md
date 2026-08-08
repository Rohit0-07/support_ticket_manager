2

Automatic Zoom
Q4. Zepto Support Ticket Manager
DigiPlus IT Agentic AI Hackathon · 6-hour build · Thakur College of Engineering & Technology

1. Challenge
   A 10-minute-delivery company gets thousands of support tickets a day — "items missing", "order late", "wrong
   item", "refund not received". Ninety percent are near-identical to tickets already resolved hundreds of times before,
   yet each one still waits for a human to apply the same fix as last time.
2. Problem Statement
   Build a resolution system that learns from history: for each new ticket, find the most similar past resolved tickets,
   auto-resolve the same way when confidence is high (refund / redelivery / coupon), and queue for human review
   when it is not. The customer gets a drafted reply either way.
3. Dataset
   File Contents
   resolved_tickets.csv Historical resolved tickets: description, action taken, resolution note, CSAT.
   new_tickets.csv Incoming tickets: description and linked order.
   orders_context.csv Order facts: items, value, delivery time, status.
4. Reference Flow (User Perspective)
   Today — the pain:
5. "Milk packet missing" — the 4,000th ticket today — waits in a queue for hours.
6. An agent reads it, recognises it instantly, refunds Rs 40 — a decision history already knew.
7. Multiplied by thousands, daily; unusual tickets wait just as long behind routine ones.
   With your system:
8. A new ticket is matched to its most similar past resolved tickets in seconds.
9. Routine tickets are auto-resolved the way history resolved them, with a drafted reply.
10. Unusual tickets land in a human lane with precedents and a suggested action attached.
11. The board shows what was auto-resolved, why, and with what confidence.
12. Expected Components in the Solution
    Component Expectation
    Backend Similarity search over resolved tickets (TF-IDF is fine); confidence threshold decides auto vs
    human; simulated refund/redeliver/coupon actions; decisions logged.
    Frontend Two-lane board (auto-resolved / needs-human); each ticket shows top-3 similar past cases,
    chosen action, confidence, and drafted reply.
    AI layer Decide act-vs-escalate with an explicit confidence score; generate the reply; answer "why
    this action?" with the precedent tickets.
    Deployment Live public URL (free tier) + public GitHub repo.
    Bonus Human approve/override controls with logging; live ticket-stream simulation; embeddings
    instead of TF-IDF.
    Build the core completely before touching anything in the Bonus row. A small finished system beats a large broken one.
13. Validation Scenarios — How an Ideal System Behaves
    • A clear missing-item ticket with strong precedents is auto-resolved with the same action, a refund no larger than
    the order value, and a reply citing its top-3 precedents.
    • A novel ticket with low similarity goes to the human lane — the system never acts on weak evidence.
    • When top precedents disagree on the action, the ticket is queued, not guessed.
    • A ticket on a cancelled order never triggers redelivery — order context constrains actions.
