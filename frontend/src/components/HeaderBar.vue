<template>
  <header class="header-bar glass-panel">
    <div class="header-main">
      <div class="brand-section">
        <div class="brand-logo">
          <Zap class="icon-brand" />
        </div>
        <div>
          <h1 class="brand-title">Zepto Support Intelligence</h1>
          <p class="brand-subtitle">Autonomous Resolution Engine & Live Decision Dashboard</p>
        </div>
      </div>

      <!-- Quick System Stats -->
      <div class="stats-row" v-if="stats">
        <div class="stat-pill">
          <span class="stat-label">Total Processed</span>
          <span class="stat-value">{{ stats.total }}</span>
        </div>
        <div class="stat-pill">
          <span class="stat-label">Auto-Resolved Rate</span>
          <span class="stat-value text-emerald">
            {{ stats.autoRate }}%
          </span>
        </div>
        <div class="stat-pill">
          <span class="stat-label">System Status</span>
          <span class="status-indicator" :class="{ 'status-ok': health === 'ok' }">
            <span class="dot"></span>
            {{ health === 'ok' ? 'Online' : 'Connecting...' }}
          </span>
        </div>
      </div>
    </div>

    <!-- Action Bar & Agent Sign-in -->
    <div class="header-actions">
      <!-- Nav Tabs -->
      <div class="nav-tabs">
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'board' }"
          @click="$emit('update:activeTab', 'board')"
        >
          <LayoutGrid :size="16" />
          Two-Lane Board
        </button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'audit' }"
          @click="$emit('update:activeTab', 'audit')"
        >
          <History :size="16" />
          Human Audit Log
        </button>
      </div>

      <div class="controls-group">
        <!-- Agent Identity Input -->
        <div class="agent-signin">
          <User :size="15" class="icon-agent" />
          <input
            v-model="localAgentId"
            @blur="saveAgent"
            @keyup.enter="saveAgent"
            type="text"
            placeholder="Agent ID..."
            class="agent-input"
            title="Active Human Agent ID for Override Auditing"
          />
        </div>

        <!-- Manual Resolve Button -->
        <button class="btn btn-secondary" @click="$emit('open-manual-resolve')">
          <Play :size="15" />
          Resolve Ticket
        </button>

        <!-- Re-Seed DB Button -->
        <button class="btn btn-secondary" @click="handleSeed" :disabled="seeding">
          <RefreshCw :size="15" :class="{ 'spin': seeding }" />
          {{ seeding ? 'Seeding...' : 'Seed DB' }}
        </button>
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { Zap, LayoutGrid, History, User, Play, RefreshCw } from 'lucide-vue-next';
import { api } from '../services/api';

const props = defineProps({
  activeTab: { type: String, default: 'board' },
  stats: { type: Object, default: () => ({ total: 0, autoRate: 0 }) },
});

const emit = defineEmits(['update:activeTab', 'open-manual-resolve', 'seeded']);

const localAgentId = ref('agent-007');
const seeding = ref(false);
const health = ref('connecting');

function saveAgent() {
  const trimmed = localAgentId.value.trim() || 'agent-007';
  localAgentId.value = trimmed;
  localStorage.setItem('stm_agent_id', trimmed);
}

async function handleSeed() {
  seeding.value = true;
  try {
    const res = await api.seedData();
    emit('seeded', res);
  } catch (err) {
    alert(`Failed to seed data: ${err.message}`);
  } finally {
    seeding.value = false;
  }
}

async function checkHealth() {
  try {
    const res = await api.getHealth();
    if (res.status === 'ok') {
      health.value = 'ok';
    }
  } catch (_) {
    health.value = 'error';
  }
}

onMounted(() => {
  const saved = localStorage.getItem('stm_agent_id');
  if (saved) localAgentId.value = saved;
  else localStorage.setItem('stm_agent_id', localAgentId.value);
  checkHealth();
});
</script>

<style scoped>
.header-bar {
  padding: 1.25rem 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.header-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}

.brand-section {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.brand-logo {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--brand-gradient);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 16px var(--brand-glow);
}

.icon-brand {
  color: white;
  width: 24px;
  height: 24px;
}

.brand-title {
  font-size: 1.35rem;
  letter-spacing: -0.02em;
  background: linear-gradient(180deg, #ffffff 0%, #cbd5e1 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.brand-subtitle {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.stats-row {
  display: flex;
  gap: 1rem;
  align-items: center;
}

.stat-pill {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--border-color);
  padding: 0.4rem 0.8rem;
  border-radius: var(--radius-sm);
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.stat-label {
  font-size: 0.68rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.stat-value {
  font-family: 'Outfit', sans-serif;
  font-weight: 700;
  font-size: 1rem;
  color: white;
}

.text-emerald {
  color: #34d399;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  font-weight: 600;
  color: #f87171;
}

.status-indicator.status-ok {
  color: #34d399;
}

.status-indicator .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 8px currentColor;
}

.header-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid var(--border-color);
  padding-top: 0.85rem;
  flex-wrap: wrap;
  gap: 1rem;
}

.nav-tabs {
  display: flex;
  gap: 0.5rem;
  background: rgba(0, 0, 0, 0.3);
  padding: 0.25rem;
  border-radius: var(--radius-sm);
}

.tab-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  padding: 0.4rem 0.85rem;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  transition: all var(--transition-fast);
}

.tab-btn:hover {
  color: white;
}

.tab-btn.active {
  background: rgba(255, 255, 255, 0.12);
  color: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

.controls-group {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.agent-signin {
  display: flex;
  align-items: center;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 0.3rem 0.6rem;
  gap: 0.4rem;
}

.icon-agent {
  color: var(--brand-primary);
}

.agent-input {
  background: transparent;
  border: none;
  color: white;
  font-size: 0.85rem;
  width: 100px;
  outline: none;
  font-weight: 500;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  100% { transform: rotate(360deg); }
}
</style>
