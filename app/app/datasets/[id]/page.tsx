import { notFound } from 'next/navigation'
import { serverApiRequest } from '@/lib/api/server'
import { ApiError } from '@/lib/api/http'
import Link from 'next/link'
import { AppTopBar } from '@/components/app/topbar'
import { type Dataset } from '@/lib/types'
import { ArrowLeft, Database } from 'lucide-react'
import { DownloadButton } from '@/components/app/download-button'

type DatasetFile = {
  id: string
  file_name: string
  file_type: string
  file_size_bytes: number
}

function formatBytes(bytes: number) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

export default async function DatasetDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  let ds: Dataset
  let files: DatasetFile[]
  try {
    const data = await serverApiRequest<{ dataset: Dataset; files: DatasetFile[] }>(`/v1/datasets/${encodeURIComponent(id)}`)
    ds = data.dataset
    files = data.files
  } catch (error) {
    if (error instanceof ApiError && [404, 422].includes(error.status)) notFound()
    throw error
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <AppTopBar
        breadcrumbs={[
          { label: 'Datasets', href: '/app/datasets' },
          { label: ds.name },
        ]}
      />

      <main className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl">
          <Link
            href="/app/datasets"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors mb-6"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            Back to datasets
          </Link>

          <div className="flex items-start justify-between mb-6">
            <div>
              <h1 className="text-xl font-bold">{ds.name}</h1>
              <p className="text-sm text-muted-foreground capitalize mt-0.5">
                {ds.defect_type?.replace(/_/g, ' ') ?? 'Unknown defect type'}
              </p>
            </div>
            {ds.status === 'available' && (
              <DownloadButton
                datasetId={ds.id}
                className="bg-primary text-primary-foreground px-4 py-2 text-xs font-medium hover:opacity-90 transition-opacity"
              />
            )}
          </div>

          <div className="grid md:grid-cols-3 gap-4 mb-8">
            {[
              { label: 'Images', value: ds.image_count.toLocaleString() },
              { label: 'Total size', value: formatBytes(ds.file_size_bytes) },
              {
                label: 'Annotation formats',
                value: ds.annotation_formats.length
                  ? ds.annotation_formats.join(', ')
                  : '—',
              },
            ].map((stat) => (
              <div key={stat.label} className="border border-border bg-card p-4">
                <div className="text-xs text-muted-foreground mb-1">{stat.label}</div>
                <div className="text-sm font-mono font-medium">{stat.value}</div>
              </div>
            ))}
          </div>

          {/* Files */}
          <div className="border border-border bg-card">
            <div className="px-5 py-3 border-b border-border flex items-center gap-2">
              <Database className="w-3.5 h-3.5 text-muted-foreground" />
              <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Files ({files?.length ?? 0})
              </h2>
            </div>
            {!files || files.length === 0 ? (
              <div className="px-5 py-8 text-center text-xs text-muted-foreground">
                No files attached to this dataset yet.
              </div>
            ) : (
              <div className="divide-y divide-border">
                <div className="grid grid-cols-[1fr_120px_80px_80px] gap-4 px-5 py-2 text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  <span>File name</span>
                  <span>Type</span>
                  <span>Size</span>
                  <span>Actions</span>
                </div>
                {(files as DatasetFile[]).map((file) => (
                  <div key={file.id} className="grid grid-cols-[1fr_120px_80px_80px] gap-4 px-5 py-3 items-center">
                    <span className="text-xs font-mono truncate">{file.file_name}</span>
                    <span className="text-xs text-muted-foreground">{file.file_type.replace(/_/g, ' ')}</span>
                    <span className="text-xs font-mono">{formatBytes(file.file_size_bytes)}</span>
                    <DownloadButton
                      datasetId={ds.id}
                      fileId={file.id}
                      className="text-xs text-muted-foreground hover:text-primary transition-colors"
                    />
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
