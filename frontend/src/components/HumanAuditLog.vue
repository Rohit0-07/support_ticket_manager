<template>
  <div class="audit-container glass-panel">
    <div class="audit-header">
      <div>
        <h2>Human Decision Audit Log (F6)</h2>
        <p>Comprehensive historical log of all human agent approvals, overrides, and rejections</p>
      </div>

      <button class="btn btn-secondary" @click="fetchAuditLog">
        <RefreshCw :size="15" :class="{ spin: loading }" />
        Refresh
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="audit-loading">
      <Loader2 :size="28" class="spin" />
      <span>Loading audit records...</span>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="audit-error">
      <AlertOctagon :size="24" />
      <span>{{ error }}</span>
    </div>

    <!-- Empty Audit Log -->
    <div v-else-if="items.length === 0" class="audit-empty">
      <History :size="36" class="empty-icon" />
      <p>No human decisions have been recorded yet.</p>
      <small>When human agents approve, override, or reject tickets, they will be logged here.</small>
    </div>

    <!-- Audit Table -->
    <div v-else class="table-wrapper">
      <table class="audit-table">
        <thead>
          <tr>
            <th>Ticket ID</th>
            <th>Order ID</th>
            <th>Agent ID</th>
            <th>Decision Action</th>
            <th>Original Suggestion</th>
            <th>Final Action</th>
            <th>Details / Reason</th>
            <th>Timestamp</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.ticket_id">
            <td class="col-ticket">#{{ item.ticket_id }}</td>
            <td class="col-order">{{ item.order_id }}</td>
            <td class="col-agent">
              <span class="agent-tag">{{ item.agent_id }}</span>
            </td>
            <td>
              <span class="action-pill" :class="`pill-${item.agent_action}`">
                {{ item.agent_action.toUpperCase() }}
              </span>
            </td>
            <td>{{ item.original_action ? item.original_action.toUpperCase() : '—' }}</td>
            <td>{{ item.final_action ? item.final_action.toUpperCase() : '—' }}</td>
            <td class="col-detail">
              <span v-if="item.rejection_reason" class="reason-text">
                Reason: {{ item.rejection_reason }}
              </span>
              <span v-else-if="item.final_reply" class="reply-preview" :title="item.final_reply">
                Edited Reply: "{{ item.final_reply }}"
              </span>
              <span v-else class="text-muted">—</span>
            </td>
            <td class="col-time">{{ formatTime(item.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { RefreshCw, Loader2, AlertOctagon, History } from 'lucide-vue-next';
import { api } from '../services/api';

const items = ref([]);
const total = ref(0);
const loading = ref(true);
const error = ref(null);

async function fetchAuditLog() {
  loading.value = true;
  error.value = null;
  try {
    const res = await api.listHumanDecisions(0, 100);
    items.value = res.items || [];
    total.value = res.total || 0;
  } catch (err) {
    error.value = err.message || 'Failed to load human decision audit log.';
  } finally {
    loading.value = false;
  }
}

function formatTime(isoStr) {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    return d.toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch (_) {
    return isoStr;
  }
}

onMounted(() => {
  fetchAuditLog();
});
</script>

<style scoped>
.audit-container {
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.audit-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.audit-header h2 {
  font-size: 1.25rem;
}

.audit-header p {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.audit-loading, .audit-error, .audit-empty {
  padding: 3rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  color: var(--text-secondary);
  text-align: center;
}

.table-wrapper {
  overflow-x: auto;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
}

.audit-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
  text-align: left;
}

.audit-table th {
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-secondary);
  font-weight: 600;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-color);
  white-space: nowrap;
}

.audit-table td {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-primary);
}

.audit-table tr:hover {
  background: rgba(255, 255, 255, 0.02);
}

.col-ticket {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
}

.col-order {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.agent-tag {
  background: rgba(99, 102, 241, 0.15);
  color: #818cf8;
  padding: 0.2rem 0.5rem;
  border-radius: var(--radius-sm);
  font-size: 0.75rem;
  font-weight: 600;
}

.action-pill {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 0.2rem 0.6rem;
  border-radius: var(--radius-full);
}

.pill-approve {
  background: rgba(16, 185, 129, 0.18);
  color: #34d399;
}

.pill-override {
  background: rgba(245, 158, 11, 0.18);
  color: #fbbf24;
}

.pill-reject {
  background: rgba(239, 68, 68, 0.18);
  color: #f87171;
}

.col-detail {
  max-width: 250px;
}

.reason-text {
  color: #f87171;
  font-size: 0.8rem;
}

.reply-preview {
  color: #c7d2fe;
  font-size: 0.8rem;
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.col-time {
  font-size: 0.75rem;
  color: var(--text-muted);
  white-space: nowrap;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  100% { transform: rotate(360deg); }
}
</style>
