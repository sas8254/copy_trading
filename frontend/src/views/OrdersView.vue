<script setup>
import { onMounted, ref } from 'vue'
import { errorMessage, fetchOrders } from '@/api/copytrading'
import { debounce, useLiveEvents } from '@/composables/useLiveEvents'
import { MASTER_STATUS, STYLES, copyState, fmtMoney, fmtTime } from '@/utils/format'

const trades = ref(null)
const error = ref('')

async function load() {
  try {
    trades.value = await fetchOrders(200)
    error.value = ''
  } catch (e) {
    error.value = errorMessage(e, 'Failed to load orders.')
  }
}

const refresh = debounce(load)
useLiveEvents((msg) => {
  if (['copy_order', 'master_order', 'ticker_order'].includes(msg.type)) refresh()
})

// Limit price for open orders, average fill price once filled.
const shownPrice = (t) => (t.filled_quantity ? t.average_price : t.price) ?? t.price

onMounted(load)
</script>

<template>
  <div>
    <div class="d-flex align-center mb-4">
      <h1 class="page-title">Orders</h1>
      <v-spacer />
      <v-btn icon="mdi-refresh" variant="text" title="Refresh" @click="load" />
    </div>

    <v-alert v-if="error" type="error" class="mb-4">{{ error }}</v-alert>
    <v-progress-linear v-if="!trades && !error" indeterminate />

    <v-alert v-if="trades && !trades.length" type="info" variant="tonal">
      No master orders yet. Master orders appear here with what happened on each copy account.
    </v-alert>

    <v-card v-if="trades && trades.length">
      <div class="table-scroll">
        <v-table density="compact">
          <thead>
            <tr>
              <th>Time</th><th>Master order</th><th class="num">Filled</th><th class="num">Price</th>
              <th>Status</th><th>Copies</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in trades" :key="t.id">
              <td class="text-no-wrap">{{ fmtTime(t.observed_at) }}</td>
              <td class="text-no-wrap">
                <span :class="t.side === 'BUY' ? 'text-success' : 'text-error'">{{ t.side }}</span>
                {{ t.tradingsymbol }}
                <div class="text-medium-emphasis text-caption">
                  {{ t.order_type }} {{ t.product }} · {{ t.exchange }}
                  <span v-if="t.trigger_price"> · trigger {{ fmtMoney(t.trigger_price) }}</span>
                  · {{ STYLES[t.copy_style]?.label }}
                </div>
              </td>
              <td class="num text-no-wrap">{{ t.filled_quantity }}/{{ t.quantity }}</td>
              <td class="num">{{ fmtMoney(shownPrice(t)) }}</td>
              <td>
                <v-chip size="small" label :color="MASTER_STATUS[t.status]?.color">
                  {{ MASTER_STATUS[t.status]?.label || t.status }}
                </v-chip>
              </td>
              <td>
                <span v-if="!t.copies.length" class="text-medium-emphasis">
                  {{ t.finalized ? 'Not copied' : 'Waiting…' }}
                </span>
                <div v-for="c in t.copies" :key="c.id" class="d-flex align-center flex-wrap ga-2 my-1">
                  <v-chip size="small" label :color="copyState(c).color">{{ copyState(c).label }}</v-chip>
                  <span class="text-no-wrap">{{ c.account }} · {{ c.computed_quantity }}</span>
                  <span v-if="c.modifications" class="text-medium-emphasis text-caption">
                    modified {{ c.modifications }}×
                  </span>
                  <span v-if="c.error_message" class="text-error text-caption">{{ c.error_message }}</span>
                </div>
              </td>
            </tr>
          </tbody>
        </v-table>
      </div>
    </v-card>
  </div>
</template>
