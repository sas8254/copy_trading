<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const { mdAndUp } = useDisplay()
const drawer = ref(false)

const nav = [
  { to: { name: 'home' }, title: 'Home', icon: 'mdi-home-outline' },
  { to: { name: 'accounts' }, title: 'Accounts', icon: 'mdi-account-multiple-outline' },
  { to: { name: 'positions' }, title: 'Positions', icon: 'mdi-scale-balance' },
  { to: { name: 'orders' }, title: 'Orders', icon: 'mdi-format-list-bulleted' },
  { to: { name: 'settings' }, title: 'Settings', icon: 'mdi-cog-outline' },
]

async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <v-app>
    <template v-if="auth.isAuthenticated">
      <v-app-bar color="primary" density="compact" flat>
        <v-app-bar-nav-icon v-if="!mdAndUp" @click="drawer = !drawer" />
        <v-app-bar-title>Copy Trading</v-app-bar-title>
        <template v-if="mdAndUp">
          <v-btn v-for="item in nav" :key="item.title" :to="item.to" :prepend-icon="item.icon" exact>
            {{ item.title }}
          </v-btn>
        </template>
        <v-btn icon="mdi-logout" title="Log out" @click="onLogout" />
      </v-app-bar>

      <v-navigation-drawer v-if="!mdAndUp" v-model="drawer" temporary>
        <v-list nav>
          <v-list-item
            v-for="item in nav" :key="item.title" :to="item.to"
            :prepend-icon="item.icon" :title="item.title" exact @click="drawer = false"
          />
        </v-list>
      </v-navigation-drawer>
    </template>

    <v-main>
      <v-container class="page">
        <RouterView />
      </v-container>
    </v-main>
  </v-app>
</template>

<style>
.page { max-width: 1200px; }
.page-title { font-size: 1.5rem; font-weight: 500; margin: 0; }
.section-title { font-size: 1.05rem; font-weight: 500; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.table-scroll { overflow-x: auto; }
</style>
