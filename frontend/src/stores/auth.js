import { defineStore } from 'pinia'
import api from '@/api/client'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('auth_token') || null,
    user: null,
  }),
  getters: {
    isAuthenticated: (state) => !!state.token,
  },
  actions: {
    async login(username, password) {
      const { data } = await api.post('/auth/login/', { username, password })
      this.token = data.token
      localStorage.setItem('auth_token', data.token)
      await this.fetchMe()
    },
    async register(payload) {
      await api.post('/auth/register/', payload)
    },
    async fetchMe() {
      const { data } = await api.get('/auth/me/')
      this.user = data
      return data
    },
    async logout() {
      try {
        await api.post('/auth/logout/')
      } catch {
        // Even if server call fails (e.g. network), clear local state.
      }
      this.token = null
      this.user = null
      localStorage.removeItem('auth_token')
    },
  },
})
