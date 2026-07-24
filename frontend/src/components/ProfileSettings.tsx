import type { ReactElement } from 'react'
import type { AuthSession } from '../api/types'
import { Avatar, AvatarFallback, AvatarImage } from './ui/avatar'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from './ui/sheet'

export function ProfileSettings({
  auth,
  children,
}: {
  auth: AuthSession
  onAuthChange: (auth: AuthSession) => void
  children: ReactElement
}) {
  const initials = auth.fullName.trim().slice(0, 1).toUpperCase() || 'U'

  return (
    <Sheet>
      <SheetTrigger asChild>{children}</SheetTrigger>
      <SheetContent className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Account</SheetTitle>
          <SheetDescription>
            Your identity is managed through Google. Passwords are not stored by this application.
          </SheetDescription>
        </SheetHeader>
        <div className="mt-8 flex flex-col items-center gap-4 px-4 text-center">
          <Avatar className="size-24 border-4 border-background shadow-lg ring-1 ring-border">
            {auth.avatarUrl && <AvatarImage src={auth.avatarUrl} alt="" />}
            <AvatarFallback className="bg-primary text-2xl text-primary-foreground">
              {initials}
            </AvatarFallback>
          </Avatar>
          <div>
            <p className="font-semibold">{auth.fullName}</p>
            <p className="text-sm text-muted-foreground">{auth.email}</p>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
