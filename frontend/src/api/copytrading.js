import api from './client'

const get = (url, params) => api.get(url, { params }).then((r) => r.data)
const post = (url, body) => api.post(url, body).then((r) => r.data)
const patch = (url, body) => api.patch(url, body).then((r) => r.data)

export const fetchOverview = () => get('/copytrading/overview/')
export const fetchPositions = () => get('/copytrading/positions/')
export const fetchOrders = (limit = 100) => get('/copytrading/orders/', { limit })

// Accounts
export const fetchAccounts = () => get('/copytrading/accounts/')
export const createAccount = (data) => post('/copytrading/accounts/', data)
export const updateAccount = (id, data) => patch(`/copytrading/accounts/${id}/`, data)
export const deleteAccount = (id) => api.delete(`/copytrading/accounts/${id}/`)
export const makeMaster = (id) => post(`/copytrading/accounts/${id}/make-master/`)
export const kiteLoginUrl = (id) => get(`/copytrading/accounts/${id}/login-url/`)
export const completeKiteLogin = (id, requestToken) =>
  post(`/copytrading/accounts/${id}/login/`, { request_token: requestToken })

// Settings
export const fetchSettings = () => get('/copytrading/settings/')
export const updateSettings = (data) => patch('/copytrading/settings/', data)
export const sendTestEmail = () => post('/copytrading/settings/test-email/')

// Alerts
export const fetchAlerts = (resolved = false) => get('/copytrading/alerts/', { resolved })
export const resolveAlert = (id) => post(`/copytrading/alerts/${id}/resolve/`)
export const resolveAllAlerts = () => post('/copytrading/alerts/resolve-all/')

// Pull a readable message out of a DRF error response.
export function errorMessage(e, fallback = 'Something went wrong.') {
  const data = e?.response?.data
  if (!data) return e?.message || fallback
  if (typeof data === 'string') return fallback
  if (data.detail) return data.detail
  const [field, msgs] = Object.entries(data)[0] || []
  if (!field) return fallback
  const msg = Array.isArray(msgs) ? msgs[0] : msgs
  return field === 'non_field_errors' ? msg : `${field.replace(/_/g, ' ')}: ${msg}`
}

// Live feed WebSocket URL. Prefer VITE_WS_BASE_URL; otherwise derive it from
// the API base URL (http->ws, drop /api). A relative API base ("/api" in the
// production build) means same origin.
export function dashboardWsUrl(token) {
  const explicit = import.meta.env.VITE_WS_BASE_URL
  const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
  let origin
  if (explicit) origin = explicit.replace(/\/$/, '')
  else if (apiBase.startsWith('/')) origin = window.location.origin.replace(/^http/, 'ws')
  else origin = apiBase.replace(/\/api\/?$/, '').replace(/^http/, 'ws')
  return `${origin}/ws/dashboard/?token=${encodeURIComponent(token)}`
}
