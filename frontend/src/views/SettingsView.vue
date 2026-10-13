<script setup>
import { onMounted, ref } from 'vue'
import { errorMessage, fetchSettings, sendTestEmail, updateSettings } from '@/api/copytrading'
import { MODES, STYLES } from '@/utils/format'

const settings = ref(null)
const emails = ref('')
const error = ref('')
const snack = ref({ show: false, text: '', color: 'success' })
const confirmLive = ref(false)
const saving = ref(false)
const testing = ref(false)

function notify(text, color = 'success') {
  snack.value = { show: true, text, color }
}

async function load() {
  try {
    settings.value = await fetchSettings()
    emails.value = settings.value.alert_emails
  } catch (e) {
    error.value = errorMessage(e)
  }
}

async function save(data, message) {
  saving.value = true
  try {
    settings.value = await updateSettings(data)
    emails.value = settings.value.alert_emails
    notify(message)
  } catch (e) {
    notify(errorMessage(e), 'error')
  } finally {
    saving.value = false
  }
}

function pickMode(mode) {
  if (mode === settings.value.mode) return
  if (mode === 'live') {
    confirmLive.value = true
    return
  }
  save({ mode }, `Copying is now: ${MODES[mode].label}.`)
}

function goLive() {
  confirmLive.value = false
  save({ mode: 'live' }, 'Copying is LIVE. Real orders will be placed.')
}

async function onTestEmail() {
  testing.value = true
  try {
    const { sent_to: to } = await sendTestEmail()
    notify(`Test email sent to ${to.join(', ')}.`)
  } catch (e) {
    notify(errorMessage(e), 'error')
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <h1 class="page-title mb-4">Settings</h1>
    <v-alert v-if="error" type="error" class="mb-4">{{ error }}</v-alert>
    <v-progress-linear v-if="!settings && !error" indeterminate />

    <template v-if="settings">
      <v-card class="mb-4">
        <v-card-item>
          <v-card-title>Copying</v-card-title>
          <v-card-subtitle>Takes effect immediately, including for orders already queued.</v-card-subtitle>
        </v-card-item>
        <v-card-text>
          <v-row dense>
            <v-col v-for="(m, key) in MODES" :key="key" cols="12" sm="4">
              <v-card
                :variant="settings.mode === key ? 'flat' : 'outlined'"
                :color="settings.mode === key ? m.color : undefined"
                :disabled="saving" height="100%" @click="pickMode(key)"
              >
                <v-card-title class="d-flex align-center ga-2">
                  <v-icon :icon="m.icon" />
                  {{ m.label }}
                  <v-spacer />
                  <v-icon v-if="settings.mode === key" icon="mdi-check-circle" />
                </v-card-title>
                <v-card-text>{{ m.text }}</v-card-text>
              </v-card>
            </v-col>
          </v-row>
          <p class="text-medium-emphasis text-body-2 mt-3">
            Turning copying back on never copies orders the master made while it was off.
          </p>
        </v-card-text>
      </v-card>

      <v-card class="mb-4">
        <v-card-item>
          <v-card-title>Copy style</v-card-title>
          <v-card-subtitle>Applies to new master orders. Orders already in progress keep their style.</v-card-subtitle>
        </v-card-item>
        <v-card-text>
          <v-row dense>
            <v-col v-for="(st, key) in STYLES" :key="key" cols="12" sm="6">
              <v-card
                :variant="settings.copy_style === key ? 'flat' : 'outlined'"
                :color="settings.copy_style === key ? 'primary' : undefined"
                :disabled="saving" height="100%"
                @click="key !== settings.copy_style && save({ copy_style: key }, `Copy style: ${st.label}.`)"
              >
                <v-card-title class="d-flex align-center ga-2">
                  <v-icon :icon="st.icon" />
                  {{ st.label }}
                  <v-spacer />
                  <v-icon v-if="settings.copy_style === key" icon="mdi-check-circle" />
                </v-card-title>
                <v-card-text>{{ st.text }}</v-card-text>
              </v-card>
            </v-col>
          </v-row>
          <p class="text-medium-emphasis text-body-2 mt-3">
            Either way, once the master's order is done the copy is checked: if it filled less,
            it gets {{ settings.fill_grace_seconds }} seconds to fill at its own price, then the rest is bought at market.
            If it filled more (master cancelled), you get an alert.
          </p>
        </v-card-text>
      </v-card>

      <v-card class="mb-4">
        <v-card-item>
          <v-card-title>Instant copy feed</v-card-title>
          <v-card-subtitle>Needs the paid Kite Connect streaming add-on on the master's app.</v-card-subtitle>
        </v-card-item>
        <v-card-text>
          <v-switch
            :model-value="settings.instant_feed" color="primary" hide-details :disabled="saving"
            :label="settings.instant_feed ? 'On: copies start in under a second' : 'Off: master orders are checked every 2 seconds'"
            @update:model-value="(v) => save({ instant_feed: v }, `Instant copy feed turned ${v ? 'on' : 'off'}.`)"
          />
        </v-card-text>
      </v-card>

      <v-card>
        <v-card-item>
          <v-card-title>Alert emails</v-card-title>
          <v-card-subtitle>For failed copies, position mismatches and expired logins.</v-card-subtitle>
        </v-card-item>
        <v-card-text>
          <v-text-field
            v-model="emails" label="Send alerts to" placeholder="you@example.com, other@example.com"
            hint="Separate several addresses with commas." persistent-hint
          />
        </v-card-text>
        <v-card-actions>
          <v-btn color="primary" variant="flat" :loading="saving" :disabled="emails === settings.alert_emails"
            @click="save({ alert_emails: emails }, 'Alert emails saved.')">Save</v-btn>
          <v-btn :loading="testing" :disabled="!settings.alert_emails" @click="onTestEmail">Send test email</v-btn>
        </v-card-actions>
      </v-card>
    </template>

    <v-dialog v-model="confirmLive" max-width="460">
      <v-card title="Turn on live copying?">
        <v-card-text>
          Every filled order in the master account will be placed as a <strong>real order</strong>
          on each enabled copy account, using real money. Start with a small multiplier.
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="confirmLive = false">Cancel</v-btn>
          <v-btn color="error" variant="flat" @click="goLive">Go live</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snack.show" :color="snack.color" timeout="4000">{{ snack.text }}</v-snackbar>
  </div>
</template>
