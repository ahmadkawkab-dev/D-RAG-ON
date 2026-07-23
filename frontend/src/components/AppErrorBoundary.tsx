import { Component, type ErrorInfo, type ReactNode } from 'react'

type AppErrorBoundaryProps = {
  children: ReactNode
}

type AppErrorBoundaryState = {
  hasError: boolean
}

/** A class component is required because React error boundaries use lifecycle APIs. */
export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  public state: AppErrorBoundaryState = { hasError: false }

  public static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true }
  }

  public componentDidCatch(error: Error, info: ErrorInfo): void {
    // Keep diagnostic detail out of the UI while retaining it for development.
    if (import.meta.env.DEV) console.error(error, info)
  }

  public render(): ReactNode {
    if (this.state.hasError) {
      return (
        <main className="flex min-h-screen items-center justify-center bg-background p-6">
          <section className="max-w-md rounded-xl border bg-card p-6 text-card-foreground shadow-sm">
            <h1 className="text-lg font-semibold">Something went wrong</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Reload the application to recover. If this continues, contact support with the time of the error.
            </p>
            <button
              className="mt-5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
              type="button"
              onClick={() => window.location.reload()}
            >
              Reload application
            </button>
          </section>
        </main>
      )
    }

    return this.props.children
  }
}
