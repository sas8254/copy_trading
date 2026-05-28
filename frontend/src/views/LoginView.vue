<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

async function onSubmit() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    const next = typeof route.query.next === 'string' ? route.query.next : '/profile'
    router.push(next)
  } catch (e) {
    error.value = e.response?.data?.non_field_errors?.[0] || 'Login failed.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <v-row justify="center">
    <v-col cols="12" sm="8" md="5">
      <v-card>
        <v-card-title>Login</v-card-title>
        <v-card-text>
          <v-form @submit.prevent="onSubmit">
            <v-text-field v-model="username" label="Username" required autofocus />
            <v-text-field v-model="password" label="Password" type="password" required />
            <v-alert v-if="error" type="error" density="compact" class="mb-3">{{ error }}</v-alert>
            <v-btn type="submit" color="primary" :loading="loading" block>Sign in</v-btn>
          </v-form>
        </v-card-text>
        <v-card-actions>
          <v-btn :to="{ name: 'register' }" variant="text">Need an account?</v-btn>
        </v-card-actions>
      </v-card>
    </v-col>
  </v-row>
</template>
