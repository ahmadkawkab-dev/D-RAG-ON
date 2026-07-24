import type { ReactNode } from 'react'
import { Toaster } from 'sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ThemeProvider, useTheme } from '@/components/theme-provider'

function ProviderContent({ children }: { children: ReactNode }) {
  const { theme } = useTheme()

  return (
    <TooltipProvider>
      {children}
      <Toaster
        theme={theme}
        position="top-right"
        richColors
        closeButton
        toastOptions={{ className: 'font-sans' }}
      />
    </TooltipProvider>
  )
}

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider defaultTheme="system" storageKey="pixel-mind-theme">
      <ProviderContent>{children}</ProviderContent>
    </ThemeProvider>
  )
}
