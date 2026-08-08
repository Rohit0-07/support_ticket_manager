<template>
  <div
    class="ticket-card"
    :class="[confidenceClass, { 'animate-landing': recentlyLanded }]"
    @click="$emit('select-ticket', card.ticket_id)"
  >
    <!-- Card Header: Ticket ID & Time -->
    <div class="card-header">
      <span class="ticket-id">#{{ card.ticket_id }}</span>
      <span class="card-time">{{ formattedTime }}</span>
    </div>

    <!-- Description Preview -->
    <p class="card-desc" :title="card.description_preview">
      {{ card.description_preview }}
    </p>

    <!-- Card Footer: Action Tag & Confidence Badge -->
    <div class="card-footer">
      <div class="action-tag" :class="actionBadgeClass">
        {{ actionDisplay }}
      </div>

      <div class="confidence-badge" :class="confidenceClass">
        <span class="conf-dot"></span>
        <span>{{ Math.round(card.confidence * 100) }}% Match</span>
      </div>
    </div>

    <!-- Escalation Reason Badge (if escalated) -->
    <div v-if="card.escalation_reason" class="escalation-reason-tag">
      <AlertTriangle :size="12" />
      <span>{{ formatEscalationReason(card.escalation_reason) }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { AlertTriangle } from 'lucide-vue-next';

const props = defineProps({
  card: { type: Object, required: true },
  recentlyLanded: { type: Boolean, default: false },
});

defineEmits(['select-ticket']);

const confidenceClass = computed(() => {
  return `confidence-${props.card.confidence_level || 'medium'}`;
});

const actionDisplay = computed(() => {
  if (props.card.action) {
    return props.card.action.toUpperCase();
  }
  return 'NEEDS HUMAN REVIEW';
});

const actionBadgeClass = computed(() => {
  if (!props.card.action) return 'badge-action-reject';
  return `badge-action-${props.card.action}`;
});

const formattedTime = computed(() => {
  if (!props.card.created_at) return '';
  try {
    const d = new Date(props.card.created_at);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch (_) {
    return props.card.created_at;
  }
});

function formatEscalationReason(reason) {
  switch (reason) {
    case 'low_confidence': return 'Low Confidence';
    case 'disagreeing_precedents': return 'Precedent Disagreement';
    case 'context_constraint': return 'Order Constraint';
    default: return reason.replace(/_/g, ' ');
  }
}
</script>

<style scoped>
.ticket-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  cursor: pointer;
  transition: all var(--transition-fast);
  position: relative;
  overflow: hidden;
}

.ticket-card:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-light);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.4);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.ticket-id {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  font-size: 0.85rem;
  color: white;
}

.card-time {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.card-desc {
  font-size: 0.875rem;
  color: var(--text-primary);
  line-height: 1.4;

  /* Ellipsis truncation fallback */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 0.25rem;
}

.action-tag {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 0.2rem 0.5rem;
  border-radius: var(--radius-sm);
  letter-spacing: 0.04em;
}

.confidence-badge {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.2rem 0.5rem;
  border-radius: var(--radius-full);
}

.conf-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.escalation-reason-tag {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.7rem;
  color: #fbbf24;
  background: rgba(245, 158, 11, 0.1);
  padding: 0.2rem 0.5rem;
  border-radius: var(--radius-sm);
  border: 1px dashed rgba(245, 158, 11, 0.3);
}
</style>
