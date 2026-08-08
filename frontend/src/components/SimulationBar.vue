<template>
  <div class="simulation-bar glass-panel" :class="{ 'is-running': status?.running }">
    <div class="sim-header">
      <div class="sim-title-group">
        <Activity class="icon-sim" :class="{ 'pulse-icon': status?.running }" />
        <div>
          <h3 class="sim-title">Live Ticket Stream Simulation (F7)</h3>
          <p class="sim-desc">Feeds new tickets real-time into resolution engine and animates landing</p>
        </div>
      </div>

      <!-- Live Status Pill -->
      <div class="sim-status-badge" :class="stateClass">
        <span class="status-dot"></span>
        <span class="status-label">{{ stateLabel }}</span>
      </div>
    </div>

    <!-- Session Mismatch Warning (EC-04) -->
    <div class="sim-alert alert-warning" v-if="sessionMismatch">
      <AlertTriangle :size="18" />
      <div class="alert-text">
        <strong>Session Mismatch:</strong> Another live simulation is running on the server.
      </div>
      <button class="btn btn-warning btn-sm" @click="handleForceStart">
        Stop Previous &amp; Start New
      </button>
    </div>

    <!-- Error Banner (EC-03) -->
    <div class="sim-alert alert-error" v-if="status?.error">
      <AlertOctagon :size="18" />
      <div class="alert-text">
        <strong>Pipeline Error:</strong> {{ status.error.message }}
      </div>
      <div class="alert-actions">
        <button class="btn btn-primary btn-sm" v-if="status.error.retryable" @click="handleResume">
          Resume
        </button>
        <button class="btn btn-secondary btn-sm" @click="handleStop">
          Stop
        </button>
      </div>
    </div>

    <!-- Controls Row & Progress Bar -->
    <div class="sim-body">
      <div class="controls-row">
        <!-- Pace Selector -->
        <div class="pace-selector">
          <label class="input-label">Pace (sec/ticket):</label>
          <select v-model.number="selectedPace" :disabled="status?.running" class="sim-select">
            <option :value="1.0">1.0s (Fast)</option>
            <option :value="2.0">2.0s (Standard)</option>
            <option :value="3.0">3.0s (Demo)</option>
            <option :value="5.0">5.0s (Slow)</option>
          </select>
        </div>

        <!-- Action Buttons -->
        <div class="sim-buttons">
          <!-- Start Button -->
          <button
            v-if="status?.state === 'idle' || status?.state === 'completed'"
            class="btn btn-primary"
            @click="handleStart"
            :disabled="loading"
          >
            <Play :size="16" />
            Start Simulation
          </button>

          <!-- Pause Button -->
          <button
            v-if="status?.state === 'running'"
            class="btn btn-warning"
            @click="handlePause"
            :disabled="loading"
          >
            <Pause :size="16" />
            Pause
          </button>

          <!-- Resume Button -->
          <button
            v-if="status?.state === 'paused' && !status?.error"
            class="btn btn-success"
            @click="handleResume"
            :disabled="loading"
          >
            <Play :size="16" />
            Resume
          </button>

          <!-- Stop Button -->
          <button
            v-if="status?.state === 'running' || status?.state === 'paused'"
            class="btn btn-secondary"
            @click="handleStop"
            :disabled="loading"
          >
            <Square :size="16" />
            Stop
          </button>
        </div>
      </div>

      <!-- Progress Section -->
      <div class="progress-section" v-if="status && status.queue_total > 0">
        <div class="progress-info">
          <span class="progress-text">
            Processed <strong>{{ status.processed_count }}</strong> of <strong>{{ status.queue_total }}</strong> tickets
          </span>
          <span class="progress-percent">{{ progressPercent }}%</span>
        </div>

        <!-- Visual Progress Bar -->
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" :style="{ width: progressPercent + '%' }"></div>
        </div>

        <!-- Breakdown counters -->
        <div class="progress-counters">
          <span class="counter-badge badge-auto">
            Auto-Resolved: <strong>{{ status.auto_resolved_count }}</strong>
          </span>
          <span class="counter-badge badge-review">
            Needs Review: <strong>{{ status.needs_review_count }}</strong>
          </span>
          <span class="counter-badge badge-skip" v-if="status.skipped_count > 0">
            Skipped: <strong>{{ status.skipped_count }}</strong>
          </span>
        </div>
      </div>

      <!-- Warnings Area (EC-02) -->
      <div class="sim-warnings" v-if="status?.warnings && status.warnings.length > 0">
        <div v-for="(warn, idx) in status.warnings" :key="idx" class="warning-item">
          <AlertCircle :size="14" />
          <span>{{ warn.ticket_id }}: {{ warn.message }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue';
import { Activity, Play, Pause, Square, AlertTriangle, AlertOctagon, AlertCircle } from 'lucide-vue-next';
import { api } from '../services/api';

const props = defineProps({
  status: { type: Object, default: null },
  sessionMismatch: { type: Boolean, default: false },
});

const emit = defineEmits(['status-changed', 'refresh-board']);

const selectedPace = ref(2.0);
const loading = ref(false);

const stateLabel = computed(() => {
  if (!props.status) return 'IDLE';
  if (props.status.queue_empty) return 'QUEUE EMPTY';
  return props.status.state.toUpperCase();
});

const stateClass = computed(() => {
  if (!props.status) return 'state-idle';
  if (props.status.queue_empty) return 'state-empty';
  switch (props.status.state) {
    case 'running': return 'state-running';
    case 'paused': return 'state-paused';
    case 'completed': return 'state-completed';
    default: return 'state-idle';
  }
});

const progressPercent = computed(() => {
  if (!props.status || props.status.queue_total === 0) return 0;
  return Math.round((props.status.processed_count / props.status.queue_total) * 100);
});

async function handleStart() {
  loading.value = true;
  try {
    const res = await api.startSimulation(selectedPace.value);
    emit('status-changed', res);
    emit('refresh-board');
  } catch (err) {
    alert(`Failed to start simulation: ${err.message}`);
  } finally {
    loading.value = false;
  }
}

async function handlePause() {
  loading.value = true;
  try {
    const res = await api.pauseSimulation();
    emit('status-changed', res);
  } catch (err) {
    alert(`Failed to pause simulation: ${err.message}`);
  } finally {
    loading.value = false;
  }
}

async function handleResume() {
  loading.value = true;
  try {
    const res = await api.resumeSimulation();
    emit('status-changed', res);
  } catch (err) {
    alert(`Failed to resume simulation: ${err.message}`);
  } finally {
    loading.value = false;
  }
}

async function handleStop() {
  loading.value = true;
  try {
    const res = await api.stopSimulation();
    emit('status-changed', res);
    emit('refresh-board');
  } catch (err) {
    alert(`Failed to stop simulation: ${err.message}`);
  } finally {
    loading.value = false;
  }
}

async function handleForceStart() {
  try {
    await api.stopSimulation();
  } catch (_) {}
  await handleStart();
}
</script>

<style scoped>
.simulation-bar {
  padding: 1.25rem 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  border-left: 4px solid var(--brand-primary);
  transition: all var(--transition-normal);
}

.simulation-bar.is-running {
  border-left-color: #10b981;
  box-shadow: 0 0 25px rgba(16, 185, 129, 0.15);
}

.sim-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}

.sim-title-group {
  display: flex;
  align-items: center;
  gap: 0.85rem;
}

.icon-sim {
  color: var(--brand-primary);
  width: 24px;
  height: 24px;
}

.pulse-icon {
  animation: pulse 1.5s infinite;
  color: #10b981;
}

@keyframes pulse {
  0% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.15); opacity: 0.7; }
  100% { transform: scale(1); opacity: 1; }
}

.sim-title {
  font-size: 1.1rem;
}

.sim-desc {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.sim-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0.8rem;
  border-radius: var(--radius-full);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.05em;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.state-idle {
  background: rgba(156, 163, 175, 0.15);
  color: var(--text-secondary);
  border: 1px solid rgba(156, 163, 175, 0.3);
}

.state-running {
  background: rgba(16, 185, 129, 0.18);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.4);
}

.state-paused {
  background: rgba(245, 158, 11, 0.18);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.4);
}

.state-completed {
  background: rgba(99, 102, 241, 0.18);
  color: #818cf8;
  border: 1px solid rgba(99, 102, 241, 0.4);
}

.state-empty {
  background: rgba(107, 114, 128, 0.18);
  color: #9ca3af;
  border: 1px solid rgba(107, 114, 128, 0.4);
}

.sim-alert {
  padding: 0.75rem 1rem;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.85rem;
}

.alert-warning {
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: #fef3c7;
}

.alert-error {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: #fee2e2;
}

.alert-text {
  flex: 1;
}

.alert-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-sm {
  padding: 0.25rem 0.6rem;
  font-size: 0.75rem;
}

.sim-body {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.controls-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}

.pace-selector {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.input-label {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.sim-select {
  background: var(--bg-input);
  color: white;
  border: 1px solid var(--border-color);
  padding: 0.4rem 0.75rem;
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
  outline: none;
  cursor: pointer;
}

.sim-buttons {
  display: flex;
  gap: 0.5rem;
}

.progress-section {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  background: rgba(0, 0, 0, 0.25);
  padding: 0.75rem 1rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-color);
}

.progress-info {
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
}

.progress-text {
  color: var(--text-secondary);
}

.progress-percent {
  font-weight: 700;
  color: white;
}

.progress-bar-bg {
  width: 100%;
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: var(--brand-gradient);
  transition: width 0.3s ease;
}

.progress-counters {
  display: flex;
  gap: 0.75rem;
  margin-top: 0.25rem;
}

.counter-badge {
  font-size: 0.75rem;
  padding: 0.15rem 0.5rem;
  border-radius: var(--radius-sm);
}

.badge-auto {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
}

.badge-review {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
}

.badge-skip {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
}

.sim-warnings {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: #fbbf24;
}

.warning-item {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
</style>
