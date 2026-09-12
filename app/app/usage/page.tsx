import { AppTopBar } from '@/components/app/topbar'
import { serverApiRequest } from '@/lib/api/server'

type UsageSummary = {
  image_count: number
  successful_gpu_seconds: number
  failed_gpu_seconds: number
  render_attempts: number
  storage_bytes: number
  dataset_downloads: number
  billing_available: boolean
}

function formatBytes(bytes: number) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(1)} ${units[index]}`
}

export default async function UsagePage() {
  const usage = await serverApiRequest<UsageSummary>('/v1/usage/summary')
  const stats = [
    ['Images generated', usage.image_count.toLocaleString(), 'images'],
    ['Successful GPU time', (usage.successful_gpu_seconds / 60).toFixed(1), 'min'],
    ['Failed GPU time', (usage.failed_gpu_seconds / 60).toFixed(1), 'min'],
    ['Render attempts', usage.render_attempts.toLocaleString(), 'attempts'],
    ['Storage written', formatBytes(usage.storage_bytes), ''],
    ['Dataset downloads', usage.dataset_downloads.toLocaleString(), 'downloads'],
  ]

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <AppTopBar breadcrumbs={[{ label: 'Usage' }]} />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl">
          <h1 className="text-xl font-bold mb-1">Usage</h1>
          <p className="text-sm text-muted-foreground mb-6">Generation activity and resources used by your workspace.</p>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
            {stats.map(([label, value, unit]) => (
              <div key={label} className="border border-border bg-card p-4">
                <div className="text-xs text-muted-foreground mb-1">{label}</div>
                <div className="text-xl font-bold font-mono">{value}{unit && <span className="text-xs font-normal text-muted-foreground ml-1">{unit}</span>}</div>
              </div>
            ))}
          </div>
          <div className="border border-border bg-muted/30 p-4 text-xs text-muted-foreground">
            These figures track local rendering and storage. Any Gemini API charges are managed separately by your Google project.
          </div>
        </div>
      </main>
    </div>
  )
}
