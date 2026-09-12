'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Clock, Copy, Database, RefreshCw, X } from 'lucide-react'
import { AppTopBar } from '@/components/app/topbar'
import { apiRequest, createIdempotencyKey } from '@/lib/api/client'
import { JOB_STATUS_CONFIG, type GenerationJob, type JobEvent } from '@/lib/types'

const ACTIVE_STATUSES = new Set(['awaiting_worker', 'queued', 'rendering', 'processing_annotations'])

function formatDate(value: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function JobDetailClient({
  initialJob,
  initialEvents,
}: {
  initialJob: GenerationJob
  initialEvents: JobEvent[]
}) {
  const router = useRouter()
  const [job, setJob] = useState(initialJob)
  const [events, setEvents] = useState(initialEvents)
  const [acting, setActing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!ACTIVE_STATUSES.has(job.status)) return
    const timer = window.setInterval(async () => {
      try {
        const [nextJob, nextEvents] = await Promise.all([
          apiRequest<GenerationJob>(`/v1/jobs/${job.id}`),
          apiRequest<{ items: JobEvent[] }>(`/v1/jobs/${job.id}/events`),
        ])
        setJob(nextJob)
        setEvents(nextEvents.items)
      } catch {
        // Keep the last known state and retry on the next interval.
      }
    }, 3000)
    return () => window.clearInterval(timer)
  }, [job.id, job.status])

  async function action(kind: 'cancel' | 'retry' | 'duplicate') {
    if (acting) return
    setActing(true)
    setError(null)
    try {
      const nextJob = await apiRequest<GenerationJob>(`/v1/jobs/${job.id}/${kind}`, {
        method: 'POST',
        headers: kind === 'duplicate'
          ? { 'Idempotency-Key': createIdempotencyKey('duplicate') }
          : undefined,
      })
      if (kind === 'duplicate') {
        router.push(`/app/jobs/${nextJob.id}`)
      } else {
        setJob(nextJob)
      }
      router.refresh()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The action failed.')
    } finally {
      setActing(false)
    }
  }

  const statusConfig = JOB_STATUS_CONFIG[job.status]
  const canCancel = ACTIVE_STATUSES.has(job.status)
  const canRetry = job.status === 'failed' || job.status === 'cancelled'

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <AppTopBar breadcrumbs={[{ label: 'Jobs', href: '/app/jobs' }, { label: job.name }]} />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl">
          <Link
            href="/app/jobs"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors mb-6"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            Back to jobs
          </Link>

          <div className="flex items-start justify-between gap-6 mb-6">
            <div>
              <h1 className="text-xl font-bold">{job.name}</h1>
              {job.description && <p className="text-sm text-muted-foreground mt-1">{job.description}</p>}
            </div>
            <div className="flex items-center gap-2">
              {canCancel && (
                <button
                  onClick={() => action('cancel')}
                  disabled={acting}
                  className="inline-flex items-center gap-1.5 border border-border px-3 py-1.5 text-xs disabled:opacity-50"
                >
                  <X className="w-3.5 h-3.5" />
                  Cancel
                </button>
              )}
              {canRetry && (
                <button
                  onClick={() => action('retry')}
                  disabled={acting}
                  className="inline-flex items-center gap-1.5 border border-border px-3 py-1.5 text-xs disabled:opacity-50"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  Retry
                </button>
              )}
              <button
                onClick={() => action('duplicate')}
                disabled={acting}
                className="inline-flex items-center gap-1.5 border border-border px-3 py-1.5 text-xs disabled:opacity-50"
              >
                <Copy className="w-3.5 h-3.5" />
                Duplicate
              </button>
              <span className={`text-sm font-semibold ml-2 ${statusConfig.color}`}>
                {statusConfig.label}
              </span>
            </div>
          </div>

          {error && (
            <div className="text-xs text-destructive border border-destructive/20 bg-destructive/5 px-3 py-2 mb-5">
              {error}
            </div>
          )}

          <div className="border border-border bg-card p-5 mb-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium">{job.current_stage.replace(/_/g, ' ')}</span>
              <span className="text-xs font-mono">{job.progress}%</span>
            </div>
            <div className="h-1.5 bg-muted overflow-hidden">
              <div className="h-full bg-primary transition-[width]" style={{ width: `${job.progress}%` }} />
            </div>
            <div className="grid grid-cols-3 gap-4 mt-4 text-xs">
              <div>
                <div className="text-muted-foreground">Worker</div>
                <div className="font-mono truncate">{job.worker_id ?? 'Not assigned'}</div>
              </div>
              <div>
                <div className="text-muted-foreground">Attempt</div>
                <div className="font-mono">{job.attempt_count} / {job.max_attempts}</div>
              </div>
              <div>
                <div className="text-muted-foreground">Submitted</div>
                <div className="font-mono">{formatDate(job.submitted_at)}</div>
              </div>
            </div>
          </div>

          {(job.failure_code || job.failure_message) && (
            <div className="border border-destructive/30 bg-destructive/5 p-4 mb-6">
              <div className="text-xs font-mono text-destructive mb-1">{job.failure_code}</div>
              <div className="text-sm text-destructive">{job.failure_message}</div>
            </div>
          )}

          <div className="grid md:grid-cols-2 gap-6 mb-8">
            <div className="border border-border bg-card p-5">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">Configuration</h2>
              <dl className="space-y-2.5">
                {[
                  ['Defect type', job.defect_type?.replace(/_/g, ' ') ?? '—'],
                  ['Severity range', `${job.severity_min} – ${job.severity_max}`],
                  ['Image count', job.image_count.toLocaleString()],
                  ['Resolution', `${job.image_width} × ${job.image_height}`],
                  ['Annotation format', job.annotation_format.replace(/_/g, ' ').toUpperCase()],
                  ['Dataset name', job.dataset_name ?? '—'],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-4">
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd className="text-xs font-mono capitalize text-right">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <div className="border border-border bg-card p-5">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">Timeline</h2>
              <dl className="space-y-2.5">
                {[
                  ['Created', formatDate(job.created_at)],
                  ['Started', formatDate(job.started_at)],
                  ['Completed', formatDate(job.completed_at)],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-4">
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd className="text-xs font-mono text-right">{value}</dd>
                  </div>
                ))}
              </dl>
              {job.status === 'complete' && (
                <Link
                  href="/app/datasets"
                  className="mt-5 inline-flex items-center gap-1.5 text-xs bg-primary text-primary-foreground px-3 py-1.5"
                >
                  <Database className="w-3.5 h-3.5" />
                  View dataset
                </Link>
              )}
            </div>
          </div>

          <div className="border border-border bg-card">
            <div className="px-5 py-3 border-b border-border flex items-center gap-2">
              <Clock className="w-3.5 h-3.5 text-muted-foreground" />
              <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Event log</h2>
            </div>
            {events.length === 0 ? (
              <div className="px-5 py-6 text-center text-xs text-muted-foreground">No events recorded yet.</div>
            ) : (
              <div className="divide-y divide-border">
                {events.map((event) => (
                  <div key={event.id} className="flex items-start gap-4 px-5 py-3">
                    <span className="text-[10px] font-mono text-muted-foreground whitespace-nowrap mt-0.5">
                      {new Date(event.created_at).toLocaleTimeString('en-GB')}
                    </span>
                    <span className="text-[10px] font-mono uppercase text-primary/80 min-w-[120px]">
                      {event.event_type}
                    </span>
                    <span className="text-xs text-muted-foreground flex-1">{event.message}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
