import Link from 'next/link'
import { Database } from 'lucide-react'
import { AppTopBar } from '@/components/app/topbar'
import { serverApiRequest } from '@/lib/api/server'
import { type Dataset } from '@/lib/types'

type DatasetPage = {
  items: Dataset[]
  page: number
  page_size: number
  total: number
  pages: number
}

function formatBytes(bytes: number) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(1)} ${units[index]}`
}

export default async function DatasetsPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string }>
}) {
  const { page = '1' } = await searchParams
  const result = await serverApiRequest<DatasetPage>(`/v1/datasets?page=${page}&page_size=24`)
  const totalImages = result.items.reduce((sum, dataset) => sum + dataset.image_count, 0)
  const totalBytes = result.items.reduce((sum, dataset) => sum + dataset.file_size_bytes, 0)

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <AppTopBar breadcrumbs={[{ label: 'Datasets' }]} />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="mb-6">
          <h1 className="text-xl font-bold">Datasets</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {result.total} datasets · {totalImages.toLocaleString()} images on this page · {formatBytes(totalBytes)}
          </p>
        </div>
        {result.items.length === 0 ? (
          <div className="border border-dashed border-border bg-muted/30 p-16 text-center">
            <Database className="w-8 h-8 text-border mx-auto mb-4" />
            <h2 className="text-sm font-semibold mb-1">No datasets yet</h2>
            <p className="text-sm text-muted-foreground mb-6">
              A dataset appears only after its files and annotations pass validation.
            </p>
            <Link href="/app/generate" className="text-xs bg-primary text-primary-foreground px-4 py-2">
              Start a generation job
            </Link>
          </div>
        ) : (
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
            {result.items.map((dataset) => (
              <Link
                key={dataset.id}
                href={`/app/datasets/${dataset.id}`}
                className="border border-border bg-card p-5 hover:border-muted-foreground group"
              >
                <div className="flex items-start justify-between mb-3">
                  <Database className="w-4 h-4 text-muted-foreground" />
                  <span className={dataset.status === 'available' ? 'text-[10px] text-emerald-600' : 'text-[10px] text-muted-foreground'}>
                    {dataset.status}
                  </span>
                </div>
                <h3 className="text-sm font-semibold mb-1 truncate">{dataset.name}</h3>
                <p className="text-xs text-muted-foreground mb-4">Leading edge erosion</p>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div><div className="text-muted-foreground">Images</div><div className="font-mono">{dataset.image_count.toLocaleString()}</div></div>
                  <div><div className="text-muted-foreground">Size</div><div className="font-mono">{formatBytes(dataset.file_size_bytes)}</div></div>
                </div>
              </Link>
            ))}
          </div>
        )}
        {result.pages > 1 && (
          <div className="flex justify-end gap-3 mt-5 text-xs">
            {result.page > 1 && <Link href={`?page=${result.page - 1}`}>Previous</Link>}
            <span className="text-muted-foreground">Page {result.page} of {result.pages}</span>
            {result.page < result.pages && <Link href={`?page=${result.page + 1}`}>Next</Link>}
          </div>
        )}
      </main>
    </div>
  )
}
