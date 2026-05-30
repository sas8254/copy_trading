<script setup>
import { RouterLink, RouterView } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

async function onLogout() {
  await auth.logout()
}
</script>

<template>
  <v-app>
    <v-app-bar color="primary" density="compact">
      <v-app-bar-title>Core</v-app-bar-title>
      <v-spacer />
      <template v-if="auth.isAuthenticated">
        <v-btn :to="{ name: 'dashboard' }">Dashboard</v-btn>
        <v-btn :to="{ name: 'profile' }" :exact="true">Profile</v-btn>
        <v-btn @click="onLogout">Logout</v-btn>
      </template>
      <template v-else>
        <v-btn :to="{ name: 'login' }">Login</v-btn>
        <v-btn :to="{ name: 'register' }">Register</v-btn>
      </template>
    </v-app-bar>

    <v-main>
      <v-container>
        <RouterView />
      </v-container>
    </v-main>
  </v-app>
</template>
