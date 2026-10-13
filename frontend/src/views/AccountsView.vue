<script setup>
import { computed, onMounted, ref } from 'vue'
import { deleteAccount, errorMessage, fetchAccounts, makeMaster, updateAccount } from '@/api/copytrading'
import AccountDialog from '@/components/AccountDialog.vue'
import { fmtTime } from '@/utils/format'
import { kiteRedirectUrl, startKiteLogin } from '@/utils/kite'

const accounts = ref([])
const loading = ref(true)
const error = ref('')
const snack = ref({ show: false, text: '', color: 'success' })
const dialog = ref(false)
const editing = ref(null)
const confirm = ref({ show: false, title: '', text: '', action: null })
const busy = ref(null)

const master = computed(() => accounts.value.find((a) => a.is_master))
const copies = computed(() => accounts.value.filter((a) => !a.is_master))

async function load() {
  try {
    accounts.value = await fetchAccounts()
    error.value = ''
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

function notify(text, color = 'success') {
  snack.value = { show: true, text, color }
}

function openAdd() { editing.value = null; dialog.value = true }
function openEdit(a) { editing.value = a; dialog.value = true }

function onSaved(a) {
  notify(`Saved ${a.label}.`)
  load()
}

async function run(account, fn, done) {
  busy.value = account.id
  try {
    await fn()
    if (done) notify(done)
    await load()
  } catch (e) {
    notify(errorMessage(e), 'error')
  } finally {
    busy.value = null
  }
}

async function login(a) {
  busy.value = a.id
  try {
    await startKiteLogin(a) // navigates away to Zerodha
  } catch (e) {
    notify(errorMessage(e), 'error')
    busy.value = null
  }
}

function askConfirm(title, text, action) {
  confirm.value = { show: true, title, text, action }
}

async function onConfirm() {
  const { action } = confirm.value
  confirm.value.show = false
  await action()
}

function askMakeMaster(a) {
  askConfirm(
    `Make ${a.label} the master?`,
    `Trades in ${a.label} will be copied to all other enabled accounts.` +
      (master.value ? ` ${master.value.label} becomes a copy account.` : ''),
    () => run(a, () => makeMaster(a.id), `${a.label} is now the master.`),
  )
}

function askDelete(a) {
  askConfirm(
    `Delete ${a.label}?`,
    'This also deletes its order history. To stop using it for a while, disable it instead.',
    () => run(a, () => deleteAccount(a.id), `Deleted ${a.label}.`),
  )
}

const toggleActive = (a) =>
  run(a, () => updateAccount(a.id, { active: !a.active }), `${a.label} ${a.active ? 'disabled' : 'enabled'}.`)

function copyRedirect() {
  navigator.clipboard?.writeText(kiteRedirectUrl())
  notify('Redirect URL copied.')
}

onMounted(load)
</script>

<template>
  <div>
    <div class="d-flex align-center mb-4">
      <h1 class="page-title">Accounts</h1>
      <v-spacer />
      <v-btn color="primary" prepend-icon="mdi-plus" @click="openAdd">Add account</v-btn>
    </div>

    <v-progress-linear v-if="loading" indeterminate class="mb-4" />
    <v-alert v-if="error" type="error" class="mb-4">{{ error }}</v-alert>

    <v-alert v-if="!loading && !accounts.length" type="info" variant="tonal" class="mb-4">
      No accounts yet. Add the master account first (the one whose trades are copied), then the
      copy accounts.
    </v-alert>

    <template v-for="group in [{ title: 'Master', list: master ? [master] : [] }, { title: 'Copy accounts', list: copies }]" :key="group.title">
      <div v-if="group.list.length" class="section-title mb-2 mt-2">{{ group.title }}</div>
      <v-row v-if="group.list.length" class="mb-2">
        <v-col v-for="a in group.list" :key="a.id" cols="12" md="6">
          <v-card :class="{ 'disabled-card': !a.active }">
            <v-card-item>
              <v-card-title class="d-flex align-center flex-wrap ga-2">
                {{ a.label }}
                <v-chip v-if="a.is_master" color="primary" size="small" label>Master</v-chip>
                <v-chip v-else size="small" label>× {{ Number(a.multiplier) }}</v-chip>
                <v-chip v-if="!a.active" size="small" label>Disabled</v-chip>
              </v-card-title>
              <v-card-subtitle>{{ a.client_id || 'Zerodha user ID not set yet' }}</v-card-subtitle>
            </v-card-item>

            <v-card-text class="pt-0">
              <div class="d-flex align-center ga-2">
                <v-icon :color="a.logged_in ? 'success' : 'error'" :icon="a.logged_in ? 'mdi-check-circle' : 'mdi-alert-circle'" />
                <span v-if="a.logged_in">Logged in to Zerodha (at {{ fmtTime(a.token_updated_at) }})</span>
                <span v-else>Needs Zerodha login today</span>
              </div>
              <div v-if="!a.api_key || !a.has_api_secret" class="text-error text-body-2 mt-1">
                Missing API {{ !a.api_key ? 'key' : 'secret' }}. Click Edit to add it.
              </div>
            </v-card-text>

            <v-card-actions class="flex-wrap">
              <v-btn
                :color="a.logged_in ? undefined : 'primary'" :variant="a.logged_in ? 'text' : 'flat'"
                prepend-icon="mdi-login" :loading="busy === a.id" :disabled="!a.api_key || !a.has_api_secret"
                @click="login(a)"
              >
                {{ a.logged_in ? 'Log in again' : 'Login to Zerodha' }}
              </v-btn>
              <v-btn prepend-icon="mdi-pencil" @click="openEdit(a)">Edit</v-btn>
              <v-spacer />
              <v-menu>
                <template #activator="{ props }">
                  <v-btn icon="mdi-dots-vertical" variant="text" v-bind="props" />
                </template>
                <v-list density="compact">
                  <v-list-item v-if="!a.is_master" prepend-icon="mdi-crown-outline" title="Make master" @click="askMakeMaster(a)" />
                  <v-list-item
                    :prepend-icon="a.active ? 'mdi-pause' : 'mdi-play'"
                    :title="a.active ? 'Disable' : 'Enable'" @click="toggleActive(a)"
                  />
                  <v-list-item prepend-icon="mdi-delete-outline" title="Delete" class="text-error" @click="askDelete(a)" />
                </v-list>
              </v-menu>
            </v-card-actions>
          </v-card>
        </v-col>
      </v-row>
    </template>

    <v-card variant="tonal" class="mt-4">
      <v-card-text class="text-body-2">
        <strong>Zerodha logins expire every morning around 6 AM.</strong> Click
        <em>Login to Zerodha</em> on each account once a day before the market opens.
        Each Kite Connect app's Redirect URL must be
        <code>{{ kiteRedirectUrl() }}</code>
        <v-btn size="x-small" variant="text" icon="mdi-content-copy" title="Copy" @click="copyRedirect" />.
        If you are already logged in to a different Zerodha user in this browser, log out at
        kite.zerodha.com first.
      </v-card-text>
    </v-card>

    <AccountDialog v-model="dialog" :account="editing" @saved="onSaved" />

    <v-dialog v-model="confirm.show" max-width="440">
      <v-card :title="confirm.title" :text="confirm.text">
        <v-card-actions>
          <v-spacer />
          <v-btn @click="confirm.show = false">Cancel</v-btn>
          <v-btn color="primary" variant="flat" @click="onConfirm">Confirm</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snack.show" :color="snack.color" timeout="4000">{{ snack.text }}</v-snackbar>
  </div>
</template>

<style scoped>
.disabled-card { opacity: 0.6; }
code { word-break: break-all; }
</style>
