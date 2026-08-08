<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal-panel glass-panel">
      <div class="modal-header">
        <h3>Manual Ticket Resolution Tester</h3>
        <button class="close-btn" @click="$emit('close')">
          <X :size="20" />
        </button>
      </div>

      <div class="modal-body">
        <p class="modal-desc">
          Enter a ticket ID (e.g. <code>N-001</code> to <code>N-010</code>) to manually run it through the F2 similarity matching, F3 resolution engine, and F4 reply drafting pipeline.
        </p>

        <div class="form-row">
          <input
            v-model="ticketIdInput"
            type="text"
            placeholder="e.g. N-001"
            class="input-ticket"
            @keyup.enter="handleResolve"
          />
          <button class="btn btn-primary" @click="handleResolve" :disabled="loading || !ticketIdInput.trim()">
            <Play :size="16" />
            Run Resolution
          </button>
        </div>

        <div v-if="loading" class="result-loading">
          <Loader2 :size="24" class="spin" />
          <span>Executing F2 Similarity Engine &amp; F3 Resolution Pipeline...</span>
        </div>

        <div v-if="error" class="result-error">
          <AlertCircle :size="18" />
          <span>{{ error }}</span>
        </div>

        <div v-if="decision" class="decision-result-box glass-panel">
          <div class="result-header">
            <h4>Resolution Outcome for #{{ decision.ticket_id }}</h4>
            <span class="outcome-pill" :class="decision.auto_resolved ? 'pill-auto' : 'pill-esc'">
              {{ decision.auto_resolved ? 'AUTO-RESOLVED' : 'ESCALATED TO HUMAN' }}
            </span>
          </div>

          <div class="result-grid">
            <div>
              <span class="lbl">Confidence Score:</span>
              <strong class="val">{{ Math.round(decision.confidence * 100) }}%</strong>
            </div>
            <div>
              <span class="lbl">Chosen Action:</span>
              <strong class="val">{{ (decision.action || 'NONE').toUpperCase() }}</strong>
            </div>
          </div>

          <div class="reasoning-text">
            <strong>Reasoning:</strong> {{ decision.reasoning }}
          </div>

          <div class="reply-text" v-if="decision.drafted_reply">
            <strong>Drafted Reply:</strong>
            <p>{{ decision.drafted_reply }}</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { X, Play, Loader2, AlertCircle } from 'lucide-vue-next';
import { api } from '../services/api';

const emit = defineEmits(['close', 'resolved']);

const ticketIdInput = ref('N-001');
const loading = ref(false);
const error = ref(null);
const decision = ref(null);

async function handleResolve() {
  if (!ticketIdInput.value.trim()) return;
  loading.value = true;
  error.value = null;
  decision.value = null;

  try {
    const res = await api.resolveTicket(ticketIdInput.value.trim());
    decision.value = res;
    emit('resolved');
  } catch (err) {
    error.value = err.message || 'Failed to resolve ticket.';
  } finally {
    loading.value = false;
  }
}
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
  width: 600px;
  max-width: 100%;
  background: #0d1322;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-header {
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
}

.modal-body {
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.modal-desc {
  font-size: 0.875rem;
  color: var(--text-secondary);
}

.form-row {
  display: flex;
  gap: 0.75rem;
}

.input-ticket {
  flex: 1;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  color: white;
  padding: 0.6rem 0.85rem;
  border-radius: var(--radius-sm);
  font-size: 0.9rem;
  outline: none;
}

.result-loading, .result-error {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  border-radius: var(--radius-sm);
  font-size: 0.875rem;
}

.result-loading {
  background: rgba(99, 102, 241, 0.1);
  color: #a5b4fc;
}

.result-error {
  background: rgba(239, 68, 68, 0.15);
  color: #fca5a5;
}

.decision-result-box {
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  background: rgba(255, 255, 255, 0.03);
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.outcome-pill {
  font-size: 0.75rem;
  font-weight: 700;
  padding: 0.25rem 0.6rem;
  border-radius: var(--radius-full);
}

.pill-auto {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
}

.pill-esc {
  background: rgba(245, 158, 11, 0.2);
  color: #fbbf24;
}

.result-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  font-size: 0.875rem;
}

.lbl {
  color: var(--text-secondary);
  display: block;
}

.val {
  font-size: 1.1rem;
  color: white;
}

.reasoning-text {
  font-size: 0.85rem;
  color: #cbd5e1;
  background: rgba(0, 0, 0, 0.2);
  padding: 0.75rem;
  border-radius: var(--radius-sm);
}

.reply-text {
  font-size: 0.85rem;
  color: #e2e8f0;
  background: rgba(15, 23, 42, 0.6);
  padding: 0.75rem;
  border-radius: var(--radius-sm);
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  100% { transform: rotate(360deg); }
}
</style>
