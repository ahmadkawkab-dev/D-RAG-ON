import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  ArrowLeft,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  Mail,
  UserRound,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  ApiError,
  clearStoredAuth,
  confirmPasswordReset,
  getProfile,
  login,
  register,
  requestPasswordReset,
  storeAuth,
} from '../api/client'
import type { AuthSession } from '../api/types'
import { BubbleBackground } from './animate-ui/components/backgrounds/bubble'
import { ModeToggle } from './mode-toggle'
import { Alert, AlertDescription } from './ui/alert'
import { Button } from './ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card'
import { Field, FieldDescription, FieldGroup, FieldLabel } from './ui/field'
import { Input } from './ui/input'
import { Tabs, TabsList, TabsTrigger } from './ui/tabs'

type AuthView = 'login' | 'register' | 'forgot' | 'reset'

function readableAuthError(error: unknown) {
  if (error instanceof ApiError) return error.message
  if (error instanceof TypeError) return 'Unable to reach the API. Check that FastAPI is running and the API URL is correct.'
  return 'Authentication failed. Please try again.'
}

export function AuthPanel({ onAuthenticated }: { onAuthenticated: (auth: AuthSession) => void }) {
  const [view, setView] = useState<AuthView>('login')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [resetCode, setResetCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (view === 'forgot') {
        const result = await requestPasswordReset(email.trim())
        setView('reset')
        toast.success('Reset code requested', { description: result.message })
        return
      }

      if (view === 'reset') {
        if (newPassword !== confirmPassword) {
          setError('The new passwords do not match.')
          return
        }
        await confirmPasswordReset(
          email.trim(),
          resetCode.trim(),
          newPassword,
        )
        setPassword('')
        setResetCode('')
        setNewPassword('')
        setConfirmPassword('')
        setView('login')
        toast.success('Password updated', {
          description: 'You can now sign in with your new password.',
        })
        return
      }

      let resolvedName = email.split('@')[0] || 'User'
      let avatarUrl: string | null = null
      if (view === 'register') {
        const user = await register(email.trim(), password, fullName.trim())
        resolvedName = user.full_name
        avatarUrl = user.avatar_url
      }
      const tokens = await login(email.trim(), password)
      let auth: AuthSession = {
        email: email.trim().toLowerCase(),
        fullName: resolvedName,
        avatarUrl,
        tokens,
      }
      storeAuth(auth)
      try {
        const profile = await getProfile()
        auth = {
          ...auth,
          email: profile.email,
          fullName: profile.full_name,
          avatarUrl: profile.avatar_url,
        }
        storeAuth(auth)
      } catch (caught) {
        clearStoredAuth()
        throw caught
      }
      onAuthenticated(auth)
    } catch (caught) {
      setError(readableAuthError(caught))
    } finally {
      setBusy(false)
    }
  }

  const changeView = (nextView: AuthView) => {
    setView(nextView)
    setError('')
  }

  const title = view === 'login'
    ? 'Welcome back'
    : view === 'register'
      ? 'Create your account'
      : view === 'forgot'
        ? 'Forgot your password?'
        : 'Enter your reset code'

  const description = view === 'forgot'
    ? 'We will send a six-digit code to your email address.'
    : view === 'reset'
      ? 'Enter the code from your email and choose a new password.'
      : 'Secure knowledge access'

  return (
    <main className="relative flex min-h-svh items-center justify-center overflow-hidden bg-background p-4 sm:p-8">
      <BubbleBackground
        interactive
        aria-hidden="true"
        className="absolute inset-0 bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900"
        colors={{
          first: '99,102,241',
          second: '56,189,248',
          third: '139,92,246',
          fourth: '30,64,175',
          fifth: '71,85,105',
          sixth: '129,140,248',
        }}
      />
      <div className="absolute inset-0 bg-slate-950/35 backdrop-blur-[1px]" />
      <div className="absolute right-4 top-4 z-20 rounded-md bg-background/90 shadow-sm backdrop-blur">
        <ModeToggle />
      </div>

      <Card className="relative z-10 w-full max-w-md border-white/20 bg-background/90 shadow-2xl backdrop-blur-xl">
        <CardHeader className="space-y-3 text-center">
          <div className="mx-auto flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-lg shadow-primary/25">
            {view === 'forgot' || view === 'reset'
              ? <KeyRound className="size-5" aria-hidden="true" />
              : <LockKeyhole className="size-5" aria-hidden="true" />}
          </div>
          <div>
            <CardDescription className="mb-1 text-xs font-semibold uppercase tracking-[0.18em] text-primary">
              {description}
            </CardDescription>
            <CardTitle className="text-2xl">{title}</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          {(view === 'login' || view === 'register') && (
            <Tabs value={view} onValueChange={(value) => changeView(value as AuthView)} className="mb-6">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="login">Sign in</TabsTrigger>
                <TabsTrigger value="register">Register</TabsTrigger>
              </TabsList>
            </Tabs>
          )}

          <form onSubmit={submit} className="space-y-5">
            <FieldGroup>
              {view === 'register' && (
                <Field>
                  <FieldLabel htmlFor="full-name">Full name</FieldLabel>
                  <div className="relative">
                    <UserRound className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                    <Input
                      id="full-name"
                      required
                      maxLength={120}
                      value={fullName}
                      onChange={(event) => setFullName(event.target.value)}
                      autoComplete="name"
                      className="pl-9"
                    />
                  </div>
                </Field>
              )}

              {view !== 'reset' && (
                <Field>
                  <FieldLabel htmlFor="email">Email</FieldLabel>
                  <div className="relative">
                    <Mail className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                    <Input
                      id="email"
                      required
                      type="email"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      autoComplete="email"
                      className="pl-9"
                    />
                  </div>
                </Field>
              )}

              {view === 'reset' && (
                <>
                  <Field>
                    <FieldLabel htmlFor="reset-code">Six-digit code</FieldLabel>
                    <Input
                      id="reset-code"
                      required
                      inputMode="numeric"
                      pattern="[0-9]{6}"
                      maxLength={6}
                      value={resetCode}
                      onChange={(event) => setResetCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
                      autoComplete="one-time-code"
                      className="text-center font-mono text-lg tracking-[0.35em]"
                    />
                    <FieldDescription>Code sent to {email}</FieldDescription>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="new-password">New password</FieldLabel>
                    <Input
                      id="new-password"
                      required
                      minLength={8}
                      maxLength={72}
                      type="password"
                      value={newPassword}
                      onChange={(event) => setNewPassword(event.target.value)}
                      autoComplete="new-password"
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="confirm-password">Confirm new password</FieldLabel>
                    <Input
                      id="confirm-password"
                      required
                      minLength={8}
                      maxLength={72}
                      type="password"
                      value={confirmPassword}
                      onChange={(event) => setConfirmPassword(event.target.value)}
                      autoComplete="new-password"
                    />
                  </Field>
                </>
              )}

              {(view === 'login' || view === 'register') && (
                <Field>
                  <div className="flex items-center justify-between gap-3">
                    <FieldLabel htmlFor="password">Password</FieldLabel>
                    {view === 'login' && (
                      <Button
                        type="button"
                        variant="link"
                        size="sm"
                        className="h-auto p-0 text-xs"
                        onClick={() => changeView('forgot')}
                      >
                        Forgot password?
                      </Button>
                    )}
                  </div>
                  <div className="relative">
                    <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                    <Input
                      id="password"
                      required
                      minLength={8}
                      maxLength={72}
                      type="password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      autoComplete={view === 'login' ? 'current-password' : 'new-password'}
                      className="pl-9"
                    />
                  </div>
                </Field>
              )}
            </FieldGroup>

            {error && (
              <Alert variant="destructive" role="alert">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <Button className="w-full" size="lg" type="submit" disabled={busy}>
              {busy && <LoaderCircle className="animate-spin" aria-hidden="true" />}
              {busy
                ? 'Please wait...'
                : view === 'login'
                  ? 'Sign in'
                  : view === 'register'
                    ? 'Create account'
                    : view === 'forgot'
                      ? 'Send reset code'
                      : 'Change password'}
            </Button>

            {(view === 'forgot' || view === 'reset') && (
              <Button
                className="w-full"
                type="button"
                variant="ghost"
                onClick={() => changeView('login')}
              >
                <ArrowLeft aria-hidden="true" />
                Back to sign in
              </Button>
            )}
          </form>
        </CardContent>
      </Card>
    </main>
  )
}
