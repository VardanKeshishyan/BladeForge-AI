import { AppTopBar } from '@/components/app/topbar'
import { RefreshButton } from '@/components/app/refresh-button'
import { serverApiRequest } from '@/lib/api/server'
import { API_URL } from '@/lib/api/http'
import { Monitor, Cpu, Sparkles } from 'lucide-react'

type Worker = { id: string; name: string; status: string; last_seen_at: string | null }

export default async function SettingsPage() {
  let workers: Worker[] = []
  let connectionError = ''
  try {
    workers = (await serverApiRequest<{ items: Worker[] }>('/v1/render-workers')).items
  } catch (error) {
    connectionError = error instanceof Error ? error.message : 'Unable to connect to the backend.'
  }
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <AppTopBar breadcrumbs={[{ label: 'Settings' }]} />
      <main className="flex-1 overflow-y-auto p-4 md:p-6">
        <div className="max-w-3xl space-y-6">
          <div className="flex items-start justify-between gap-4">
            <div><h1 className="text-xl font-bold">Workspace settings</h1><p className="mt-1 text-sm text-muted-foreground">Your local services and optional image editing.</p></div>
            <RefreshButton />
          </div>
          <section className="rounded-lg border border-border bg-card p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold"><Monitor className="size-4 text-primary" />Local backend</h2>
            <p className="mt-3 text-sm text-muted-foreground">The workspace connects to the API running on your computer.</p>
            <code className="mt-3 block break-all rounded bg-muted px-3 py-2 text-xs">{API_URL}</code>
            <p role={connectionError ? 'alert' : undefined} className={`mt-3 text-xs ${connectionError ? 'text-destructive' : 'text-primary'}`}>{connectionError || 'Connected'}</p>
          </section>
          <section className="rounded-lg border border-border bg-card p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold"><Cpu className="size-4 text-primary" />Render workers</h2>
            {workers.length ? (
              <ul className="mt-4 divide-y divide-border">
                {workers.map(worker => (
                  <li key={worker.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
                    <div><p className="font-medium">{worker.name}</p><p className="mt-1 text-xs text-muted-foreground">Last seen: {worker.last_seen_at ? new Date(worker.last_seen_at).toLocaleString('en-GB') : 'Not yet connected'}</p></div>
                    <span className="rounded-full bg-muted px-2.5 py-1 text-xs capitalize">{worker.status.replaceAll('_', ' ')}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="mt-3 text-sm text-muted-foreground">{connectionError ? 'Worker status is unavailable while the backend is disconnected.' : 'No workers registered yet. Start your render worker to process jobs.'}</p>}
          </section>
          <section className="rounded-lg border border-border bg-card p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="size-4 text-primary" />Gemini image editing</h2>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">Add your key to <code className="text-xs break-all">render_worker/.env.gemini.local</code>, then restart the worker. A nonempty <code className="text-xs">GEMINI_API_KEY</code> enables masked image editing for new jobs.</p>
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">Your key is managed by the worker and is never shown here. This page does not verify Gemini credentials or quota.</p>
          </section>
        </div>
      </main>
    </div>
  )
}
