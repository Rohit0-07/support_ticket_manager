<template>
  <div class="app-container">
    <!-- Header Bar -->
    <HeaderBar
      v-model:activeTab="activeTab"
      :stats="stats"
      @open-manual-resolve="showManualResolve = true"
      @seeded="handleDataSeeded"
    />

    <!-- Live Simulation Control Bar (F7) -->
    <SimulationBar
      :status="simStatus"
      :session-mismatch="sessionMismatch"
      @status-changed="handleSimStatusChange"
      @refresh-board="fetchBoard"
    />

    <!-- Main View Switcher -->
    <main class="main-content">
      <!-- Two-Lane Dashboard Board (F5) -->
      <TwoLaneBoard
        v-if="activeTab === 'board'"
        :board="board"
        :recently-landed-ids="recentlyLandedIds"
        :error="boardError"
        @select-ticket="openTicketDetail"
        @retry="fetchBoard"
      />

      <!-- Human Decision Audit Log (F6) -->
      <HumanAuditLog v-else-if="activeTab === 'audit'" />
    </main>

    <!-- Ticket Detail Modal (F5 & F6) -->
    <TicketDetailModal
      v-if="selectedTicketId"
      :ticket-id="selectedTicketId"
      @close="selectedTicketId = null"
      @ticket-updated="handleTicketUpdated"
    />

    <!-- Manual Ticket Resolve Modal -->
    <ManualResolveModal
      v-if="showManualResolve"
      @close="showManualResolve = false"
      @resolved="handleManualResolved"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue';
import HeaderBar from './components/HeaderBar.vue';
import SimulationBar from './components/SimulationBar.vue';
import TwoLaneBoard from './components/TwoLaneBoard.vue';
import HumanAuditLog from './components/HumanAuditLog.vue';
import TicketDetailModal from './components/TicketDetailModal.vue';
import ManualResolveModal from './components/ManualResolveModal.vue';
import { api } from './services/api';

const activeTab = ref('board');
const board = ref(null);
const boardError = ref(null);

const simStatus = ref(null);
const knownSessionId = ref(null);
const sessionMismatch = ref(false);
const recentlyLandedIds = ref([]);

const selectedTicketId = ref(null);
const showManualResolve = ref(false);

let pollTimer = null;

const stats = computed(() => {
  if (!board.value) return { total: 0, autoRate: 0 };
  const autoCount = board.value.auto_resolved?.count || 0;
  const reviewCount = board.value.needs_review?.count || 0;
  const total = autoCount + reviewCount;
  const autoRate = total > 0 ? Math.round((autoCount / total) * 100) : 0;
  return { total, autoRate };
});

async function fetchBoard() {
  try {
    const res = await api.getDashboard();
    board.value = res;
    boardError.value = null;
  } catch (err) {
    boardError.value = err.message || 'Unable to connect to dashboard API.';
  }
}

async function pollSimulation() {
  try {
    const status = await api.getSimulationStatus();
    simStatus.value = status;

    // Check EC-04 Session Mismatch
    if (status.running || status.paused) {
      if (knownSessionId.value && status.session_id && knownSessionId.value !== status.session_id) {
        sessionMismatch.value = true;
      }
    } else {
      sessionMismatch.value = false;
    }

    // Check for recently landed tickets to refresh board
    if (status.recently_landed_ticket_ids && status.recently_landed_ticket_ids.length > 0) {
      recentlyLandedIds.value = status.recently_landed_ticket_ids;
      await fetchBoard();
    }
  } catch (_) {
    // Ignore transient poll error
  }
}

function handleSimStatusChange(newStatus) {
  simStatus.value = newStatus;
  if (newStatus && newStatus.session_id) {
    knownSessionId.value = newStatus.session_id;
    sessionMismatch.value = false;
  }
}

function openTicketDetail(ticketId) {
  selectedTicketId.value = ticketId;
}

async function handleTicketUpdated() {
  await fetchBoard();
}

async function handleManualResolved() {
  await fetchBoard();
}

async function handleDataSeeded() {
  await fetchBoard();
  await pollSimulation();
}

onMounted(() => {
  fetchBoard();
  pollSimulation();
  pollTimer = setInterval(pollSimulation, 1000);
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});
</script>

<style scoped>
.main-content {
  display: flex;
  flex-direction: column;
  flex: 1;
}
</style>
