<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { completeKiteLogin, errorMessage } from '@/api/copytrading'
import { pendingKiteAccount } from '@/utils/kite'

const route = useRoute()
const state = ref('working') // working | ok | error
const message = ref('')

onMounted(async () => {
  const { request_token: token, status } = route.query
  const accountId = pendingKiteAccount(route.query)
  if (status !== 'success' || !token) {
    state.value = 'error'
    message.value = 'Zerodha login was cancelled or failed. Please try again.'
    return
  }
  if (!accountId) {
    state.value = 'error'
    message.value = 'Could not tell which account this login was for. Start again from the Accounts page.'
    return
  }
  try {
    const account = await completeKiteLogin(accountId, token)
    state.value = 'ok'
    message.value = `${account.label} is logged in to Zerodha (${account.client_id}).`
  } catch (e) {
    state.value = 'error'
    message.value = errorMessage(e, 'Login failed.')
  }
})
</script>

<template>
  <v-row justify="center" class="mt-8">
    <v-col cols="12" sm="8" md="6">
      <v-card>
        <v-card-title>Zerodha login</v-card-title>
        <v-card-text>
          <v-progress-linear v-if="state === 'working'" indeterminate />
          <v-alert v-else :type="state === 'ok' ? 'success' : 'error'">{{ message }}</v-alert>
        </v-card-text>
        <v-card-actions v-if="state !== 'working'">
          <v-btn color="primary" variant="flat" :to="{ name: 'accounts' }">Back to accounts</v-btn>
          <v-btn :to="{ name: 'home' }">Home</v-btn>
        </v-card-actions>
      </v-card>
    </v-col>
  </v-row>
</template>
