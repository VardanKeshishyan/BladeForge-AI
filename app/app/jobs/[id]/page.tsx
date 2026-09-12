import { notFound } from 'next/navigation'
import { serverApiRequest } from '@/lib/api/server'
import { ApiError } from '@/lib/api/http'
import { type GenerationJob, type JobEvent } from '@/lib/types'
import { JobDetailClient } from './job-detail-client'

export default async function JobDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  let job: GenerationJob
  let events: JobEvent[]
  try {
    const [jobData, eventData] = await Promise.all([
      serverApiRequest<GenerationJob>(`/v1/jobs/${encodeURIComponent(id)}`),
      serverApiRequest<{ items: JobEvent[] }>(`/v1/jobs/${encodeURIComponent(id)}/events`),
    ])
    job = jobData
    events = eventData.items
  } catch (error) {
    if (error instanceof ApiError && [404, 422].includes(error.status)) notFound()
    throw error
  }

  return (
    <JobDetailClient
      initialJob={job}
      initialEvents={events}
    />
  )
}
