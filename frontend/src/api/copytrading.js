import api from './client'

export function fetchOverview() {
  return api.get('/copytrading/overview/').then((r) => r.data)
}

export function resolveAlert(id) {
  return api.post(`/copytrading/alerts/${id}/resolve/`).then((r) => r.data)
}

// Build the dashboard WebSocket URL. Prefer VITE_WS_BASE_URL; otherwise derive
// it from the API base URL (swap http->ws, drop the /api suffix).
export function dashboardWsUrl() {
  const explicit = import.meta.env.VITE_WS_BASE_URL
  if (explicit) return `${explicit.replace(/\/$/, '')}/ws/dashboard/`
  const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
  const origin = apiBase.replace(/\/api\/?$/, '').replace(/^http/, 'ws')
  return `${origin}/ws/dashboard/`
}
