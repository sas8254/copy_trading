<script setup>
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

onMounted(async () => {
  if (!auth.user) {
    await auth.fetchMe()
  }
})
</script>

<template>
  <v-row justify="center">
    <v-col cols="12" sm="8" md="6">
      <v-card>
        <v-card-title>Profile</v-card-title>
        <v-card-text>
          <div v-if="auth.user">
            <p><strong>ID:</strong> {{ auth.user.id }}</p>
            <p><strong>Username:</strong> {{ auth.user.username }}</p>
            <p><strong>Email:</strong> {{ auth.user.email || '—' }}</p>
            <p><strong>First name:</strong> {{ auth.user.first_name || '—' }}</p>
            <p><strong>Last name:</strong> {{ auth.user.last_name || '—' }}</p>
          </div>
          <v-progress-circular v-else indeterminate />
        </v-card-text>
      </v-card>
    </v-col>
  </v-row>
</template>
