<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const username = ref('')
const email = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

const auth = useAuthStore()
const router = useRouter()

async function onSubmit() {
  error.value = ''
  loading.value = true
  try {
    await auth.register({
      username: username.value,
      email: email.value,
      password: password.value,
    })
    await auth.login(username.value, password.value)
    router.push({ name: 'profile' })
  } catch (e) {
    const data = e.response?.data
    if (data && typeof data === 'object') {
      // Surface the first field-level error message.
      const first = Object.entries(data)[0]
      error.value = `${first[0]}: ${Array.isArray(first[1]) ? first[1][0] : first[1]}`
    } else {
      error.value = 'Registration failed.'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <v-row justify="center">
    <v-col cols="12" sm="8" md="5">
      <v-card>
        <v-card-title>Register</v-card-title>
        <v-card-text>
          <v-form @submit.prevent="onSubmit">
            <v-text-field v-model="username" label="Username" required autofocus />
            <v-text-field v-model="email" label="Email" type="email" required />
            <v-text-field v-model="password" label="Password" type="password" required />
            <v-alert v-if="error" type="error" density="compact" class="mb-3">{{ error }}</v-alert>
            <v-btn type="submit" color="primary" :loading="loading" block>Create account</v-btn>
          </v-form>
        </v-card-text>
        <v-card-actions>
          <v-btn :to="{ name: 'login' }" variant="text">Already have an account?</v-btn>
        </v-card-actions>
      </v-card>
    </v-col>
  </v-row>
</template>
