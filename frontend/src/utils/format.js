export const MODES = {
  off: { label: 'Off', color: 'grey', icon: 'mdi-pause-circle', text: 'Nothing is copied.' },
  dry_run: {
    label: 'Dry run', color: 'warning', icon: 'mdi-test-tube',
    text: 'Copies are simulated only. No real orders are placed.',
  },
  live: {
    label: 'Live', color: 'error', icon: 'mdi-flash',
    text: 'Real orders are placed on copy accounts.',
  },
}

export const STYLES = {
  on_fill: {
    label: 'When filled', icon: 'mdi-check-all',
    text: "Copy once the master's order has filled. Simple, never copies orders that don't fill.",
  },
  mirror: {
    label: 'Mirror', icon: 'mdi-content-copy',
    text: "Copy as soon as the master places an order, at the same price, and follow its changes and cancellation.",
  },
}

// Label + color for one copy order, from our status and the broker's.
export function copyState(c) {
  const prefix = c.kind === 'topup' ? 'Top-up ' : ''
  const part = `${c.filled_quantity}/${c.computed_quantity}`
  let s
  if (c.status === 'simulated') s = { color: 'warning', label: 'Simulated' }
  else if (c.status === 'pending') s = { color: 'info', label: 'Placing…' }
  else if (c.status === 'failed') s = { color: 'error', label: 'Failed' }
  else if (c.status === 'skipped') s = { color: 'grey', label: 'Skipped' }
  else if (c.broker_status === 'COMPLETE') s = { color: 'success', label: 'Filled' }
  else if (c.broker_status === 'REJECTED') s = { color: 'error', label: 'Rejected' }
  else if (c.broker_status === 'CANCELLED') {
    s = c.filled_quantity
      ? { color: 'success', label: `Part-filled ${part}` }
      : { color: 'grey', label: 'Cancelled' }
  } else {
    s = { color: 'info', label: c.filled_quantity ? `Open ${part}` : 'Open' }
  }
  return { color: s.color, label: prefix + s.label }
}

export const MASTER_STATUS = {
  COMPLETE: { color: 'success', label: 'Filled' },
  OPEN: { color: 'info', label: 'Open' },
  'TRIGGER PENDING': { color: 'info', label: 'Trigger pending' },
  CANCELLED: { color: 'grey', label: 'Cancelled' },
  REJECTED: { color: 'error', label: 'Rejected' },
}

export function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  const today = new Date().toDateString() === d.toDateString()
  return today
    ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : d.toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function fmtMoney(v) {
  if (v === null || v === undefined || v === '') return '—'
  return Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function pnlColor(v) {
  const n = Number(v)
  return n > 0 ? 'text-success' : n < 0 ? 'text-error' : ''
}
