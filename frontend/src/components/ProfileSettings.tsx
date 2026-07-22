import { useRef, useState } from 'react'
import type { ChangeEvent, FormEvent, ReactElement } from 'react'
import {
  Bot,
  CheckCircle2,
  KeyRound,
  LoaderCircle,
  MessageSquareText,
  MessagesSquare,
  ShieldCheck,
  ThumbsUp,
  Upload,
  UserRound,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  ApiError,
  changePassword,
  getProfile,
  getUsage,
  storeAuth,
  updateProfile,
} from '../api/client'
import type { AuthSession, Usage } from '../api/types'
import { Avatar, AvatarFallback, AvatarImage } from './ui/avatar'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'
import { Field, FieldDescription, FieldGroup, FieldLabel } from './ui/field'
import { Input } from './ui/input'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from './ui/sheet'
import { Skeleton } from './ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs'

const MAX_AVATAR_BYTES = 512 * 1024
const allowedAvatarTypes = new Set(['image/png', 'image/jpeg', 'image/webp'])

function readableError(error: unknown) {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'Unable to update your account.'
}

function readAvatar(file: File): Promise<string> {
  if (!allowedAvatarTypes.has(file.type)) {
    return Promise.reject(new Error('Choose a PNG, JPEG, or WebP image.'))
  }
  if (file.size > MAX_AVATAR_BYTES) {
    return Promise.reject(new Error('Avatar images must be 512 KB or smaller.'))
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('Unable to read that image.'))
    reader.readAsDataURL(file)
  })
}

export function ProfileSettings({
  auth,
  onAuthChange,
  children,
}: {
  auth: AuthSession
  onAuthChange: (auth: AuthSession) => void
  children: ReactElement
}) {
  const [open, setOpen] = useState(false)
  const [fullName, setFullName] = useState(auth.fullName)
  const [avatarUrl, setAvatarUrl] = useState<string | null>(auth.avatarUrl ?? null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [loading, setLoading] = useState(false)
  const [savingProfile, setSavingProfile] = useState(false)
  const [savingPassword, setSavingPassword] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const initials = fullName.trim().slice(0, 1).toUpperCase() || 'U'

  const updateAuthFromProfile = (profile: {
    email: string
    full_name: string
    avatar_url: string | null
  }) => {
    const nextAuth: AuthSession = {
      ...auth,
      email: profile.email,
      fullName: profile.full_name,
      avatarUrl: profile.avatar_url,
    }
    storeAuth(nextAuth)
    onAuthChange(nextAuth)
  }

  const loadAccount = async () => {
    setLoading(true)
    try {
      const [profile, usageResult] = await Promise.all([getProfile(), getUsage()])
      setFullName(profile.full_name)
      setAvatarUrl(profile.avatar_url)
      setUsage(usageResult)
      updateAuthFromProfile(profile)
    } catch (caught) {
      toast.error('Unable to load account', { description: readableError(caught) })
    } finally {
      setLoading(false)
    }
  }

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen)
    if (nextOpen) void loadAccount()
  }

  const handleAvatar = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try {
      setAvatarUrl(await readAvatar(file))
    } catch (caught) {
      toast.error('Avatar not selected', { description: readableError(caught) })
    }
  }

  const saveProfile = async (event: FormEvent) => {
    event.preventDefault()
    setSavingProfile(true)
    try {
      const profile = await updateProfile({
        fullName: fullName.trim(),
        avatarUrl,
      })
      updateAuthFromProfile(profile)
      toast.success('Profile updated')
    } catch (caught) {
      toast.error('Unable to update profile', { description: readableError(caught) })
    } finally {
      setSavingProfile(false)
    }
  }

  const savePassword = async (event: FormEvent) => {
    event.preventDefault()
    if (newPassword !== confirmPassword) {
      toast.error('New passwords do not match')
      return
    }
    setSavingPassword(true)
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      toast.success('Password updated')
    } catch (caught) {
      toast.error('Unable to update password', { description: readableError(caught) })
    } finally {
      setSavingPassword(false)
    }
  }

  const usageCards = usage
    ? [
        { label: 'Conversations', value: usage.conversations, icon: MessagesSquare },
        { label: 'Messages', value: usage.messages, icon: MessageSquareText },
        { label: 'Answers', value: usage.assistant_answers, icon: Bot },
        { label: 'Feedback sent', value: usage.feedback_submitted, icon: ThumbsUp },
      ]
    : []

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetTrigger asChild>{children}</SheetTrigger>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Account settings</SheetTitle>
          <SheetDescription>
            Customize your profile, review usage, and manage account security.
          </SheetDescription>
        </SheetHeader>

        <Tabs defaultValue="profile" className="mt-6 px-4 pb-6">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="profile">Profile</TabsTrigger>
            <TabsTrigger value="security">Security</TabsTrigger>
            <TabsTrigger value="usage">Usage</TabsTrigger>
          </TabsList>

          <TabsContent value="profile" className="mt-6">
            {loading ? (
              <div className="space-y-4">
                <Skeleton className="mx-auto size-24 rounded-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : (
              <form onSubmit={saveProfile} className="space-y-6">
                <div className="flex flex-col items-center gap-3">
                  <Avatar className="size-24 border-4 border-background shadow-lg ring-1 ring-border">
                    {avatarUrl && <AvatarImage src={avatarUrl} alt="" />}
                    <AvatarFallback className="bg-primary text-2xl text-primary-foreground">
                      {initials}
                    </AvatarFallback>
                  </Avatar>
                  <div className="flex flex-wrap justify-center gap-2">
                    <Button type="button" variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
                      <Upload aria-hidden="true" />
                      Change avatar
                    </Button>
                    {avatarUrl && (
                      <Button type="button" variant="ghost" size="sm" onClick={() => setAvatarUrl(null)}>
                        Remove
                      </Button>
                    )}
                  </div>
                  <input
                    ref={fileInputRef}
                    className="sr-only"
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    onChange={handleAvatar}
                  />
                  <p className="text-center text-xs text-muted-foreground">PNG, JPEG, or WebP. Maximum 512 KB.</p>
                </div>

                <FieldGroup>
                  <Field>
                    <FieldLabel htmlFor="profile-name">Full name</FieldLabel>
                    <div className="relative">
                      <UserRound className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                      <Input
                        id="profile-name"
                        required
                        maxLength={120}
                        value={fullName}
                        onChange={(event) => setFullName(event.target.value)}
                        className="pl-9"
                      />
                    </div>
                  </Field>
                  <Field>
                    <FieldLabel>Email</FieldLabel>
                    <Input value={auth.email} disabled />
                    <FieldDescription>Email changes are not enabled for this account.</FieldDescription>
                  </Field>
                </FieldGroup>

                <Button type="submit" className="w-full" disabled={savingProfile || !fullName.trim()}>
                  {savingProfile && <LoaderCircle className="animate-spin" aria-hidden="true" />}
                  Save profile
                </Button>
              </form>
            )}
          </TabsContent>

          <TabsContent value="security" className="mt-6">
            <form onSubmit={savePassword} className="space-y-6">
              <div className="rounded-xl border bg-muted/40 p-4">
                <div className="flex items-start gap-3">
                  <ShieldCheck className="mt-0.5 size-5 text-primary" aria-hidden="true" />
                  <div>
                    <p className="text-sm font-medium">Password protection</p>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      Your current password is required before a new password can be saved.
                    </p>
                  </div>
                </div>
              </div>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="current-password">Current password</FieldLabel>
                  <Input
                    id="current-password"
                    required
                    type="password"
                    maxLength={72}
                    autoComplete="current-password"
                    value={currentPassword}
                    onChange={(event) => setCurrentPassword(event.target.value)}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="profile-new-password">New password</FieldLabel>
                  <Input
                    id="profile-new-password"
                    required
                    type="password"
                    minLength={8}
                    maxLength={72}
                    autoComplete="new-password"
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="profile-confirm-password">Confirm new password</FieldLabel>
                  <Input
                    id="profile-confirm-password"
                    required
                    type="password"
                    minLength={8}
                    maxLength={72}
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                  />
                </Field>
              </FieldGroup>
              <Button type="submit" className="w-full" disabled={savingPassword}>
                {savingPassword
                  ? <LoaderCircle className="animate-spin" aria-hidden="true" />
                  : <KeyRound aria-hidden="true" />}
                Update password
              </Button>
            </form>
          </TabsContent>

          <TabsContent value="usage" className="mt-6">
            {loading || !usage ? (
              <div className="grid grid-cols-2 gap-3">
                {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-28 rounded-xl" />)}
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                {usageCards.map(({ label, value, icon: Icon }) => (
                  <Card key={label} className="gap-3 py-4 shadow-none">
                    <CardContent className="px-4">
                      <Icon className="mb-4 size-5 text-primary" aria-hidden="true" />
                      <p className="text-2xl font-semibold tabular-nums">{value.toLocaleString()}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{label}</p>
                    </CardContent>
                  </Card>
                ))}
                <div className="col-span-2 mt-2 flex items-center gap-2 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
                  <CheckCircle2 className="size-4 text-emerald-500" aria-hidden="true" />
                  Usage reflects conversations stored for this account.
                </div>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  )
}
