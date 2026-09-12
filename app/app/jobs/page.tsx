import Link from 'next/link'
import { Zap } from 'lucide-react'
import { AppTopBar } from '@/components/app/topbar'
import { JOB_STATUS_CONFIG, type GenerationJob, type JobStatus } from '@/lib/types'
import { serverApiRequest } from '@/lib/api/server'

type JobsResponse = {
  items: GenerationJob[]
  page: number
  page_size: number
  total: number
  pages: number
}

function timeAgo(value: string) {
  const minutes = Math.floor((Date.now() - new Date(value).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`
  return `${Math.floor(minutes / 1440)}d ago`
}

export default async function JobsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; search?: string; sort?: string; page?: string }>
}) {
  const params = await searchParams
  const query = new URLSearchParams({
    page: params.page ?? '1',
    page_size: '25',
    sort: params.sort ?? 'created_at',
  })
  if (params.status) query.set('status', params.status)
  if (params.search) query.set('search', params.search)
  const result = await serverApiRequest<JobsResponse>(`/v1/jobs?${query}`)

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <AppTopBar breadcrumbs={[{ label: 'Jobs' }]} />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold">Generation jobs</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              {result.total} job{result.total !== 1 ? 's' : ''} in your pipeline
            </p>
          </div>
          <Link
            href="/app/generate"
            className="inline-flex items-center gap-1.5 bg-primary text-primary-foreground px-4 py-2 text-xs font-medium"
          >
            <Zap className="w-3.5 h-3.5" />
            New generation
          </Link>
        </div>

        <form className="flex items-center gap-2 mb-4">
          <input
            name="search"
            defaultValue={params.search}
            placeholder="Search jobs or datasets"
            className="h-8 w-64 px-3 text-xs border border-input bg-background"
          />
          <select
            name="status"
            defaultValue={params.status ?? ''}
            className="h-8 px-2 text-xs border border-input bg-background"
          >
            <option value="">All statuses</option>
            {Object.entries(JOB_STATUS_CONFIG).map(([value, config]) => (
              <option key={value} value={value}>{config.label}</option>
            ))}
          </select>
          <select
            name="sort"
            defaultValue={params.sort ?? 'created_at'}
            className="h-8 px-2 text-xs border border-input bg-background"
          >
            <option value="created_at">Newest first</option>
            <option value="name">Name</option>
            <option value="status">Status</option>
            <option value="progress">Progress</option>
          </select>
          <button className="h-8 px-3 bg-primary text-primary-foreground text-xs">Apply</button>
        </form>

        {result.items.length === 0 ? (
          <div className="border border-dashed border-border bg-muted/30 p-16 text-center">
            <Zap className="w-8 h-8 text-border mx-auto mb-4" />
            <h2 className="text-sm font-semibold mb-1">No matching jobs</h2>
            <p className="text-sm text-muted-foreground">Create a job or change the current filters.</p>
          </div>
        ) : (
          <div className="border border-border bg-card">
            <div className="grid grid-cols-[1fr_140px_80px_90px_110px_90px] gap-4 px-5 py-2.5 text-[10px] font-medium text-muted-foreground uppercase tracking-wider border-b border-border">
              <span>Name</span><span>Defect type</span><span>Images</span><span>Progress</span><span>Status</span><span>Created</span>
            </div>
            <div className="divide-y divide-border">
              {result.items.map((job) => {
                const status = JOB_STATUS_CONFIG[job.status as JobStatus]
                return (
                  <Link
                    key={job.id}
                    href={`/app/jobs/${job.id}`}
                    className="grid grid-cols-[1fr_140px_80px_90px_110px_90px] gap-4 px-5 py-3 hover:bg-muted/40 items-center"
                  >
                    <div>
                      <div className="text-sm font-medium truncate">{job.name}</div>
                      <div className="text-xs text-muted-foreground truncate">{job.current_stage?.replace(/_/g, ' ')}</div>
                    </div>
                    <div className="text-xs text-muted-foreground capitalize">Leading edge erosion</div>
                    <div className="text-xs font-mono">{job.image_count.toLocaleString()}</div>
                    <div className="text-xs font-mono">{job.progress}%</div>
                    <div className={`text-xs font-medium ${status.color}`}>{status.label}</div>
                    <div className="text-xs text-muted-foreground">{timeAgo(job.created_at)}</div>
                  </Link>
                )
              })}
            </div>
          </div>
        )}

        {result.pages > 1 && (
          <div className="flex items-center justify-end gap-2 mt-4 text-xs">
            {result.page > 1 && <Link href={`?${new URLSearchParams({ ...params, page: String(result.page - 1) })}`}>Previous</Link>}
            <span className="text-muted-foreground">Page {result.page} of {result.pages}</span>
            {result.page < result.pages && <Link href={`?${new URLSearchParams({ ...params, page: String(result.page + 1) })}`}>Next</Link>}
          </div>
        )}
      </main>
    </div>
  )
}

