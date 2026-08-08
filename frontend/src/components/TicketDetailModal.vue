<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal-panel glass-panel">
      <!-- Modal Header -->
      <div class="modal-header">
        <div class="header-title-group">
          <span class="ticket-badge">Ticket #{{ ticketId }}</span>
          <span class="order-badge" v-if="detail?.order_id">Order {{ detail.order_id }}</span>
          <span class="lane-badge" :class="detail?.lane === 'auto_resolved' ? 'badge-auto-res' : 'badge-needs-rev'">
            {{ detail?.lane === 'auto_resolved' ? 'Auto-Resolved' : 'Needs Review' }}
          </span>
        </div>

        <button class="close-btn" @click="$emit('close')">
          <X :size="20" />
        </button>
      </div>

      <!-- Loading State -->
      <div v-if="loading" class="modal-loading">
        <Loader2 :size="32" class="spin" />
        <p>Fetching full decision analysis &amp; precedent evidence...</p>
      </div>

      <!-- Error State -->
      <div v-else-if="error" class="modal-error">
        <AlertOctagon :size="32" class="icon-err" />
        <h4>Failed to Load Ticket Details</h4>
        <p>{{ error }}</p>
        <button class="btn btn-secondary" @click="fetchDetail">Retry</button>
      </div>

      <!-- Detail Body -->
      <div v-else-if="detail" class="modal-body">
        <!-- Ticket Customer Query Section -->
        <div class="detail-section">
          <h4 class="section-title">
            <MessageSquare :size="16" />
            Customer Issue Description
          </h4>
          <div class="description-box">
            {{ detail.description }}
          </div>
        </div>

        <!-- System Decision & Confidence Section -->
        <div class="detail-section">
          <h4 class="section-title">
            <Cpu :size="16" />
            Resolution Engine Analysis
          </h4>
          <div class="decision-grid">
            <!-- Confidence Meter -->
            <div class="decision-card">
              <span class="card-label">Confidence Score</span>
              <div class="confidence-meter-group">
                <div class="confidence-score-val" :class="`text-${detail.confidence_level}`">
                  {{ Math.round(detail.confidence * 100) }}%
                </div>
                <div class="meter-bar-bg">
                  <div
                    class="meter-bar-fill"
                    :class="`fill-${detail.confidence_level}`"
                    :style="{ width: Math.round(detail.confidence * 100) + '%' }"
                  ></div>
                </div>
                <span class="meter-bucket">{{ detail.confidence_level.toUpperCase() }} CONFIDENCE</span>
              </div>
            </div>

            <!-- Action Suggested / Taken -->
            <div class="decision-card">
              <span class="card-label">System Action</span>
              <div class="action-value-tag" :class="actionBadgeClass">
                {{ (detail.action || 'ESCALATED').toUpperCase() }}
              </div>
              <span v-if="detail.refund_amount" class="refund-amount-text">
                Refund Amount: ₹{{ detail.refund_amount.toFixed(2) }}
              </span>
            </div>
          </div>

          <!-- Plain Language Reasoning -->
          <div class="reasoning-box">
            <strong>Engine Reasoning:</strong>
            <p>{{ detail.reasoning }}</p>
          </div>
        </div>

        <!-- Evidence Section (Top-3 Similar Cases) -->
        <div class="detail-section">
          <div class="section-header-flex">
            <h4 class="section-title">
              <Layers :size="16" />
              Precedent Case Evidence (Top-3)
            </h4>
            <span class="evidence-status-pill" :class="detail.similar_cases_status === 'found' ? 'status-found' : 'status-none'">
              {{ detail.similar_cases_status === 'found' ? 'Precedents Found' : 'No Precedents' }}
            </span>
          </div>

          <div v-if="detail.similar_cases_status === 'found' && detail.similar_cases.length > 0" class="cases-list">
            <div v-for="caseItem in detail.similar_cases" :key="caseItem.ticket_id" class="case-card">
              <div class="case-header">
                <span class="case-id">Past Case #{{ caseItem.ticket_id }}</span>
                <span class="case-score">
                  {{ Math.round(caseItem.similarity_score * 100) }}% Cosine Match
                </span>
              </div>
              <p class="case-desc">{{ caseItem.description }}</p>
              <div class="case-footer">
                <span class="case-action">Action Taken: <strong>{{ caseItem.action_taken }}</strong></span>
                <span class="case-note" :title="caseItem.resolution_note">Note: {{ caseItem.resolution_note }}</span>
              </div>
            </div>
          </div>

          <div v-else class="no-cases-box">
            <FileQuestion :size="24" />
            <p>No similar past cases were found in the resolved ticket corpus.</p>
          </div>
        </div>

        <!-- Customer Reply Draft (F4) -->
        <div class="detail-section" v-if="detail.reply">
          <div class="section-header-flex">
            <h4 class="section-title">
              <Send :size="16" />
              Drafted Customer Reply (F4)
            </h4>
            <div class="reply-badges">
              <span class="reply-badge-variant">{{ detail.reply.variant }}</span>
              <span class="reply-badge-status">{{ detail.reply.status }}</span>
            </div>
          </div>
          <div class="reply-box">
            {{ detail.reply.final_body }}
          </div>
        </div>

        <!-- Human Override Controls Section (F6) -->
        <div class="detail-section override-section glass-panel">
          <h4 class="section-title">
            <UserCheck :size="16" />
            Human Override Controls (F6)
          </h4>

          <!-- Handled Status (if human has already acted) -->
          <div v-if="humanDecision" class="handled-card">
            <CheckCircle :size="20" class="icon-handled" />
            <div>
              <strong>Human Decision Recorded by {{ humanDecision.agent_id }}</strong>
              <p>
                Action: <span class="badge-action-text">{{ humanDecision.agent_action.toUpperCase() }}</span>
                <span v-if="humanDecision.final_action"> (Final Action: {{ humanDecision.final_action }})</span>
                <span v-if="humanDecision.rejection_reason"> - Reason: {{ humanDecision.rejection_reason }}</span>
              </p>
            </div>
          </div>

          <!-- Actionable Controls (when in Needs Review lane and not yet handled) -->
          <div v-else-if="detail.lane === 'needs_review'" class="override-controls-body">
            <!-- Inline Action Error Message (e.g. 422 Policy Blocked) -->
            <div v-if="actionError" class="action-error-box">
              <AlertCircle :size="16" />
              <span>{{ actionError }}</span>
            </div>

            <!-- Primary Buttons -->
            <div class="action-buttons-row" v-if="!activeForm">
              <button class="btn btn-success" @click="handleApprove" :disabled="submitting">
                <Check :size="16" />
                Approve System Suggestion
              </button>

              <button class="btn btn-warning" @click="activeForm = 'override'">
                <Edit3 :size="16" />
                Override Action &amp; Reply
              </button>

              <button class="btn btn-danger" @click="activeForm = 'reject'">
                <XCircle :size="16" />
                Reject Suggestion
              </button>
            </div>

            <!-- Override Form -->
            <div v-if="activeForm === 'override'" class="override-form">
              <h5>Override Resolution Action &amp; Reply</h5>

              <div class="form-group">
                <label>Select New Action:</label>
                <div class="radio-group">
                  <label class="radio-label">
                    <input type="radio" v-model="overrideAction" value="refund" />
                    Refund Order
                  </label>
                  <label class="radio-label">
                    <input type="radio" v-model="overrideAction" value="redelivery" />
                    Item Redelivery
                  </label>
                  <label class="radio-label">
                    <input type="radio" v-model="overrideAction" value="coupon" />
                    Issue Store Coupon
                  </label>
                </div>
              </div>

              <div class="form-group">
                <label>Edited Reply Body (Optional):</label>
                <textarea
                  v-model="overrideReplyBody"
                  rows="3"
                  class="form-textarea"
                  placeholder="Enter customized customer reply..."
                ></textarea>
              </div>

              <div class="form-actions">
                <button class="btn btn-primary" @click="handleOverrideSubmit" :disabled="submitting">
                  Submit Override
                </button>
                <button class="btn btn-secondary" @click="activeForm = null">Cancel</button>
              </div>
            </div>

            <!-- Reject Form -->
            <div v-if="activeForm === 'reject'" class="reject-form">
              <h5>Reject Suggested Action</h5>

              <div class="form-group">
                <label>Rejection Reason (Required):</label>
                <textarea
                  v-model="rejectReason"
                  rows="3"
                  class="form-textarea"
                  placeholder="Explain why the system recommendation is rejected..."
                ></textarea>
              </div>

              <div class="form-actions">
                <button class="btn btn-danger" @click="handleRejectSubmit" :disabled="submitting">
                  Submit Rejection
                </button>
                <button class="btn btn-secondary" @click="activeForm = null">Cancel</button>
              </div>
            </div>
          </div>

          <!-- Read-only note for Auto-resolved tickets without human decision -->
          <div v-else class="read-only-note">
            <CheckCircle :size="16" />
            <span>This ticket was auto-resolved by the system with high confidence.</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import {
  X, Loader2, AlertOctagon, MessageSquare, Cpu, Layers, FileQuestion,
  Send, UserCheck, CheckCircle, AlertCircle, Check, Edit3, XCircle
} from 'lucide-vue-next';
import { api } from '../services/api';

const props = defineProps({
  ticketId: { type: String, required: true },
});

const emit = defineEmits(['close', 'ticket-updated']);

const detail = ref(null);
const humanDecision = ref(null);
const loading = ref(true);
const error = ref(null);

const activeForm = ref(null); // 'override' | 'reject' | null
const overrideAction = ref('refund');
const overrideReplyBody = ref('');
const rejectReason = ref('');

const submitting = ref(false);
const actionError = ref(null);

const actionBadgeClass = computed(() => {
  if (!detail.value || !detail.value.action) return 'badge-action-reject';
  return `badge-action-${detail.value.action}`;
});

async function fetchDetail() {
  loading.value = true;
  error.value = null;
  actionError.value = null;

  try {
    const [detailRes, decisionRes] = await Promise.all([
      api.getTicketDetail(props.ticketId),
      api.getHumanDecision(props.ticketId),
    ]);

    detail.value = detailRes;
    humanDecision.value = decisionRes;

    // Pre-fill override reply body if reply exists
    if (detailRes && detailRes.reply) {
      overrideReplyBody.value = detailRes.reply.final_body;
    }
    if (detailRes && detailRes.action) {
      overrideAction.value = detailRes.action;
    }
  } catch (err) {
    error.value = err.message || 'Failed to load ticket details.';
  } finally {
    loading.value = false;
  }
}

function getActiveAgentId() {
  return localStorage.getItem('stm_agent_id') || 'agent-007';
}

async function handleApprove() {
  submitting.value = true;
  actionError.value = null;
  try {
    const agentId = getActiveAgentId();
    await api.approveHumanDecision(props.ticketId, agentId);
    emit('ticket-updated');
    await fetchDetail();
  } catch (err) {
    actionError.value = err.message;
  } finally {
    submitting.value = false;
  }
}

async function handleOverrideSubmit() {
  submitting.value = true;
  actionError.value = null;
  try {
    const agentId = getActiveAgentId();
    await api.overrideHumanDecision(props.ticketId, agentId, overrideAction.value, overrideReplyBody.value);
    activeForm.value = null;
    emit('ticket-updated');
    await fetchDetail();
  } catch (err) {
    actionError.value = err.message;
  } finally {
    submitting.value = false;
  }
}

async function handleRejectSubmit() {
  if (!rejectReason.value.trim()) {
    actionError.value = 'Rejection reason is required.';
    return;
  }
  submitting.value = true;
  actionError.value = null;
  try {
    const agentId = getActiveAgentId();
    await api.rejectHumanDecision(props.ticketId, agentId, rejectReason.value.trim());
    activeForm.value = null;
    emit('ticket-updated');
    await fetchDetail();
  } catch (err) {
    actionError.value = err.message;
  } finally {
    submitting.value = false;
  }
}

onMounted(() => {
  fetchDetail();
});
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(8px);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
  padding: 1.5rem;
}

.modal-panel {
  width: 900px;
  max-width: 100%;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  background: #0d1322;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
  overflow: hidden;
}

.modal-header {
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(255, 255, 255, 0.02);
}

.header-title-group {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.ticket-badge {
  font-family: 'Outfit', sans-serif;
  font-weight: 700;
  font-size: 1.1rem;
  color: white;
}

.order-badge {
  font-size: 0.8rem;
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.06);
  padding: 0.2rem 0.6rem;
  border-radius: var(--radius-sm);
}

.lane-badge {
  font-size: 0.75rem;
  font-weight: 700;
  padding: 0.2rem 0.6rem;
  border-radius: var(--radius-full);
}

.badge-auto-res {
  background: rgba(16, 185, 129, 0.18);
  color: #34d399;
}

.badge-needs-rev {
  background: rgba(245, 158, 11, 0.18);
  color: #fbbf24;
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 0.25rem;
  border-radius: 6px;
  transition: color var(--transition-fast);
}

.close-btn:hover {
  color: white;
}

.modal-loading, .modal-error {
  padding: 4rem 2rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  color: var(--text-secondary);
  text-align: center;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  100% { transform: rotate(360deg); }
}

.modal-body {
  padding: 1.5rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.detail-section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
  color: var(--text-secondary);
}

.description-box {
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  padding: 1rem;
  border-radius: var(--radius-sm);
  font-size: 0.95rem;
  line-height: 1.6;
  color: #f3f4f6;
}

.decision-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.decision-card {
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid var(--border-color);
  padding: 1rem;
  border-radius: var(--radius-sm);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.card-label {
  font-size: 0.75rem;
  color: var(--text-muted);
  text-transform: uppercase;
}

.confidence-meter-group {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.confidence-score-val {
  font-family: 'Outfit', sans-serif;
  font-weight: 800;
  font-size: 1.4rem;
}

.text-high { color: #34d399; }
.text-medium { color: #fbbf24; }
.text-low { color: #f87171; }

.meter-bar-bg {
  width: 100%;
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
}

.meter-bar-fill {
  height: 100%;
}

.fill-high { background: #10b981; }
.fill-medium { background: #f59e0b; }
.fill-low { background: #ef4444; }

.meter-bucket {
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--text-muted);
}

.action-value-tag {
  align-self: flex-start;
  font-weight: 700;
  font-size: 0.85rem;
  padding: 0.3rem 0.75rem;
  border-radius: var(--radius-sm);
}

.refund-amount-text {
  font-size: 0.8rem;
  color: #34d399;
  font-weight: 600;
}

.reasoning-box {
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(99, 102, 241, 0.2);
  padding: 0.85rem;
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
  color: #c7d2fe;
}

.section-header-flex {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.evidence-status-pill {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 0.2rem 0.5rem;
  border-radius: var(--radius-full);
}

.status-found {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
}

.status-none {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
}

.cases-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.case-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border-color);
  padding: 0.85rem;
  border-radius: var(--radius-sm);
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.case-header {
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
}

.case-id {
  font-weight: 700;
  color: white;
}

.case-score {
  color: #818cf8;
  font-weight: 600;
}

.case-desc {
  font-size: 0.85rem;
  color: var(--text-primary);
}

.case-footer {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: var(--text-secondary);
  border-top: 1px dashed var(--border-color);
  padding-top: 0.4rem;
  margin-top: 0.25rem;
}

.no-cases-box {
  background: rgba(0, 0, 0, 0.2);
  border: 1px dashed var(--border-color);
  padding: 1.5rem;
  border-radius: var(--radius-sm);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  color: var(--text-muted);
  text-align: center;
}

.reply-badges {
  display: flex;
  gap: 0.4rem;
}

.reply-badge-variant {
  font-size: 0.7rem;
  background: rgba(99, 102, 241, 0.2);
  color: #818cf8;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
}

.reply-badge-status {
  font-size: 0.7rem;
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
}

.reply-box {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid var(--border-color);
  padding: 1rem;
  border-radius: var(--radius-sm);
  font-size: 0.9rem;
  line-height: 1.5;
  color: #e2e8f0;
}

.override-section {
  padding: 1.25rem;
  background: rgba(17, 24, 39, 0.8);
}

.handled-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 1rem;
  border-radius: var(--radius-sm);
  color: #d1fae5;
}

.icon-handled {
  color: #34d399;
}

.badge-action-text {
  font-weight: 700;
  color: white;
}

.override-controls-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.action-error-box {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: #fca5a5;
  padding: 0.65rem;
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.action-buttons-row {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.override-form, .reject-form {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border-color);
  padding: 1rem;
  border-radius: var(--radius-sm);
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-group label {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.radio-group {
  display: flex;
  gap: 1.25rem;
}

.radio-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.875rem;
  cursor: pointer;
}

.form-textarea {
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  color: white;
  padding: 0.65rem;
  border-radius: var(--radius-sm);
  font-size: 0.875rem;
  outline: none;
  resize: vertical;
}

.form-actions {
  display: flex;
  gap: 0.5rem;
}

.read-only-note {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: var(--text-muted);
}
</style>
