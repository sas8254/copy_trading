<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { errorMessage, fetchPositions } from '@/api/copytrading'
import { fmtMoney, pnlColor } from '@/utils/format'

const data = ref(null)
const error = ref('')
const loading = ref(false)
const autoRefresh = ref(true)
let timer = null

async function load() {
  loading.value = true
  try {
    data.value = await fetchPositions()
    error.value = ''
  } catch (e) {
    error.value = errorMessage(e, 'Failed to load positions.')
  } finally {
    loading.value = false
  }
}

const totalPnl = (rows) => rows.reduce((s, r) => s + Number(r.pnl || 0), 0)

onMounted(() => {
  load()
  timer = setInterval(() => { if (autoRefresh.value && !loading.value) load() }, 10000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div>
    <div class="d-flex align-center flex-wrap ga-2 mb-4">
      <h1 class="page-title">Positions</h1>
      <v-spacer />
      <v-switch v-model="autoRefresh" label="Auto-refresh" color="primary" density="compact" hide-details class="flex-grow-0" />
      <v-btn icon="mdi-refresh" variant="text" :loading="loading" title="Refresh" @click="load" />
    </div>

    <v-alert v-if="error" type="error" class="mb-4">{{ error }}</v-alert>
    <v-progress-linear v-if="!data && !error" indeterminate />

    <template v-if="data">
      <v-alert v-if="!data.master" type="info" variant="tonal">
        No master account yet. Add one on the Accounts page.
      </v-alert>

      <template v-else>
        <!-- Master -->
        <v-card class="mb-4">
          <v-card-item>
            <v-card-subtitle>Master</v-card-subtitle>
            <v-card-title>{{ data.master.label }}</v-card-title>
          </v-card-item>
          <v-card-text v-if="data.master.error">
            <v-alert type="warning" variant="tonal" density="compact">{{ data.master.error }}</v-alert>
          </v-card-text>
          <v-card-text v-else-if="!data.master.positions.length" class="text-medium-emphasis">
            No positions today.
          </v-card-text>
          <div v-else class="table-scroll">
            <v-table density="compact">
              <thead>
                <tr><th>Symbol</th><th>Product</th><th class="num">Qty</th><th class="num">Avg</th><th class="num">LTP</th><th class="num">P&amp;L</th></tr>
              </thead>
              <tbody>
                <tr v-for="p in data.master.positions" :key="p.exchange + p.symbol + p.product">
                  <td class="text-no-wrap">{{ p.symbol }} <span class="text-medium-emphasis text-caption">{{ p.exchange }}</span></td>
                  <td>{{ p.product }}</td>
                  <td class="num">{{ p.qty }}</td>
                  <td class="num">{{ fmtMoney(p.avg_price) }}</td>
                  <td class="num">{{ fmtMoney(p.last_price) }}</td>
                  <td class="num" :class="pnlColor(p.pnl)">{{ fmtMoney(p.pnl) }}</td>
                </tr>
              </tbody>
            </v-table>
          </div>
        </v-card>

        <!-- Each copy account vs expected -->
        <v-alert v-if="!data.copies.length" type="info" variant="tonal">No enabled copy accounts.</v-alert>
        <v-card v-for="c in data.copies" :key="c.id" class="mb-4">
          <v-card-item>
            <v-card-subtitle>Copy · × {{ Number(c.multiplier) }}</v-card-subtitle>
            <v-card-title class="d-flex align-center ga-2">
              {{ c.label }}
              <template v-if="!c.error && !data.master.error">
                <v-chip v-if="c.rows.every((r) => r.ok)" color="success" size="small" label>In sync</v-chip>
                <v-chip v-else color="error" size="small" label>
                  {{ c.rows.filter((r) => !r.ok).length }} mismatch{{ c.rows.filter((r) => !r.ok).length > 1 ? 'es' : '' }}
                </v-chip>
              </template>
            </v-card-title>
          </v-card-item>
          <v-card-text v-if="c.error">
            <v-alert type="warning" variant="tonal" density="compact">{{ c.error }}</v-alert>
          </v-card-text>
          <v-card-text v-else-if="data.master.error" class="text-medium-emphasis">
            Can't compare until the master's positions load.
          </v-card-text>
          <v-card-text v-else-if="!c.rows.length" class="text-medium-emphasis">
            No positions on either side.
          </v-card-text>
          <div v-else class="table-scroll">
            <v-table density="compact">
              <thead>
                <tr><th>Symbol</th><th class="num">Master</th><th class="num">Expected</th><th class="num">Actual</th><th></th><th class="num">P&amp;L</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in c.rows" :key="r.exchange + r.symbol" :class="{ mismatch: !r.ok }">
                  <td class="text-no-wrap">{{ r.symbol }} <span class="text-medium-emphasis text-caption">{{ r.exchange }}</span></td>
                  <td class="num">{{ r.master_qty }}</td>
                  <td class="num">{{ r.expected }}</td>
                  <td class="num">{{ r.actual }}</td>
                  <td><v-icon :icon="r.ok ? 'mdi-check' : 'mdi-alert'" :color="r.ok ? 'success' : 'error'" size="small" /></td>
                  <td class="num" :class="pnlColor(r.pnl)">{{ fmtMoney(r.pnl) }}</td>
                </tr>
              </tbody>
              <tfoot>
                <tr>
                  <td colspan="5" class="text-medium-emphasis">Total P&amp;L</td>
                  <td class="num font-weight-medium" :class="pnlColor(totalPnl(c.rows))">{{ fmtMoney(totalPnl(c.rows)) }}</td>
                </tr>
              </tfoot>
            </v-table>
          </div>
        </v-card>

        <p class="text-medium-emphasis text-body-2">
          Expected = master quantity × multiplier, rounded down to whole lots. Fix any mismatch
          directly in Zerodha.
        </p>
      </template>
    </template>
  </div>
</template>

<style scoped>
.mismatch { background: rgba(var(--v-theme-error), 0.08); }
</style>
