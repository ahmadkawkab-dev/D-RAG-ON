import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, login, register, storeAuth } from '../api/client'
import type { AuthSession } from '../api/types'
import { PixelBot } from './PixelBot'

function readableAuthError(error: unknown) {
  if (error instanceof ApiError) return error.message
  if (error instanceof TypeError) return 'Unable to reach the API. Check that FastAPI is running and the API URL is correct.'
  return 'Authentication failed. Please try again.'
}

export function AuthPanel({ onAuthenticated }: { onAuthenticated: (auth: AuthSession) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      let resolvedName = email.split('@')[0] || 'User'
      if (mode === 'register') {
        const user = await register(email.trim(), password, fullName.trim())
        resolvedName = user.full_name
      }
      const tokens = await login(email.trim(), password)
      const auth = { email: email.trim().toLowerCase(), fullName: resolvedName, tokens }
      storeAuth(auth)
      onAuthenticated(auth)
    } catch (caught) {
      setError(readableAuthError(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <PixelBot />
        <p className="eyebrow">SECURE KNOWLEDGE ACCESS</p>
        <h1>{mode === 'login' ? 'WELCOME BACK' : 'CREATE ACCOUNT'}</h1>
        <form onSubmit={submit}>
          {mode === 'register' && (
            <label>
              FULL NAME
              <input required maxLength={120} value={fullName} onChange={(event) => setFullName(event.target.value)} autoComplete="name" />
            </label>
          )}
          <label>
            EMAIL
            <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" />
          </label>
          <label>
            PASSWORD
            <input required minLength={8} maxLength={72} type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
          </label>
          {error && <p className="api-error" role="alert">{error}</p>}
          <button className="auth-submit" type="submit" disabled={busy}>
            {busy ? 'CONNECTING...' : mode === 'login' ? 'SIGN IN' : 'REGISTER'}
          </button>
        </form>
        <button
          className="auth-switch"
          type="button"
          onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}
        >
          {mode === 'login' ? 'NEED AN ACCOUNT? REGISTER' : 'ALREADY REGISTERED? SIGN IN'}
        </button>
      </section>
    </main>
  )
}
