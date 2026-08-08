<template>
  <div class="two-lane-container">
    <!-- Filter & Search Bar -->
    <div class="filter-bar glass-panel">
      <div class="search-input-group">
        <Search :size="16" class="icon-search" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Filter tickets by ID, keyword, or action..."
          class="search-input"
        />
        <button v-if="searchQuery" class="clear-btn" @click="searchQuery = ''">
          <X :size="14" />
        </button>
      </div>

      <div class="filter-badges">
        <button
          class="filter-chip"
          :class="{ active: actionFilter === 'all' }"
          @click="actionFilter = 'all'"
        >
          All
        </button>
        <button
          class="filter-chip"
          :class="{ active: actionFilter === 'refund' }"
          @click="actionFilter = 'refund'"
        >
          Refunds
        </button>
        <button
          class="filter-chip"
          :class="{ active: actionFilter === 'redelivery' }"
          @click="actionFilter = 'redelivery'"
        >
          Redeliveries
        </button>
        <button
          class="filter-chip"
          :class="{ active: actionFilter === 'coupon' }"
          @click="actionFilter = 'coupon'"
        >
          Coupons
        </button>
      </div>
    </div>

    <!-- Error Banner when board fails to load -->
    <div class="glass-panel error-panel" v-if="error">
      <AlertOctagon :size="24" class="icon-error" />
      <div>
        <h4>Couldn't Load Dashboard Board</h4>
        <p>{{ error }}</p>
      </div>
      <button class="btn btn-secondary" @click="$emit('retry')">Retry</button>
    </div>

    <!-- Two Lanes Grid -->
    <div class="two-lane-grid" v-else>
      <!-- Auto-Resolved Lane -->
      <div class="lane-column glass-panel lane-auto">
        <div class="lane-header">
          <div class="lane-title">
            <CheckCircle2 :size="20" class="icon-lane-auto" />
            <h2>Auto-Resolved</h2>
          </div>
          <span class="lane-count-badge badge-auto-count">
            {{ filteredAutoTickets.length }}
          </span>
        </div>

        <div class="lane-tickets-list">
          <TicketCard
            v-for="card in filteredAutoTickets"
            :key="card.ticket_id"
            :card="card"
            :recently-landed="recentlyLandedIds.includes(card.ticket_id)"
            @select-ticket="$emit('select-ticket', $event)"
          />

          <!-- Empty State -->
          <div v-if="filteredAutoTickets.length === 0" class="empty-lane">
            <Inbox :size="32" class="empty-icon" />
            <p>No auto-resolved tickets yet.</p>
          </div>
        </div>
      </div>

      <!-- Needs Human Review Lane -->
      <div class="lane-column glass-panel lane-review">
        <div class="lane-header">
          <div class="lane-title">
            <UserCheck :size="20" class="icon-lane-review" />
            <h2>Needs Human Review</h2>
          </div>
          <span class="lane-count-badge badge-review-count">
            {{ filteredReviewTickets.length }}
          </span>
        </div>

        <div class="lane-tickets-list">
          <TicketCard
            v-for="card in filteredReviewTickets"
            :key="card.ticket_id"
            :card="card"
            :recently-landed="recentlyLandedIds.includes(card.ticket_id)"
            @select-ticket="$emit('select-ticket', $event)"
          />

          <!-- Empty State -->
          <div v-if="filteredReviewTickets.length === 0" class="empty-lane">
            <CheckCheck :size="32" class="empty-icon" />
            <p>All clear! No tickets awaiting human review.</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue';
import { Search, X, CheckCircle2, UserCheck, Inbox, CheckCheck, AlertOctagon } from 'lucide-vue-next';
import TicketCard from './TicketCard.vue';

const props = defineProps({
  board: { type: Object, default: null },
  recentlyLandedIds: { type: Array, default: () => [] },
  error: { type: String, default: null },
});

defineEmits(['select-ticket', 'retry']);

const searchQuery = ref('');
const actionFilter = ref('all');

function filterTickets(tickets = []) {
  return tickets.filter(t => {
    // Search query filter
    const query = searchQuery.value.trim().toLowerCase();
    if (query) {
      const matchId = t.ticket_id.toLowerCase().includes(query);
      const matchDesc = t.description_preview.toLowerCase().includes(query);
      const matchAction = (t.action || '').toLowerCase().includes(query);
      if (!matchId && !matchDesc && !matchAction) return false;
    }

    // Action type filter
    if (actionFilter.value !== 'all') {
      if ((t.action || '').toLowerCase() !== actionFilter.value) return false;
    }

    return true;
  });
}

const filteredAutoTickets = computed(() => {
  if (!props.board || !props.board.auto_resolved) return [];
  return filterTickets(props.board.auto_resolved.tickets);
});

const filteredReviewTickets = computed(() => {
  if (!props.board || !props.board.needs_review) return [];
  return filterTickets(props.board.needs_review.tickets);
});
</script>

<style scoped>
.two-lane-container {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  flex: 1;
}

.filter-bar {
  padding: 0.75rem 1.25rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}

.search-input-group {
  display: flex;
  align-items: center;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 0.4rem 0.75rem;
  width: 340px;
  max-width: 100%;
  gap: 0.5rem;
}

.icon-search {
  color: var(--text-muted);
}

.search-input {
  background: transparent;
  border: none;
  color: white;
  font-size: 0.875rem;
  width: 100%;
  outline: none;
}

.clear-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
}

.filter-badges {
  display: flex;
  gap: 0.5rem;
}

.filter-chip {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  padding: 0.3rem 0.75rem;
  border-radius: var(--radius-full);
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.filter-chip:hover {
  color: white;
  border-color: var(--border-light);
}

.filter-chip.active {
  background: var(--brand-primary);
  color: white;
  border-color: var(--brand-primary);
  box-shadow: 0 2px 8px var(--brand-glow);
}

.lane-column {
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-height: 500px;
}

.lane-auto {
  border-top: 3px solid #10b981;
}

.lane-review {
  border-top: 3px solid #f59e0b;
}

.lane-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 0.75rem;
}

.lane-title {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.lane-title h2 {
  font-size: 1.15rem;
}

.icon-lane-auto {
  color: #34d399;
}

.icon-lane-review {
  color: #fbbf24;
}

.lane-count-badge {
  font-family: 'Outfit', sans-serif;
  font-weight: 700;
  font-size: 0.9rem;
  padding: 0.2rem 0.65rem;
  border-radius: var(--radius-full);
}

.badge-auto-count {
  background: rgba(16, 185, 129, 0.18);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.badge-review-count {
  background: rgba(245, 158, 11, 0.18);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.lane-tickets-list {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  overflow-y: auto;
  max-height: 70vh;
  padding-right: 0.25rem;
}

.empty-lane {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 1rem;
  color: var(--text-muted);
  gap: 0.75rem;
  text-align: center;
}

.empty-icon {
  opacity: 0.4;
}

.error-panel {
  padding: 2rem;
  display: flex;
  align-items: center;
  gap: 1rem;
  border-color: rgba(239, 68, 68, 0.4);
}

.icon-error {
  color: #f87171;
}
</style>
