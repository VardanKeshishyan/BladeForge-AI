'use client'

import { useState } from 'react'
import { Download } from 'lucide-react'
import { apiRequest } from '@/lib/api/client'

export function DownloadButton({
  datasetId,
  fileId,
  label = 'Download',
  className = '',
}: {
  datasetId: string
  fileId?: string
  label?: string
  className?: string
}) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function download() {
    if (loading) return
    setLoading(true)
    setError(null)
    try {
      const path = fileId
        ? `/v1/datasets/${datasetId}/files/${fileId}/download`
        : `/v1/datasets/${datasetId}/download`
      const { url } = await apiRequest<{ url: string }>(path, { method: 'POST' })
      window.location.assign(url)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Download failed.')
      setLoading(false)
    }
  }

  return (
    <span className="inline-flex flex-col items-end">
      <button
        type="button"
        onClick={download}
        disabled={loading}
        className={`inline-flex items-center gap-1.5 disabled:opacity-50 ${className}`}
      >
        <Download className="w-3.5 h-3.5" />
        {loading ? 'Preparing…' : label}
      </button>
      {error && <span className="text-[10px] text-destructive mt-1">{error}</span>}
    </span>
  )
}

