import { onBeforeUnmount, onMounted, ref } from 'vue'
import { dashboardWsUrl } from '@/api/copytrading'

// Subscribe to the backend's live event feed while the component is mounted.
// `onEvent` gets every message; `connected` reflects the socket state.
export function useLiveEvents(onEvent) {
  const connected = ref(false)
  let ws = null
  let retryTimer = null
  let stopped = false

  function connect() {
    const token = localStorage.getItem('auth_token')
    if (!token || stopped) return
    ws = new WebSocket(dashboardWsUrl(token))
    ws.onopen = () => { connected.value = true }
    ws.onclose = () => {
      connected.value = false
      if (!stopped) retryTimer = setTimeout(connect, 3000)
    }
    ws.onmessage = (e) => {
      try { onEvent(JSON.parse(e.data)) } catch { /* ignore bad frames */ }
    }
  }

  onMounted(connect)
  onBeforeUnmount(() => {
    stopped = true
    clearTimeout(retryTimer)
    if (ws) ws.close()
  })

  return { connected }
}

// Call `fn` at most once per `ms`, trailing (for bursts of live events).
export function debounce(fn, ms = 800) {
  let timer = null
  return () => {
    if (timer) return
    timer = setTimeout(() => { timer = null; fn() }, ms)
  }
}
