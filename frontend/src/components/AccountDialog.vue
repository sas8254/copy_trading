<script setup>
import { computed, ref, watch } from 'vue'
import { createAccount, errorMessage, updateAccount } from '@/api/copytrading'
import { kiteRedirectUrl } from '@/utils/kite'

const props = defineProps({
  modelValue: Boolean,
  account: { type: Object, default: null }, // null = add new
})
const emit = defineEmits(['update:modelValue', 'saved'])

const blank = () => ({
  label: '', client_id: '', api_key: '', api_secret: '',
  multiplier: '1', zero_qty_policy: 'skip_alert', active: true,
})
const form = ref(blank())
const error = ref('')
const saving = ref(false)
const isNew = computed(() => !props.account)

const zeroQtyOptions = [
  { value: 'skip_alert', title: 'Skip it and alert me' },
  { value: 'skip_silent', title: 'Skip it silently' },
  { value: 'round_up', title: 'Round up to 1 lot' },
]

watch(() => props.modelValue, (open) => {
  if (!open) return
  error.value = ''
  form.value = props.account
    ? { ...blank(), ...props.account, api_secret: '' }
    : blank()
})

const close = () => emit('update:modelValue', false)

async function save() {
  error.value = ''
  saving.value = true
  const data = {
    label: form.value.label,
    client_id: form.value.client_id.trim().toUpperCase(),
    api_key: form.value.api_key.trim(),
    multiplier: form.value.multiplier,
    zero_qty_policy: form.value.zero_qty_policy,
    active: form.value.active,
  }
  if (form.value.api_secret) data.api_secret = form.value.api_secret.trim()
  try {
    const saved = isNew.value
      ? await createAccount(data)
      : await updateAccount(props.account.id, data)
    emit('saved', saved)
    close()
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <v-dialog :model-value="modelValue" max-width="560" @update:model-value="close">
    <v-card>
      <v-card-title>{{ isNew ? 'Add account' : `Edit ${account.label}` }}</v-card-title>
      <v-card-text>
        <v-form @submit.prevent="save">
          <v-text-field v-model="form.label" label="Name" hint="Anything you like, e.g. Mom Zerodha" persistent-hint class="mb-2" />
          <v-text-field v-model="form.client_id" label="Zerodha user ID (optional)" hint="e.g. AB1234. Filled in automatically on first login." persistent-hint class="mb-2" />

          <div class="section-title mt-4 mb-1">Kite Connect app</div>
          <p class="text-medium-emphasis text-body-2 mb-3">
            From <a href="https://developers.kite.trade/apps" target="_blank" rel="noopener">developers.kite.trade</a>.
            Set the app's Redirect URL to <code>{{ kiteRedirectUrl() }}</code>
          </p>
          <v-text-field v-model="form.api_key" label="API key" autocomplete="off" />
          <v-text-field
            v-model="form.api_secret" label="API secret" type="password" autocomplete="new-password"
            :hint="!isNew && account.has_api_secret ? 'Saved. Leave blank to keep it.' : ''" persistent-hint
          />

          <template v-if="isNew || !account.is_master">
            <div class="section-title mt-4 mb-1">When copying to this account</div>
            <v-text-field
              v-model="form.multiplier" label="Quantity multiplier" type="number" min="0" step="0.5"
              hint="2 = twice the master's quantity, 0.5 = half. Rounded down to whole lots." persistent-hint class="mb-2"
            />
            <v-select v-model="form.zero_qty_policy" :items="zeroQtyOptions" label="If the quantity rounds down to 0 lots" />
          </template>

          <v-switch v-model="form.active" label="Enabled" color="primary" hide-details />
          <v-alert v-if="error" type="error" density="compact" class="mt-3">{{ error }}</v-alert>
        </v-form>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn @click="close">Cancel</v-btn>
        <v-btn color="primary" variant="flat" :loading="saving" @click="save">Save</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
