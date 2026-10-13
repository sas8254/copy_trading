import { kiteLoginUrl } from '@/api/copytrading'

const KEY = 'kite_login_account'

// The Redirect URL to paste into each Kite Connect app (developers.kite.trade).
export const kiteRedirectUrl = () => `${window.location.origin}/kite/callback`

// Send the browser to Zerodha's login page for this account. Zerodha then
// redirects to /kite/callback, which finishes the login.
export async function startKiteLogin(account) {
  const { url } = await kiteLoginUrl(account.id)
  sessionStorage.setItem(KEY, String(account.id))
  window.location.assign(url)
}

// Which account the callback belongs to: Zerodha echoes our redirect_params
// back as ?account=..., with sessionStorage as a fallback.
export function pendingKiteAccount(query) {
  const id = query.account || sessionStorage.getItem(KEY)
  sessionStorage.removeItem(KEY)
  return id ? Number(id) : null
}
