import Link from 'next/link'
import { AppTopBar } from '@/components/app/topbar'
import { Zap, Database, CheckCircle, Clock, AlertTriangle, ArrowRight } from 'lucide-react'
import { JOB_STATUS_CONFIG, type GenerationJob, type Dataset } from '@/lib/types'
import { serverApiRequest } from '@/lib/api/server'

type OverviewSummary = {
  total_jobs: number
  active_jobs: number
  completed_jobs: number
  total_datasets: number
  total_images: number
  gpu_seconds: number
  storage_bytes: number
}

function formatBytes(bytes: number) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export default async function OverviewPage() {
  const [jobData, datasetData, summary] = await Promise.all([
    serverApiRequest<{ items: GenerationJob[] }>('/v1/jobs?page_size=10'),
    serverApiRequest<{ items: Dataset[] }>('/v1/datasets?page_size=6'),
    serverApiRequest<OverviewSummary>('/v1/overview/summary'),
  ])
  const jobs = jobData.items
  const datasets = datasetData.items

  const failedJobs = jobs.filter((j) => j.status === 'failed')
  const recentJobs = jobs.slice(0, 5)

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <AppTopBar breadcrumbs={[{ label: 'Overview' }]} />

      <main className="flex-1 overflow-y-auto p-6">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-xl font-bold">Your workspace</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Here&apos;s what&apos;s happening across your generation pipeline.
          </p>
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {[
            {
              label: 'Total datasets',
              value: summary.total_datasets,
              unit: 'datasets',
              icon: Database,
              href: '/app/datasets',
            },
            {
              label: 'Total images generated',
              value: summary.total_images.toLocaleString(),
              unit: 'images',
              icon: Zap,
              href: '/app/datasets',
            },
            {
              label: 'Active jobs',
              value: summary.active_jobs,
              unit: 'running',
              icon: Clock,
              href: '/app/jobs',
            },
            {
              label: 'Completed jobs',
              value: summary.completed_jobs,
              unit: 'complete',
              icon: CheckCircle,
              href: '/app/jobs',
            },
          ].map((stat) => (
            <Link
              key={stat.label}
              href={stat.href}
              className="bg-card border border-border p-4 hover:border-muted-foreground transition-colors group"
            >
              <div className="flex items-start justify-between mb-3">
                <stat.icon className="w-4 h-4 text-muted-foreground" strokeWidth={1.5} />
                <ArrowRight className="w-3 h-3 text-border group-hover:text-muted-foreground transition-colors" />
              </div>
              <div className="text-2xl font-bold font-mono mb-0.5">{stat.value}</div>
              <div className="text-xs text-muted-foreground">{stat.label}</div>
            </Link>
          ))}
        </div>

        <div className="grid lg:grid-cols-[1fr_360px] gap-6">
          {/* Recent jobs */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold">Recent jobs</h2>
              <Link href="/app/jobs" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                View all
              </Link>
            </div>

            {recentJobs.length === 0 ? (
              <div className="border border-dashed border-border bg-muted/30 p-8 text-center">
                <Zap className="w-6 h-6 text-border mx-auto mb-3" />
                <p className="text-sm text-muted-foreground mb-4">No generation jobs yet.</p>
                <Link
                  href="/app/generate"
                  className="inline-flex items-center gap-1.5 text-xs bg-primary text-primary-foreground px-3 py-1.5 hover:opacity-90 transition-opacity"
                >
                  <Zap className="w-3 h-3" />
                  Start first generation
                </Link>
              </div>
            ) : (
              <div className="border border-border bg-card divide-y divide-border">
                <div className="grid grid-cols-[1fr_100px_80px_70px] gap-4 px-4 py-2 text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  <span>Job</span>
                  <span>Defect type</span>
                  <span>Images</span>
                  <span>Status</span>
                </div>
                {recentJobs.map((job) => {
                  const statusConfig = JOB_STATUS_CONFIG[job.status]
                  return (
                    <Link
                      key={job.id}
                      href={`/app/jobs/${job.id}`}
                      className="grid grid-cols-[1fr_100px_80px_70px] gap-4 px-4 py-3 hover:bg-muted/50 transition-colors"
                    >
                      <div>
                        <div className="text-sm font-medium truncate">{job.name}</div>
                        <div className="text-xs text-muted-foreground">{timeAgo(job.created_at)}</div>
                      </div>
                      <div className="text-sm text-muted-foreground self-center truncate">
                        {job.defect_type?.replace(/_/g, ' ') ?? '—'}
                      </div>
                      <div className="text-sm font-mono self-center">
                        {job.image_count.toLocaleString()}
                      </div>
                      <div className={`text-xs self-center font-medium ${statusConfig.color}`}>
                        {statusConfig.label}
                      </div>
                    </Link>
                  )
                })}
              </div>
            )}
          </div>

          {/* Right column */}
          <div className="space-y-6">
            {/* Recent datasets */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold">Datasets</h2>
                <Link href="/app/datasets" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                  View all
                </Link>
              </div>
              {datasets.length === 0 ? (
                <div className="border border-dashed border-border bg-muted/30 p-6 text-center">
                  <p className="text-xs text-muted-foreground">No datasets yet.</p>
                </div>
              ) : (
                <div className="border border-border bg-card divide-y divide-border">
                  {datasets.slice(0, 4).map((ds) => (
                    <Link
                      key={ds.id}
                      href={`/app/datasets/${ds.id}`}
                      className="flex items-center justify-between px-4 py-2.5 hover:bg-muted/50 transition-colors"
                    >
                      <div>
                        <div className="text-xs font-medium truncate max-w-[160px]">{ds.name}</div>
                        <div className="text-[10px] text-muted-foreground">
                          {ds.image_count.toLocaleString()} images · {formatBytes(ds.file_size_bytes)}
                        </div>
                      </div>
                      <span
                        className={`text-[10px] font-medium ${
                          ds.status === 'available'
                            ? 'text-emerald-600'
                            : ds.status === 'archived'
                            ? 'text-muted-foreground'
                            : 'text-amber-600'
                        }`}
                      >
                        {ds.status}
                      </span>
                    </Link>
                  ))}
                </div>
              )}
            </div>

            {/* Quick actions */}
            <div>
              <h2 className="text-sm font-semibold mb-3">Quick actions</h2>
              <div className="space-y-2">
                <Link
                  href="/app/generate"
                  className="flex items-center gap-3 px-4 py-3 border border-border bg-card hover:border-muted-foreground transition-colors"
                >
                  <Zap className="w-4 h-4 text-primary" strokeWidth={1.5} />
                  <div>
                    <div className="text-xs font-medium">New generation job</div>
                    <div className="text-[10px] text-muted-foreground">Configure & render a batch</div>
                  </div>
                </Link>
                <Link
                  href="/app/datasets"
                  className="flex items-center gap-3 px-4 py-3 border border-border bg-card hover:border-muted-foreground transition-colors"
                >
                  <Database className="w-4 h-4 text-muted-foreground" strokeWidth={1.5} />
                  <div>
                    <div className="text-xs font-medium">Browse datasets</div>
                    <div className="text-[10px] text-muted-foreground">Review images and download exports</div>
                  </div>
                </Link>
                {failedJobs.length > 0 && (
                  <Link
                    href="/app/jobs?status=failed"
                    className="flex items-center gap-3 px-4 py-3 border border-destructive/30 bg-destructive/5 hover:border-destructive/50 transition-colors"
                  >
                    <AlertTriangle className="w-4 h-4 text-destructive" strokeWidth={1.5} />
                    <div>
                      <div className="text-xs font-medium text-destructive">
                        {failedJobs.length} failed job{failedJobs.length > 1 ? 's' : ''}
                      </div>
                      <div className="text-[10px] text-muted-foreground">Click to review</div>
                    </div>
                  </Link>
                )}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
