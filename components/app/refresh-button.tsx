'use client'

import { useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { RefreshCw } from 'lucide-react'

export function RefreshButton() {
  const router = useRouter()
  const [pending, startTransition] = useTransition()
  return (
    <button type="button" disabled={pending} onClick={() => startTransition(() => router.refresh())}
      className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-xs hover:bg-muted disabled:opacity-50">
      <RefreshCw className={`size-3.5 ${pending ? 'animate-spin' : ''}`} aria-hidden="true" />
      {pending ? 'Refreshing…' : 'Refresh'}
    </button>
  )
}
