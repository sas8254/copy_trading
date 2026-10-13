<script setup>
import { computed, onMounted, ref } from 'vue'
import { errorMessage, fetchOverview, resolveAlert, resolveAllAlerts } from '@/api/copytrading'
import { debounce, useLiveEvents } from '@/composables/useLiveEvents'
import { MASTER_STATUS, MODES, copyState, fmtTime } from '@/utils/format'

const data = ref(null)
const error = ref('')

const mode = computed(() => MODES[data.value?.mode] || MODES.off)
const allOk = computed(() => data.value?.checks.every((c) => c.ok))
const needsLogin = computed(() => data.value?.accounts.some((a) => a.active && !a.logged_in))

async function load() {
  try {
    data.value = await fetchOverview()
    error.value = ''
  } catch (e) {
    error.value = errorMessage(e, 'Failed to load.')
  }
}

const refresh = debounce(load)
const { connected } = useLiveEvents((msg) => {
  if (msg.type !== 'reconcile') refresh()
})

async function onResolve(id) {
  await resolveAlert(id)
  load()
}

async function onResolveAll() {
  await resolveAllAlerts()
  load()
}

const checkIcon = { ok: 'mdi-check-circle', warn: 'mdi-alert', error: 'mdi-close-circle' }
const checkColor = { ok: 'success', warn: 'warning', error: 'error' }

onMounted(load)
</script>

<template>
  <div>
    <div class="d-flex align-center mb-4">
      <h1 class="page-title">Home</h1>
      <v-spacer />
      <v-chip size="small" :color="connected ? 'success' : 'grey'" variant="tonal" label
        :title="connected ? 'Live updates on' : 'Live updates off; page refreshes on reload'">
        <v-icon start :icon="connected ? 'mdi-access-point' : 'mdi-access-point-off'" />
        {{ connected ? 'Live' : 'Offline' }}
      </v-chip>
    </div>

    <v-alert v-if="error" type="error" class="mb-4">{{ error }}</v-alert>
    <v-progress-linear v-if="!data && !error" indeterminate />

    <v-row v-if="data">
      <!-- Copy mode -->
      <v-col cols="12" md="6">
        <v-card height="100%">
          <v-card-item>
            <v-card-subtitle>Copying</v-card-subtitle>
            <v-card-title class="d-flex align-center ga-2">
              <v-icon :icon="mode.icon" :color="mode.color" />
              {{ mode.label }}
            </v-card-title>
          </v-card-item>
          <v-card-text>
            <p>{{ mode.text }}</p>
            <p class="mt-2 text-medium-emphasis">
              Market is {{ data.market_open ? 'open' : 'closed' }}
              {{ data.market_open ? '' : '(copying runs 9:15 AM to 3:30 PM IST, Mon to Fri)' }}.
            </p>
          </v-card-text>
          <v-card-actions>
            <v-btn :to="{ name: 'settings' }" prepend-icon="mdi-swap-horizontal">Change</v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <!-- Readiness checklist -->
      <v-col cols="12" md="6">
        <v-card height="100%">
          <v-card-item>
            <v-card-subtitle>Ready to trade?</v-card-subtitle>
            <v-card-title>{{ allOk ? 'All good' : 'Needs attention' }}</v-card-title>
          </v-card-item>
          <v-list density="compact" class="py-0">
            <v-list-item v-for="(c, i) in data.checks" :key="i" :title="c.text">
              <template #prepend>
                <v-icon :icon="checkIcon[c.level]" :color="checkColor[c.level]" />
              </template>
            </v-list-item>
          </v-list>
          <v-card-actions v-if="needsLogin">
            <v-btn color="primary" variant="flat" :to="{ name: 'accounts' }" prepend-icon="mdi-login">
              Log in to Zerodha
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <!-- Alerts -->
      <v-col cols="12">
        <v-card>
          <v-card-item>
            <v-card-title class="d-flex align-center">
              Alerts
              <v-chip v-if="data.alerts.length" color="error" size="small" class="ml-2">{{ data.alerts.length }}</v-chip>
              <v-spacer />
              <v-btn v-if="data.alerts.length > 1" size="small" variant="text" @click="onResolveAll">Dismiss all</v-btn>
            </v-card-title>
          </v-card-item>
          <v-card-text v-if="!data.alerts.length" class="text-medium-emphasis">No open alerts.</v-card-text>
          <v-list v-else lines="three" class="py-0">
            <v-list-item v-for="a in data.alerts" :key="a.id">
              <v-list-item-title class="d-flex align-center ga-2">
                <strong>{{ a.kind_display }}</strong>
                <span v-if="a.count > 1" class="text-medium-emphasis text-body-2">× {{ a.count }}</span>
                <span class="text-medium-emphasis text-body-2">· {{ fmtTime(a.last_seen_at) }}</span>
              </v-list-item-title>
              <div class="text-body-2 alert-msg">{{ a.message }}</div>
              <template #append>
                <v-btn size="small" variant="text" @click="onResolve(a.id)">Dismiss</v-btn>
              </template>
            </v-list-item>
          </v-list>
        </v-card>
      </v-col>

      <!-- Recent orders -->
      <v-col cols="12">
        <v-card>
          <v-card-item>
            <v-card-title class="d-flex align-center">
              Recent master orders
              <v-spacer />
              <v-btn size="small" variant="text" :to="{ name: 'orders' }">See all</v-btn>
            </v-card-title>
          </v-card-item>
          <v-card-text v-if="!data.recent_trades.length" class="text-medium-emphasis">
            No orders copied yet.
          </v-card-text>
          <div v-else class="table-scroll">
            <v-table density="compact">
              <thead>
                <tr><th>Time</th><th>Order</th><th>Copies</th></tr>
              </thead>
              <tbody>
                <tr v-for="t in data.recent_trades" :key="t.id">
                  <td class="text-no-wrap">{{ fmtTime(t.observed_at) }}</td>
                  <td class="text-no-wrap">
                    <span :class="t.side === 'BUY' ? 'text-success' : 'text-error'">{{ t.side }}</span>
                    {{ t.quantity }} {{ t.tradingsymbol }}
                    <v-chip size="x-small" label class="ml-1" :color="MASTER_STATUS[t.status]?.color">
                      {{ MASTER_STATUS[t.status]?.label || t.status }}
                    </v-chip>
                  </td>
                  <td>
                    <span v-if="!t.copies.length" class="text-medium-emphasis">
                      {{ t.finalized ? 'Not copied' : 'Waiting…' }}
                    </span>
                    <v-chip
                      v-for="c in t.copies" :key="c.id" size="small" label class="mr-1 my-1"
                      :color="copyState(c).color" :title="c.error_message"
                    >
                      {{ c.account }}: {{ c.computed_quantity }} {{ copyState(c).label }}
                    </v-chip>
                  </td>
                </tr>
              </tbody>
            </v-table>
          </div>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<style scoped>
.alert-msg { white-space: normal; }
</style>
