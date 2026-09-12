export type JobStatus =
  | 'draft'
  | 'awaiting_worker'
  | 'queued'
  | 'rendering'
  | 'processing_annotations'
  | 'complete'
  | 'failed'
  | 'cancelled'

export type DatasetStatus = 'pending' | 'available' | 'archived'

export type OrgRole = 'owner' | 'administrator' | 'engineer' | 'viewer'

export type MemberStatus = 'active' | 'invited' | 'suspended'

export interface Profile {
  id: string
  full_name: string | null
  job_title: string | null
  organization_id: string | null
  onboarding_complete: boolean
  created_at: string
  updated_at: string
}

export interface Organization {
  id: string
  name: string
  slug: string
  owner_id: string
  created_at: string
  updated_at: string
}

export interface OrganizationMember {
  id: string
  organization_id: string
  user_id: string
  role: OrgRole
  status: MemberStatus
  invited_by: string | null
  joined_at: string
}

export interface GenerationJob {
  id: string
  organization_id: string
  created_by: string
  name: string
  status: JobStatus
  config: Record<string, unknown>
  defect_type: string | null
  severity_min: number | null
  severity_max: number | null
  image_count: number
  annotation_format: string
  dataset_name: string | null
  description: string | null
  estimated_size_mb: number | null
  estimated_size_bytes: number
  image_width: number
  image_height: number
  progress: number
  current_stage: string
  attempt_count: number
  max_attempts: number
  worker_id: string | null
  cancellation_requested_at: string | null
  failure_code: string | null
  failure_message: string | null
  started_at: string | null
  submitted_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface JobEvent {
  id: string
  job_id: string
  organization_id: string
  event_type: string
  message: string
  metadata: Record<string, unknown>
  created_by: string | null
  created_at: string
}

export interface Dataset {
  id: string
  organization_id: string
  job_id: string | null
  created_by: string
  name: string
  defect_type: string | null
  image_count: number
  annotation_formats: string[]
  file_size_bytes: number
  storage_path: string | null
  status: DatasetStatus
  created_at: string
  updated_at: string
}

export interface DefectProfile {
  id: string
  organization_id: string
  created_by: string
  name: string
  defect_type: string
  description: string | null
  severity_levels: string[]
  surface_parameters: Record<string, unknown>
  reference_image_paths: string[]
  is_system: boolean
  created_at: string
  updated_at: string
}

export interface ApiKey {
  id: string
  organization_id: string
  created_by: string
  name: string
  key_prefix: string
  key_hash: string
  status: 'active' | 'revoked'
  last_used_at: string | null
  revoked_at: string | null
  revoked_by: string | null
  created_at: string
}

export interface UsageEvent {
  id: string
  organization_id: string
  job_id: string | null
  event_type: string
  image_count: number
  gpu_seconds: number
  storage_bytes: number
  metadata: Record<string, unknown>
  recorded_at: string
}

export interface RenderWorkerConnection {
  id: string
  organization_id: string
  created_by: string
  name: string
  base_url: string | null
  health_endpoint: string
  status: 'not_connected' | 'connected' | 'error'
  last_seen_at: string | null
  created_at: string
  updated_at: string
}

// Defect type options
export const DEFECT_TYPES = [
  { value: 'leading_edge_erosion', label: 'Leading Edge Erosion' },
] as const

export const ANNOTATION_FORMATS = [
  { value: 'coco_json', label: 'COCO JSON' },
  { value: 'yolo_v8', label: 'YOLO v8' },
] as const

export const JOB_STATUS_CONFIG: Record<
  JobStatus,
  { label: string; color: string }
> = {
  draft: { label: 'Draft', color: 'text-muted-foreground' },
  awaiting_worker: { label: 'Awaiting Worker', color: 'text-amber-600' },
  queued: { label: 'Queued', color: 'text-blue-600' },
  rendering: { label: 'Rendering', color: 'text-primary' },
  processing_annotations: {
    label: 'Processing Annotations',
    color: 'text-primary',
  },
  complete: { label: 'Complete', color: 'text-emerald-600' },
  failed: { label: 'Failed', color: 'text-destructive' },
  cancelled: { label: 'Cancelled', color: 'text-muted-foreground' },
}
