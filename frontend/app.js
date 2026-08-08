/**
 * Two-Lane Dashboard frontend (FEAT-005).
 * Contracts documented in features/F5-two-lane-dashboard/2_tech_spec.md §2.5.
 * Vanilla JS — no framework. All functions are global.
 */

const API_BASE = "/api/v1";

/**
 * Fetch GET /api/v1/dashboard and render the board. On failure shows the
 * error banner with a Retry button (US-04 S2, EC-06). Never renders a
 * partial board.
 * @returns {Promise<void>}
 */
async function loadDashboard() {
  hideLoadError();
  try {
    const resp = await fetch(`${API_BASE}/dashboard`);
    if (!resp.ok) {
      throw new Error(`board request failed with status ${resp.status}`);
    }
    const board = await resp.json();
    renderBoard(board);
  } catch (err) {
    showLoadError("Couldn't load the board. Please try again.");
  }
}

/**
 * Render both lane sections into #board. Both lanes are always rendered,
 * even with zero tickets (BR-04, EC-01).
 * @param {DashboardBoard} board - payload from GET /api/v1/dashboard
 */
function renderBoard(board) {
  const auto = renderLane(board.auto_resolved, "lane--auto");
  const review = renderLane(board.needs_review, "lane--review");
  document.getElementById("lane-auto").replaceWith(auto);
  document.getElementById("lane-review").replaceWith(review);
}

/**
 * Render a single lane: header label + count badge + cards or empty-state
 * message "No tickets here yet." (US-01 S1/S2, EC-01).
 * @param {DashboardLaneSection} section
 * @param {string} laneClass - 'lane--auto' | 'lane--review'
 * @returns {HTMLElement}
 */
function renderLane(section, laneClass) {
  const sectionEl = document.createElement("section");
  sectionEl.className = `lane ${laneClass}`;

  const header = document.createElement("header");
  header.className = "lane-header";

  const title = document.createElement("h2");
  title.textContent = section.label;

  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = String(section.count);

  header.appendChild(title);
  header.appendChild(badge);

  const cards = document.createElement("div");
  cards.className = "cards";

  if (section.tickets.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No tickets here yet.";
    cards.appendChild(empty);
  } else {
    section.tickets.forEach((card) => {
      cards.appendChild(renderCard(card));
    });
  }

  sectionEl.appendChild(header);
  sectionEl.appendChild(cards);
  return sectionEl;
}

/**
 * Render one ticket card: truncated description, action label (or
 * "Needs human review" when escalated), and a color-coded confidence
 * badge (US-02 S1/S2, EC-03, EC-05). Clicking calls openDetail(ticket_id).
 * @param {DashboardTicketCard} card
 * @returns {HTMLElement}
 */
function renderCard(card) {
  const el = document.createElement("article");
  el.className = "card";
  el.addEventListener("click", () => openDetail(card.ticket_id));

  const desc = document.createElement("p");
  desc.className = "card-desc";
  desc.textContent = escapeHtml(card.description_preview);

  const meta = document.createElement("div");
  meta.className = "card-meta";

  const action = document.createElement("span");
  action.className = "action-tag";
  if (card.auto_resolved && card.action) {
    action.textContent = card.action;
  } else if (card.auto_resolved) {
    action.textContent = "Resolved";
  } else {
    action.textContent = "Needs human review";
  }

  const confidence = document.createElement("span");
  confidence.className = `confidence ${confidenceClass(card.confidence_level)}`;
  confidence.textContent = `${Math.round(card.confidence * 100)}% · ${card.confidence_level}`;

  meta.appendChild(action);
  meta.appendChild(confidence);

  el.appendChild(desc);
  el.appendChild(meta);
  return el;
}

/**
 * Fetch GET /api/v1/dashboard/tickets/{ticketId} and render the detail
 * panel (US-03 S1/S2). Shows a loading state, then the full payload.
 * @param {string} ticketId
 * @returns {Promise<void>}
 */
async function openDetail(ticketId) {
  const panel = document.getElementById("detail-panel");
  const body = document.getElementById("detail-body");
  panel.hidden = false;
  body.innerHTML = '<p class="fallback">Loading ticket details…</p>';

  try {
    const resp = await fetch(`${API_BASE}/dashboard/tickets/${encodeURIComponent(ticketId)}`);
    if (!resp.ok) {
      if (resp.status === 404) {
        body.innerHTML = '<p class="fallback">This ticket has not been processed yet.</p>';
      } else {
        body.innerHTML = '<p class="fallback">Couldn\'t load the ticket details.</p>';
      }
      return;
    }
    const detail = await resp.json();
    renderDetail(detail);
  } catch (err) {
    body.innerHTML = '<p class="fallback">Couldn\'t load the ticket details.</p>';
  }
}

/**
 * Render full ticket detail: full description, top-3 similar past cases
 * with scores, action, reasoning, drafted reply (US-03 S1). When
 * similar_cases_status === 'none', renders "No similar past cases were
 * found." and still shows action/reasoning/reply (US-03 S2, EC-02).
 * @param {DashboardTicketDetail} detail
 */
function renderDetail(detail) {
  const body = document.getElementById("detail-body");
  const title = document.getElementById("detail-title");
  title.textContent = `Ticket ${detail.ticket_id}`;

  const frag = document.createDocumentFragment();

  const appendSection = (heading, node) => {
    const h = document.createElement("h3");
    h.textContent = heading;
    frag.appendChild(h);
    frag.appendChild(node);
  };

  // Description (full, untruncated — EC-03)
  const desc = document.createElement("p");
  desc.textContent = escapeHtml(detail.description);
  appendSection("Description", desc);

  // Action + confidence
  const meta = document.createElement("div");
  meta.className = "kv";
  meta.innerHTML = "";
  const actionLabel = detail.action || (detail.auto_resolved ? "Auto-resolved" : "Needs human review");
  const actionP = document.createElement("p");
  actionP.textContent = actionLabel;
  const confP = document.createElement("p");
  confP.textContent = `${Math.round(detail.confidence * 100)}% (${detail.confidence_level})`;
  const metaWrap = document.createElement("div");
  metaWrap.className = "kv";
  metaWrap.appendChild(metaItem("Action", actionLabel));
  metaWrap.appendChild(metaItem("Confidence", confP.textContent));
  appendSection("Decision", metaWrap);

  // Reasoning (verbatim — BR-03)
  const reasoning = document.createElement("div");
  reasoning.className = "reasoning";
  reasoning.textContent = escapeHtml(detail.reasoning);
  appendSection("Reasoning", reasoning);

  // Similar past cases
  if (detail.similar_cases_status === "none" || detail.similar_cases.length === 0) {
    const none = document.createElement("p");
    none.className = "fallback";
    none.textContent = "No similar past cases were found.";
    appendSection("Similar Past Cases", none);
  } else {
    appendSection("Similar Past Cases", renderSimilarCases(detail.similar_cases));
  }

  // Drafted reply
  if (detail.reply && detail.reply.final_body) {
    const reply = document.createElement("div");
    reply.className = "reply-box";
    reply.textContent = escapeHtml(detail.reply.final_body);
    appendSection("Drafted Reply", reply);
  } else {
    const fallback = document.createElement("p");
    fallback.className = "fallback";
    fallback.textContent = "No drafted reply available yet.";
    appendSection("Drafted Reply", fallback);
  }

  body.replaceChildren(frag);
}

/**
 * Render the top-3 similar past cases list, each with its similarity score.
 * @param {Array<SimilarCaseEvidence>} cases
 * @returns {HTMLElement}
 */
function renderSimilarCases(cases) {
  const container = document.createElement("div");
  cases.forEach((caseItem) => {
    const box = document.createElement("div");
    box.className = "case";

    const head = document.createElement("div");
    head.className = "case-head";

    const id = document.createElement("span");
    id.textContent = escapeHtml(caseItem.ticket_id);

    const score = document.createElement("span");
    score.textContent = `${Math.round(caseItem.similarity_score * 100)}% match`;

    head.appendChild(id);
    head.appendChild(score);

    const desc = document.createElement("p");
    desc.textContent = escapeHtml(caseItem.description);

    const note = document.createElement("p");
    note.className = "fallback";
    note.textContent = `${escapeHtml(caseItem.action_taken)} — ${escapeHtml(caseItem.resolution_note)}`;

    box.appendChild(head);
    box.appendChild(desc);
    box.appendChild(note);
    container.appendChild(box);
  });
  return container;
}

/**
 * Show the "Couldn't load the board" banner with a Retry button that
 * re-invokes loadDashboard (US-04 S2, EC-06).
 * @param {string} message
 */
function showLoadError(message) {
  document.getElementById("error-message").textContent = message;
  document.getElementById("error-banner").hidden = false;
}

function hideLoadError() {
  document.getElementById("error-banner").hidden = true;
}

/**
 * Map a ConfidenceLevel to the CSS modifier class:
 * 'confidence--high' | 'confidence--medium' | 'confidence--low'.
 * @param {string} level
 * @returns {string}
 */
function confidenceClass(level) {
  switch (level) {
    case "high":
      return "confidence--high";
    case "medium":
      return "confidence--medium";
    case "low":
      return "confidence--low";
    default:
      return "confidence--medium";
  }
}

/**
 * Escape user-controlled text before injecting into innerHTML (XSS safety).
 * @param {string} text
 * @returns {string}
 */
function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function metaItem(key, value) {
  const k = document.createElement("span");
  k.className = "k";
  k.textContent = key;
  const v = document.createElement("span");
  v.textContent = escapeHtml(value);
  const p = document.createElement("p");
  p.className = "kv";
  p.appendChild(k);
  p.appendChild(v);
  return p;
}

// Wire up events
document.getElementById("retry-btn").addEventListener("click", loadDashboard);
document.getElementById("detail-close").addEventListener("click", () => {
  document.getElementById("detail-panel").hidden = true;
});
document.getElementById("detail-panel").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) {
    event.currentTarget.hidden = true;
  }
});

document.addEventListener("DOMContentLoaded", loadDashboard);
