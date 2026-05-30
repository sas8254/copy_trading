<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { fetchOverview, resolveAlert, dashboardWsUrl } from '@/api/copytrading'

const data = ref(null)
const loading = ref(true)
const error = ref('')
const events = ref([])
const connected = ref(false)

let ws = null
let refreshTimer = null
let reconnectTimer = null

const runtime = computed(() => data.value?.runtime || {})

const statusColor = {
  placed: 'success', simulated: 'warning', failed: 'error',
  skipped: 'grey', pending: 'info',
}
const alertColor = {
  mismatch: 'error', order_failed: 'error', zero_qty: 'grey', token_expired: 'warning',
}

async function load() {
  try {
    data.value = await fetchOverview()
    error.value = ''
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || 'Failed to load'
  } finally {
    loading.value = false
  }
}

// Debounced refresh so a burst of events triggers at most one reload.
function scheduleRefresh() {
  if (refreshTimer) return
  refreshTimer = setTimeout(() => {
    refreshTimer = null
    load()
  }, 800)
}

function pushEvent(msg) {
  events.value.unshift({ t: new Date().toLocaleTimeString(), msg })
  if (events.value.length > 200) events.value.pop()
}

function connect() {
  ws = new WebSocket(dashboardWsUrl())
  ws.onopen = () => { connected.value = true }
  ws.onclose = () => {
    connected.value = false
    reconnectTimer = setTimeout(connect, 2000)
  }
  ws.onmessage = (e) => {
    let msg
    try { msg = JSON.parse(e.data) } catch { return }
    if (msg.type === 'snapshot') return // we already fetched via REST
    pushEvent(msg)
    // Refresh the tables when something material changes.
    if (['copy_order', 'alert', 'ticker_status', 'ticker_order'].includes(msg.type)) {
      scheduleRefresh()
    }
  }
}

async function onResolve(id) {
  await resolveAlert(id)
  load()
}

onMounted(() => { load(); connect() })
onBeforeUnmount(() => {
  if (ws) { ws.onclose = null; ws.close() }
  clearTimeout(reconnectTimer)
  clearTimeout(refreshTimer)
})
</script>

<template>
  <div>
    <div class="d-flex align-center mb-4">
      <h2 class="text-h5">Copy Trading</h2>
      <v-chip class="ml-4" :color="connected ? 'success' : 'error'" size="small" label>
        <v-icon start :icon="connected ? 'mdi-lan-connect' : 'mdi-lan-disconnect'" />
        {{ connected ? 'live' : 'offline' }}
      </v-chip>
      <v-spacer />
      <v-chip :color="runtime.live_orders ? 'error' : 'grey'" size="small" label class="mr-2">
        {{ runtime.live_orders ? 'LIVE ORDERS' : 'DRY-RUN' }}
      </v-chip>
      <v-btn size="small" variant="text" icon="mdi-refresh" @click="load" />
    </div>

    <v-alert v-if="error" type="error" class="mb-4">{{ error }}</v-alert>
    <v-progress-linear v-if="loading" indeterminate class="mb-4" />

    <template v-if="data">
      <v-row>
        <!-- Accounts -->
        <v-col cols="12" md="6">
          <v-card>
            <v-card-title class="text-subtitle-1">Accounts</v-card-title>
            <v-table density="compact">
              <thead>
                <tr><th>Account</th><th>Role</th><th>Active</th><th>Token</th></tr>
              </thead>
              <tbody>
                <tr v-for="a in data.accounts" :key="a.id">
                  <td>{{ a.label }}</td>
                  <td><v-chip size="x-small" label>{{ a.role }}</v-chip></td>
                  <td><v-icon :color="a.active ? 'success' : 'error'"
                        :icon="a.active ? 'mdi-check' : 'mdi-close'" size="small" /></td>
                  <td><v-icon :color="a.has_token ? 'success' : 'error'"
                        :icon="a.has_token ? 'mdi-check' : 'mdi-close'" size="small" /></td>
                </tr>
              </tbody>
            </v-table>
          </v-card>
        </v-col>

        <!-- Mappings -->
        <v-col cols="12" md="6">
          <v-card>
            <v-card-title class="text-subtitle-1">Mappings</v-card-title>
            <v-table density="compact">
              <thead>
                <tr><th>Master</th><th>Copy</th><th>×</th><th>Zero-qty</th><th>Active</th></tr>
              </thead>
              <tbody>
                <tr v-for="m in data.mappings" :key="m.id">
                  <td>{{ m.master }}</td>
                  <td>{{ m.copy }}</td>
                  <td>{{ m.multiplier }}</td>
                  <td>{{ m.zero_qty_policy }}</td>
                  <td><v-icon :color="m.active ? 'success' : 'error'"
                        :icon="m.active ? 'mdi-check' : 'mdi-close'" size="small" /></td>
                </tr>
              </tbody>
            </v-table>
          </v-card>
        </v-col>

        <!-- Alerts -->
        <v-col cols="12">
          <v-card>
            <v-card-title class="text-subtitle-1">
              Open Alerts
              <v-chip size="x-small" class="ml-2" color="error" v-if="data.alerts.length">
                {{ data.alerts.length }}
              </v-chip>
            </v-card-title>
            <v-table density="compact">
              <thead>
                <tr><th>Kind</th><th>Account</th><th>×</th><th>Message</th><th></th></tr>
              </thead>
              <tbody>
                <tr v-if="!data.alerts.length"><td colspan="5" class="text-grey">No open alerts</td></tr>
                <tr v-for="a in data.alerts" :key="a.id">
                  <td><v-chip size="x-small" :color="alertColor[a.kind] || 'grey'" label>{{ a.kind }}</v-chip></td>
                  <td>{{ a.account }}</td>
                  <td>{{ a.count }}</td>
                  <td class="text-caption">{{ a.message }}</td>
                  <td><v-btn size="x-small" variant="text" @click="onResolve(a.id)">resolve</v-btn></td>
                </tr>
              </tbody>
            </v-table>
          </v-card>
        </v-col>

        <!-- Copy orders -->
        <v-col cols="12" md="7">
          <v-card>
            <v-card-title class="text-subtitle-1">Copy Orders</v-card-title>
            <v-table density="compact" class="scroll">
              <thead>
                <tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Copy</th><th>Status</th><th>Broker ID</th></tr>
              </thead>
              <tbody>
                <tr v-if="!data.copy_orders.length"><td colspan="6" class="text-grey">None yet</td></tr>
                <tr v-for="c in data.copy_orders" :key="c.id">
                  <td>{{ c.symbol }}</td>
                  <td>{{ c.side }}</td>
                  <td>{{ c.qty }}</td>
                  <td>{{ c.copy }}</td>
                  <td><v-chip size="x-small" :color="statusColor[c.status] || 'grey'" label>{{ c.status }}</v-chip></td>
                  <td class="text-caption">{{ c.broker_order_id }}</td>
                </tr>
              </tbody>
            </v-table>
          </v-card>
        </v-col>

        <!-- Live events -->
        <v-col cols="12" md="5">
          <v-card>
            <v-card-title class="text-subtitle-1">Live Events</v-card-title>
            <div class="events">
              <div v-for="(e, i) in events" :key="i" class="event">
                <span class="text-grey mr-2">{{ e.t }}</span>
                <span>{{ JSON.stringify(e.msg) }}</span>
              </div>
              <div v-if="!events.length" class="text-grey pa-2">Waiting for events…</div>
            </div>
          </v-card>
        </v-col>
      </v-row>
    </template>
  </div>
</template>

<style scoped>
.events { height: 320px; overflow-y: auto; font-family: ui-monospace, monospace; font-size: 12px; }
.event { padding: 2px 8px; border-bottom: 1px solid rgba(0,0,0,.06); white-space: nowrap; }
.scroll { max-height: 320px; overflow-y: auto; }
</style>
