import { LoaderCircle, LogIn } from 'lucide-react'
import { beginGoogleLogin } from '../api/client'
import { BubbleBackground } from './animate-ui/components/backgrounds/bubble'
import { ModeToggle } from './mode-toggle'
import { Button } from './ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card'

export function AuthPanel({ loading = false }: { loading?: boolean }) {
  return (
    <main className="relative flex min-h-svh items-center justify-center overflow-hidden bg-background p-4 sm:p-8">
      <BubbleBackground
        interactive
        aria-hidden="true"
        className="absolute inset-0 bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900"
      />
      <div className="absolute inset-0 bg-slate-950/35 backdrop-blur-[1px]" />
      <div className="absolute right-4 top-4 z-20 rounded-md bg-background/90 shadow-sm backdrop-blur">
        <ModeToggle />
      </div>
      <Card className="relative z-10 w-full max-w-md border-white/20 bg-background/90 shadow-2xl backdrop-blur-xl">
        <CardHeader className="space-y-3 text-center">
          <CardDescription className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
            Secure knowledge access
          </CardDescription>
          <CardTitle className="text-2xl">Sign in to Pixel Mind</CardTitle>
        </CardHeader>
        <CardContent>
          <Button
            type="button"
            className="w-full"
            disabled={loading}
            onClick={beginGoogleLogin}
          >
            {loading
              ? <LoaderCircle className="animate-spin" aria-hidden="true" />
              : <LogIn aria-hidden="true" />}
            {loading ? 'Restoring session…' : 'Continue with Google'}
          </Button>
          <p className="mt-4 text-center text-xs text-muted-foreground">
            Powered by D-RAG-ON the best open-source RAG framework for LLMs. 
            Your data is never stored or shared.
          </p>
        </CardContent>
      </Card>
    </main>
  )
}
