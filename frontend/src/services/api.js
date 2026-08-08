/**
 * Central API Client for Support Ticket Manager Backend
 */

const API_BASE = '/api/v1';

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  };

  if (config.body && typeof config.body === 'object') {
    config.body = JSON.stringify(config.body);
  }

  const response = await fetch(url, config);

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}: ${response.statusText}`;
    try {
      const errJson = await response.json();
      if (errJson && errJson.detail) {
        errorDetail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      }
    } catch (_) {
      // fallback to statusText
    }
    const error = new Error(errorDetail);
    error.status = response.status;
    throw error;
  }

  return response.json();
}

export const api = {
  // System
  getHealth: () => request('/health'),
  seedData: () => request('/seed', { method: 'POST' }),

  // Dashboard (F5)
  getDashboard: () => request('/dashboard'),
  getTicketDetail: (ticketId) => request(`/dashboard/tickets/${encodeURIComponent(ticketId)}`),

  // Resolution Engine (F3)
  resolveTicket: (ticketId) => request('/resolution/resolve', {
    method: 'POST',
    body: { ticket_id: ticketId },
  }),

  // Human Override Controls (F6)
  approveHumanDecision: (ticketId, agentId) => request(`/human-decisions/${encodeURIComponent(ticketId)}/approve`, {
    method: 'POST',
    body: { agent_id: agentId },
  }),
  overrideHumanDecision: (ticketId, agentId, action, replyBody) => request(`/human-decisions/${encodeURIComponent(ticketId)}/override`, {
    method: 'POST',
    body: { agent_id: agentId, action, reply_body: replyBody || null },
  }),
  rejectHumanDecision: (ticketId, agentId, reason) => request(`/human-decisions/${encodeURIComponent(ticketId)}/reject`, {
    method: 'POST',
    body: { agent_id: agentId, reason },
  }),
  listHumanDecisions: (skip = 0, limit = 50) => request(`/human-decisions?skip=${skip}&limit=${limit}`),
  getHumanDecision: async (ticketId) => {
    try {
      return await request(`/human-decisions/${encodeURIComponent(ticketId)}`);
    } catch (err) {
      if (err.status === 404) return null;
      throw err;
    }
  },

  // Live Ticket Simulation (F7)
  startSimulation: (paceSeconds) => request('/simulation/start', {
    method: 'POST',
    body: { pace_seconds: paceSeconds },
  }),
  pauseSimulation: () => request('/simulation/pause', { method: 'POST' }),
  resumeSimulation: () => request('/simulation/resume', { method: 'POST' }),
  stopSimulation: () => request('/simulation/stop', { method: 'POST' }),
  getSimulationStatus: () => request('/simulation/status'),
};
