'use client'

import Link from 'next/link'
import { AlertCircle } from 'lucide-react'

export default function WorkspaceError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <div className="max-w-md rounded-xl border border-border bg-card p-8">
        <AlertCircle className="size-6 text-muted-foreground" aria-hidden="true" />
        <h1 className="mt-4 text-lg font-semibold">Couldn&apos;t load this workspace page</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">Check that your local backend is running, then try again. You can check its connection in Settings.</p>
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button type="button" onClick={reset} className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:opacity-90">Try again</button>
          <Link href="/app/settings" className="rounded-md border border-border px-4 py-2 text-sm hover:bg-muted">Connection settings</Link>
        </div>
      </div>
    </main>
  )
}
