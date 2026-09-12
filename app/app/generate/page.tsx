'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import dynamic from 'next/dynamic'
import { AppTopBar } from '@/components/app/topbar'
import {
  ChevronDown,
  ChevronUp,
  CircleAlert,
  Info,
  Loader2,
  Plus,
  RotateCcw,
  Trash2,
  Upload,
  Zap,
} from 'lucide-react'
import { apiRequest, createIdempotencyKey } from '@/lib/api/client'
import { ANNOTATION_FORMATS } from '@/lib/types'
import { VIEWPORT_ENVIRONMENTS } from '@/lib/viewport/environments'
import {
  DEFECT_CATALOGUE,
  createDefectLayer,
  defectsForPart,
  getDefectType,
  type DefectLayer,
} from '@/lib/viewport/defects'
import { describePlan, planAngles } from '@/lib/viewport/angle-planner'
import {
  BUNDLED_TURBINE_URL,
  TURBINE_PART_ORDER,
  type LoadedTurbineModel,
  type TurbinePartId,
} from '@/lib/viewport/turbine-model'
import {
  DEFAULT_VIEWPORT_CAMERA,
  DEFAULT_VIEWPORT_SETTINGS,
  type ViewportCamera,
  type ViewportSettings,
} from '@/components/viewport/blade-viewport'
import {
  DEFAULT_PAINT_SETTINGS,
  PAINT_COLORS,
  StrokeHistory,
  buildDocumentFromPalette,
  defaultColorAssignments,
  defectLayersFromPalette,
  getPaintColor,
  hashUvLayout,
  type BrushStroke,
  type ColorAssignments,
  type PaintColorId,
  type PaintSettings,
} from '@/lib/viewport/region-painting'

// WebGL cannot render on the server and the loaders are heavy, so the viewport is
// client-only and code-split out of the initial bundle.
const BladeViewport = dynamic(
  () => import('@/components/viewport/blade-viewport').then((m) => m.BladeViewport),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full w-full items-center justify-center bg-[#0e1117]">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading 3D viewport…
        </div>
      </div>
    ),
  },
)

// ── Capabilities reported by the backend ──────────────────────────────────────

interface RendererCapabilities {
  engine: 'legacy' | 'v2'
  backend: string
  description: string
  gpu_required: boolean
  relative_cost: number
  supported_defects: string[]
  unsupported_defects: string[]
  supports_environments: boolean
  supports_custom_models: boolean
  supports_region_painting: boolean
  supports_all_angles: boolean
  fallback: string
}

interface AssetImportCapabilities {
  model_formats: string[]
  environment_formats: string[]
  max_model_mb: number
  max_environment_mb: number
}

interface Capabilities {
  renderer: RendererCapabilities
  asset_import: AssetImportCapabilities
}

// ── Small building blocks ─────────────────────────────────────────────────────

function ConfigSection({
  title,
  badge,
  children,
  defaultOpen = true,
}: {
  title: string
  badge?: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-border">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground"
      >
        <span className="flex items-center gap-2">
          {title}
          {badge && (
            <span className="rounded-none border border-primary/40 bg-primary/10 px-1.5 py-0.5 text-[9px] font-medium normal-case tracking-normal text-primary">
              {badge}
            </span>
          )}
        </span>
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>
      {open && <div className="space-y-3 px-4 pb-4">{children}</div>}
    </div>
  )
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="mb-1 flex items-center gap-1">
        <label className="text-xs font-medium">{label}</label>
        {hint && (
          <div className="group relative">
            <Info className="h-3 w-3 cursor-help text-muted-foreground" />
            <div className="absolute left-full top-0 z-10 ml-1.5 hidden w-48 border border-border bg-popover p-2 text-[10px] text-muted-foreground group-hover:block">
              {hint}
            </div>
          </div>
        )}
      </div>
      {children}
    </div>
  )
}

function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  suffix = '',
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step?: number
  suffix?: string
  onChange: (value: number) => void
}) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground">{label}</span>
        <span className="font-mono text-[10px]">
          {Number.isInteger(value) ? value : value.toFixed(1)}
          {suffix}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-1 w-full accent-primary"
      />
    </div>
  )
}

// ── Scene hierarchy ───────────────────────────────────────────────────────────

function SceneHierarchy({
  model,
  settings,
  onSettingsChange,
  layers,
  environmentLabel,
}: {
  model: LoadedTurbineModel | null
  settings: ViewportSettings
  onSettingsChange: (settings: ViewportSettings) => void
  layers: DefectLayer[]
  environmentLabel: string
}) {
  return (
    <div className="flex h-full w-[210px] flex-shrink-0 flex-col overflow-hidden border-r border-border bg-card">
      <div className="flex-shrink-0 border-b border-border px-3 py-3">
        <h2 className="text-sm font-semibold">Scene</h2>
      </div>
      <div className="flex-1 overflow-y-auto py-1.5 text-xs">
        <div className="px-3 py-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          {model ? `${model.meshCount} meshes · ${model.sourceFormat}` : 'loading…'}
        </div>

        {(model?.parts ?? []).map((part) => (
          <button
            key={part.id}
            type="button"
            disabled={!part.present}
            title={part.present ? part.description : part.unavailableReason}
            onClick={() => onSettingsChange({ ...settings, selectedPartId: part.id })}
            className={`flex w-full items-center gap-1.5 px-3 py-1.5 text-left transition-colors ${
              part.present ? 'hover:bg-muted/40' : 'cursor-not-allowed opacity-40'
            } ${settings.selectedPartId === part.id ? 'bg-primary/10 text-primary' : ''} ${
              part.id === 'all' ? '' : 'pl-6'
            }`}
          >
            {part.displayName}
            {!part.present && (
              <span className="ml-auto font-mono text-[9px] text-muted-foreground">n/a</span>
            )}
          </button>
        ))}

        <div className="mt-2 border-t border-border pt-2">
          <div className="px-3 py-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            Defect layers
          </div>
          {layers.length === 0 ? (
            <p className="px-3 py-1.5 text-[10px] text-muted-foreground">None selected yet.</p>
          ) : (
            layers.map((layer) => (
              <div key={`${layer.defectId}-${layer.partId}`} className="flex items-center gap-1.5 px-3 py-1.5">
                <span
                  className="h-2.5 w-2.5 flex-shrink-0 border border-black/30"
                  style={{ backgroundColor: layer.colorHex }}
                />
                <span className="truncate">{getDefectType(layer.defectId)?.label}</span>
                <span className="ml-auto font-mono text-[9px] text-muted-foreground">
                  {layer.partId}
                </span>
              </div>
            ))
          )}
        </div>

        <div className="mt-2 border-t border-border pt-2">
          <div className="px-3 py-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            World
          </div>
          <div className="px-3 py-1.5 text-muted-foreground">
            Environment <span className="ml-1 text-foreground">{environmentLabel}</span>
          </div>
        </div>

        {model && model.warnings.length > 0 && (
          <div className="mt-2 border-t border-border px-3 pt-2">
            {model.warnings.map((warning) => (
              <p key={warning} className="py-1 text-[10px] text-amber-400">
                {warning}
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Defect layer editor ───────────────────────────────────────────────────────

function DefectLayerEditor({
  layer,
  supported,
  onChange,
  onRemove,
}: {
  layer: DefectLayer
  supported: boolean
  onChange: (layer: DefectLayer) => void
  onRemove: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const type = getDefectType(layer.defectId)
  if (!type) return null

  const patch = (values: Partial<DefectLayer>) => onChange({ ...layer, ...values })

  return (
    <div className="border border-border">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <span
          className="h-3 w-3 flex-shrink-0 border border-black/30"
          style={{ backgroundColor: layer.colorHex }}
        />
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex-1 truncate text-left text-xs"
        >
          {type.label}
        </button>
        <span className="font-mono text-[9px] text-muted-foreground">sev {layer.severity}</span>
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${type.label}`}
          className="text-muted-foreground hover:text-destructive"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>

      {!supported && (
        <p className="flex items-start gap-1 border-t border-amber-500/30 bg-amber-500/5 px-2 py-1.5 text-[10px] text-amber-400">
          <CircleAlert className="mt-0.5 h-3 w-3 flex-shrink-0" />
          The active renderer cannot produce this defect yet. It is saved with the job and
          will render once a v2 worker is available.
        </p>
      )}

      {expanded && (
        <div className="space-y-2 border-t border-border px-2 py-2">
          <Field label="Placed on">
            <select
              value={layer.partId}
              onChange={(event) => patch({ partId: event.target.value as TurbinePartId })}
              className="h-7 w-full border border-input bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            >
              {type.applicableParts.map((part) => (
                <option key={part} value={part}>
                  {part}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[10px] text-muted-foreground">{type.description}</p>
          </Field>

          <Slider
            label="Severity"
            value={layer.severity}
            min={0}
            max={100}
            onChange={(severity) => patch({ severity })}
          />
          <Slider
            label="Density / coverage"
            value={layer.coverage}
            min={1}
            max={100}
            suffix="%"
            onChange={(coverage) => patch({ coverage })}
          />
          <Slider
            label="Size"
            value={layer.sizeScale}
            min={0.1}
            max={5}
            step={0.1}
            suffix="×"
            onChange={(sizeScale) => patch({ sizeScale })}
          />
          <Slider
            label="Opacity"
            value={layer.opacity}
            min={1}
            max={100}
            suffix="%"
            onChange={(opacity) => patch({ opacity })}
          />
          <Slider
            label="Rotation"
            value={layer.rotationDeg}
            min={0}
            max={360}
            suffix="°"
            onChange={(rotationDeg) => patch({ rotationDeg })}
          />
          <Slider
            label="Spread"
            value={layer.spread}
            min={0}
            max={100}
            onChange={(spread) => patch({ spread })}
          />
          <Slider
            label="Randomness"
            value={layer.randomness}
            min={0}
            max={100}
            onChange={(randomness) => patch({ randomness })}
          />

          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">
              {type.colorIsMeaningful ? 'Stain colour' : 'Layer colour (region identifier)'}
            </span>
            <input
              type="color"
              value={layer.colorHex}
              onChange={(event) => patch({ colorHex: event.target.value })}
              className="h-6 w-10 cursor-pointer border border-input bg-background"
            />
          </div>
        </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function GeneratePage() {
  const router = useRouter()

  const [jobName, setJobName] = useState('')
  const [description, setDescription] = useState('')

  // The primary defect stays a dedicated field: every existing job, filter and dataset
  // name depends on it. Extra defects are added as layers on top.
  const [primaryDefect, setPrimaryDefect] = useState('leading_edge_erosion')
  const [severityMin, setSeverityMin] = useState(20)
  const [severityMax, setSeverityMax] = useState(80)
  const [layers, setLayers] = useState<DefectLayer[]>([])
  const [defectToAdd, setDefectToAdd] = useState('')

  const [imageCount, setImageCount] = useState(10)
  const [annotationFormat, setAnnotationFormat] = useState('coco_json')
  const [datasetName, setDatasetName] = useState('')
  const [cropPolicy, setCropPolicy] = useState<'full_frame' | 'defect_crop' | 'full_and_crop'>(
    'defect_crop',
  )
  const [cropPadding, setCropPadding] = useState(18)

  const [viewport, setViewport] = useState<ViewportSettings>(DEFAULT_VIEWPORT_SETTINGS)
  const [camera, setCamera] = useState<ViewportCamera>(DEFAULT_VIEWPORT_CAMERA)
  const [model, setModel] = useState<LoadedTurbineModel | null>(null)
  const [pinCamera, setPinCamera] = useState(false)
  const [generateAllAngles, setGenerateAllAngles] = useState(false)

  const [paint, setPaint] = useState<PaintSettings>(DEFAULT_PAINT_SETTINGS)
  const [paintStrokes, setPaintStrokes] = useState<BrushStroke[]>([])
  const [colorAssignments, setColorAssignments] = useState<ColorAssignments>(defaultColorAssignments)
  const strokeHistory = useRef(new StrokeHistory())
  const [uvChecksum, setUvChecksum] = useState('turbine-default')

  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
  const [uploading, setUploading] = useState<'model' | 'environment' | null>(null)
  const [modelUploadError, setModelUploadError] = useState<string | null>(null)
  const [environmentUploadError, setEnvironmentUploadError] = useState<string | null>(null)
  const modelInputRef = useRef<HTMLInputElement>(null)

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiRequest<Capabilities>('/v1/capabilities')
      .then(setCapabilities)
      .catch(() => setCapabilities(null))
  }, [])

  const environment = useMemo(
    () =>
      VIEWPORT_ENVIRONMENTS.find((entry) => entry.id === viewport.environmentId) ??
      VIEWPORT_ENVIRONMENTS[0],
    [viewport.environmentId],
  )

  const environmentGroups = useMemo(() => {
    const groups = new Map<string, typeof VIEWPORT_ENVIRONMENTS>()
    for (const entry of VIEWPORT_ENVIRONMENTS) {
      const existing = groups.get(entry.group) ?? []
      existing.push(entry)
      groups.set(entry.group, existing)
    }
    return [...groups.entries()]
  }, [])

  const selectedPart = model?.parts.find((part) => part.id === viewport.selectedPartId)
  const addableDefects = useMemo(() => {
    const chosen = new Set([primaryDefect, ...layers.map((layer) => layer.defectId)])
    return defectsForPart(viewport.selectedPartId).filter((entry) => !chosen.has(entry.id))
  }, [layers, primaryDefect, viewport.selectedPartId])

  const primaryDefectOptions = useMemo(
    () => defectsForPart(viewport.selectedPartId),
    [viewport.selectedPartId],
  )

  const renderer = capabilities?.renderer
  const isSupported = useCallback(
    (defectId: string) => {
      // When the API is unreachable, assume the v2 catalogue — the worker decides.
      if (!renderer) return true
      return renderer.supported_defects.includes(defectId) || renderer.engine === 'v2'
    },
    [renderer],
  )

  const anglePlan = useMemo(() => {
    if (!generateAllAngles) return []
    return planAngles({
      imageCount,
      baseDistanceM: camera.distanceM,
      targetHeightM: camera.targetHeightM,
    })
  }, [generateAllAngles, imageCount, camera.distanceM, camera.targetHeightM])

  const paintDefectOptions = useMemo(
    () => defectsForPart(viewport.selectedPartId),
    [viewport.selectedPartId],
  )

  const assignColor = useCallback((colorId: PaintColorId, defectId: string | null) => {
    setColorAssignments((current) => ({ ...current, [colorId]: defectId }))
  }, [])

  const selectPaintColor = useCallback(
    (colorId: PaintColorId) => {
      setPaint((current) => ({ ...current, activeColorId: colorId, enabled: true }))
      setViewport((current) =>
        current.useOriginalMaterials ? { ...current, useOriginalMaterials: false } : current,
      )
      setColorAssignments((current) => {
        if (current[colorId]) return current
        const suggested = getPaintColor(colorId).suggestedDefectId
        return { ...current, [colorId]: suggested }
      })
    },
    [],
  )

  const handleModelLoaded = useCallback((loaded: LoadedTurbineModel | null) => {
    setModel(loaded)
    if (!loaded) return
    const height = loaded.bounds.max[2] - loaded.bounds.min[2]
    setCamera((current) => ({
      ...current,
      targetHeightM: height * 0.66,
      distanceM: Math.max(40, loaded.bounds.radiusM * 2.4),
    }))
    // Sample a few UV corners from the first mesh so a later model swap can be rejected.
    const samples: Array<[number, number]> = []
    loaded.object.traverse((child) => {
      const mesh = child as import('three').Mesh
      if (!mesh.isMesh || !mesh.geometry?.attributes?.uv) return
      const uv = mesh.geometry.attributes.uv
      for (let i = 0; i < Math.min(32, uv.count); i += 1) {
        samples.push([uv.getX(i), uv.getY(i)])
      }
    })
    setUvChecksum(hashUvLayout(samples.length > 0 ? samples : [[0, 0], [1, 1]]))
  }, [])

  const handlePaintStroke = useCallback((stroke: BrushStroke) => {
    strokeHistory.current.push(stroke)
    setPaintStrokes([...strokeHistory.current.list])
  }, [])

  async function uploadAsset(kind: 'model' | 'environment', file: File) {
    setUploading(kind)
    if (kind === 'model') setModelUploadError(null)
    else setEnvironmentUploadError(null)
    try {
      const body = new FormData()
      body.append(kind, file)
      body.append('licence_confirmed', 'true')
      const result = await apiRequest<{ key: string; url: string; filename: string; format: string }>(
        kind === 'model' ? '/v1/assets/models' : '/v1/assets/environments',
        { method: 'POST', body },
      )
      setViewport((current) =>
        kind === 'model'
          ? { ...current, modelUrl: result.url }
          : { ...current, customHdriUrl: result.url },
      )
      return result.key
    } catch (uploadFailure) {
      const message =
        uploadFailure instanceof Error ? uploadFailure.message : 'The upload failed.'
      if (kind === 'model') setModelUploadError(message)
      else setEnvironmentUploadError(message)
      return null
    } finally {
      setUploading(null)
    }
  }

  const [modelAssetKey, setModelAssetKey] = useState<string | null>(null)
  const [hdriAssetKey, setHdriAssetKey] = useState<string | null>(null)
  const [modelAssetName, setModelAssetName] = useState<string | null>(null)
  const [hdriAssetName, setHdriAssetName] = useState<string | null>(null)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!jobName) {
      setError('Please give the job a name.')
      return
    }
    setSubmitting(true)
    setError(null)

    try {
      const generationPaintStrokes = paintStrokes.filter((stroke) => {
        if (viewport.selectedPartId === 'all') return true
        if (viewport.selectedPartId === 'rotor') {
          return stroke.surfacePartId === 'blades' || stroke.surfacePartId === 'hub'
        }
        return stroke.surfacePartId === viewport.selectedPartId
      })
      const generationPaintedLayers = defectLayersFromPalette({
        assignments: colorAssignments,
        strokes: generationPaintStrokes,
        partId: viewport.selectedPartId,
      })
      for (const paintedLayer of generationPaintedLayers) {
        const defect = getDefectType(paintedLayer.defectId)
        if (!defect?.applicableParts.includes(paintedLayer.partId as TurbinePartId)) {
          throw new Error(
            `${defect?.label ?? paintedLayer.defectId} cannot be placed on ${paintedLayer.partId}. ` +
              'Choose a physically valid defect for that painted colour.',
          )
        }
      }
      const job = await apiRequest<{ id: string }>('/v1/jobs', {
        method: 'POST',
        headers: { 'Idempotency-Key': createIdempotencyKey('job') },
        body: JSON.stringify({
          name: jobName,
          description: description || null,
          defect_type: primaryDefect,
          severity_min: severityMin,
          severity_max: severityMax,
          image_count: imageCount,
          annotation_format: annotationFormat,
          dataset_name: datasetName || jobName,
          config: {
            lighting_preset: 'overcast',
            camera_fov: Math.round(camera.fovDeg),
            weather: environment.precipitationMmH > 0 || (environment.snowIntensity ?? 0) > 0,
            image_width: 1024,
            image_height: 1024,
            compression_quality: 92,
            include_masks: true,
            environment_id: viewport.environmentId,
            weather_intensity: viewport.weatherIntensity,
            turbine_part_id: viewport.selectedPartId,
            crop_policy: cropPolicy,
            crop_padding_fraction: cropPadding / 100,
            generate_all_angles: generateAllAngles,
            camera_views: generateAllAngles
              ? anglePlan.map((angle) => ({
                  target_x_m: 0,
                  target_y_m: 0,
                  target_z_m: angle.targetHeightM,
                  azimuth_deg: angle.azimuthDeg,
                  elevation_deg: angle.elevationDeg,
                  distance_m: angle.distanceM,
                  roll_deg: 0,
                  fov_deg: camera.fovDeg,
                }))
              : [],
            model_asset_key: modelAssetKey,
            hdri_asset_key: hdriAssetKey,
            defect_layers: (() => {
              const painted = generationPaintedLayers
              const paintedIds = new Set(painted.map((entry) => entry.regionId))
              const fromPanel = layers
                .filter((layer) => !layer.regionId || !paintedIds.has(layer.regionId))
                .map((layer) => ({
                  defect_id: layer.defectId,
                  part_id: layer.partId,
                  severity: layer.severity,
                  coverage: layer.coverage,
                  size_scale: layer.sizeScale,
                  opacity: layer.opacity,
                  rotation_deg: layer.rotationDeg,
                  spread: layer.spread,
                  randomness: layer.randomness,
                  color_hex: layer.colorHex,
                  region_id: layer.regionId,
                }))
              const fromPaint = painted.map((entry) => {
                const type = getDefectType(entry.defectId)
                const panel = layers.find((layer) => layer.defectId === entry.defectId)
                return {
                  defect_id: entry.defectId,
                  part_id: entry.partId,
                  severity: panel?.severity ?? type?.defaultSeverity ?? 50,
                  coverage: panel?.coverage ?? type?.defaultCoverage ?? 25,
                  size_scale: panel?.sizeScale ?? 1,
                  opacity: panel?.opacity ?? 100,
                  rotation_deg: panel?.rotationDeg ?? 0,
                  spread: panel?.spread ?? 40,
                  randomness: panel?.randomness ?? 50,
                  color_hex: entry.colorHex,
                  region_id: entry.regionId,
                }
              })
              const combined = [...fromPaint, ...fromPanel]
              if (!combined.some((entry) => entry.defect_id === primaryDefect)) {
                const type = getDefectType(primaryDefect)
                if (type) {
                  const primary = createDefectLayer(type, viewport.selectedPartId)
                  combined.unshift({
                    defect_id: primaryDefect,
                    part_id: primary.partId,
                    severity: Math.round((severityMin + severityMax) / 2),
                    coverage: primary.coverage,
                    size_scale: primary.sizeScale,
                    opacity: primary.opacity,
                    rotation_deg: primary.rotationDeg,
                    spread: primary.spread,
                    randomness: primary.randomness,
                    color_hex: primary.colorHex,
                    region_id: null,
                  })
                }
              }
              return combined
            })(),
            region_document: buildDocumentFromPalette({
              name: `${jobName || 'job'}-regions`,
              modelId: 'BF_CUSTOMER_TURBINE',
              modelVersion: '1.0.0',
              uvChecksum,
              assignments: colorAssignments,
              strokes: generationPaintStrokes,
              severityForDefect: (defectId) => {
                const panel = layers.find((layer) => layer.defectId === defectId)
                const type = getDefectType(defectId)
                const severity = panel?.severity ?? type?.defaultSeverity ?? 50
                const coverage = (panel?.coverage ?? type?.defaultCoverage ?? 25) / 100
                return {
                  min: Math.max(1, severity - 15),
                  max: Math.min(100, severity + 15),
                  coverage,
                }
              },
            }),
            // The generate page explicitly records the production renderer so a job can
            // never fall back to the blade-only compatibility path.
            render_engine: 'v2',
            camera_view:
              pinCamera && !generateAllAngles
                ? {
                    target_x_m: 0,
                    target_y_m: 0,
                    target_z_m: camera.targetHeightM,
                    azimuth_deg: camera.azimuthDeg,
                    elevation_deg: camera.elevationDeg,
                    distance_m: camera.distanceM,
                    roll_deg: camera.rollDeg,
                    fov_deg: camera.fovDeg,
                  }
                : null,
          },
        }),
      })
      router.push(`/app/jobs/${job.id}`)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Job submission failed.')
      setSubmitting(false)
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <AppTopBar
        breadcrumbs={[{ label: 'Jobs', href: '/app/jobs' }, { label: 'New generation' }]}
      />

      <main className="flex-1 overflow-hidden">
        <form onSubmit={handleSubmit} className="flex h-full">
          <div className="hidden lg:flex">
            <SceneHierarchy
              model={model}
              settings={viewport}
              onSettingsChange={setViewport}
              layers={layers}
              environmentLabel={environment.label}
            />
          </div>

          <div className="min-w-0 flex-1 bg-[#0e1117]">
            <BladeViewport
              settings={viewport}
              onSettingsChange={setViewport}
              camera={camera}
              onCameraChange={setCamera}
              onModelLoaded={handleModelLoaded}
              paint={paint}
              paintStrokes={paintStrokes}
              onPaintStroke={handlePaintStroke}
              onPaintChange={setPaint}
            />
          </div>

          <div className="flex w-[300px] flex-shrink-0 flex-col overflow-hidden border-l border-border bg-card xl:w-[340px]">
            <div className="flex-shrink-0 border-b border-border px-4 py-3">
              <h2 className="text-sm font-semibold">Job configuration</h2>
            </div>

            <div className="flex-1 overflow-y-auto">
              <ConfigSection title="Job">
                <Field label="Job name">
                  <input
                    type="text"
                    value={jobName}
                    onChange={(event) => setJobName(event.target.value)}
                    placeholder="LEE batch #1"
                    required
                    className="h-8 w-full border border-input bg-background px-2.5 text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </Field>
                <Field label="Description (optional)">
                  <textarea
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="Purpose or notes…"
                    rows={2}
                    className="w-full resize-none border border-input bg-background px-2.5 py-1.5 text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </Field>
              </ConfigSection>

              {/* Model */}
              <ConfigSection title="Turbine model">
                <Field
                  label="Source"
                  hint="The bundled turbine, or your own FBX or OBJ. Uploaded models are private to your organization."
                >
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setViewport({ ...viewport, modelUrl: BUNDLED_TURBINE_URL })
                        setModelAssetKey(null)
                        setModelAssetName(null)
                        setModelUploadError(null)
                      }}
                      className={`flex h-9 items-center justify-center gap-1.5 border text-xs transition-colors ${
                        modelAssetKey === null
                          ? 'border-primary/60 bg-primary/10 text-primary'
                          : 'border-border hover:bg-muted/40'
                      }`}
                    >
                      <RotateCcw className="h-3 w-3" />
                      Use default
                    </button>
                    <button
                      type="button"
                      onClick={() => modelInputRef.current?.click()}
                      disabled={uploading !== null}
                      className="flex h-9 items-center justify-center gap-1.5 border border-border text-xs transition-colors hover:bg-muted/40 disabled:opacity-50"
                    >
                      {uploading === 'model' ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Upload className="h-3 w-3" />
                      )}
                      Upload
                    </button>
                  </div>
                  <input
                    ref={modelInputRef}
                    type="file"
                    accept=".fbx,.obj"
                    className="hidden"
                    onChange={async (event) => {
                      const file = event.target.files?.[0]
                      event.target.value = ''
                      if (!file) return
                      const key = await uploadAsset('model', file)
                      if (key) {
                        setModelAssetKey(key)
                        setModelAssetName(file.name)
                      }
                    }}
                  />
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    FBX or OBJ, up to {capabilities?.asset_import.max_model_mb ?? 96} MB. The
                    file is validated on its contents, not its extension.
                  </p>
                  <div className="mt-2 rounded-sm border border-border/70 bg-background/50 px-2 py-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[10px] text-muted-foreground">Active model</span>
                      <span className="truncate text-right text-[10px] font-medium">
                        {modelAssetName ?? 'BladeForge default turbine'}
                      </span>
                    </div>
                  </div>
                  {modelUploadError && (
                    <p className="mt-1 text-[10px] text-destructive">{modelUploadError}</p>
                  )}
                </Field>

                <Field
                  label="Part to render"
                  hint="Restricts both the render and the defect placement to one part of the turbine."
                >
                  <select
                    value={viewport.selectedPartId}
                    onChange={(event) => {
                      const selectedPartId = event.target.value as TurbinePartId
                      const validPrimaryDefects = defectsForPart(selectedPartId)
                      if (!validPrimaryDefects.some((entry) => entry.id === primaryDefect)) {
                        const replacement = validPrimaryDefects[0]
                        if (replacement) setPrimaryDefect(replacement.id)
                      }
                      setLayers((current) =>
                        current.filter((layer) => {
                          if (selectedPartId === 'all') return true
                          if (selectedPartId === 'rotor') {
                            return layer.partId === 'blades' || layer.partId === 'hub'
                          }
                          return layer.partId === selectedPartId
                        }),
                      )
                      setViewport({ ...viewport, selectedPartId })
                    }}
                    className="h-8 w-full appearance-none border border-input bg-background px-2.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    {TURBINE_PART_ORDER.map((partId) => {
                      const part = model?.parts.find((entry) => entry.id === partId)
                      return (
                        <option key={partId} value={partId} disabled={part ? !part.present : false}>
                          {part?.displayName ?? partId}
                          {part && !part.present ? ' — not in this model' : ''}
                        </option>
                      )
                    })}
                  </select>
                  {selectedPart && (
                    <p className="mt-1 text-[10px] text-muted-foreground">
                      {selectedPart.present
                        ? selectedPart.description
                        : selectedPart.unavailableReason}
                    </p>
                  )}
                </Field>
              </ConfigSection>

              {/* Defects */}
              <ConfigSection title="Defects" badge={`${layers.length + 1}`}>
                <div className="border border-border/60 bg-background/40 p-2">
                  <label className="text-[10px] font-medium" htmlFor="primary-defect">
                    Primary defect
                  </label>
                  <select
                    id="primary-defect"
                    value={primaryDefect}
                    onChange={(event) => {
                      const next = event.target.value
                      setPrimaryDefect(next)
                      setLayers((current) => current.filter((layer) => layer.defectId !== next))
                    }}
                    className="mt-1 h-8 w-full appearance-none border border-input bg-background px-2.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    {primaryDefectOptions.map((entry) => (
                      <option key={entry.id} value={entry.id}>
                        {entry.label}{isSupported(entry.id) ? '' : ' (renderer pending)'}
                      </option>
                    ))}
                  </select>
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    Always present and used as the dataset&apos;s primary label. Add more below.
                  </p>
                </div>

                <Field
                  label={`Severity range: ${severityMin}–${severityMax}`}
                  hint="Applies to the primary defect. 0 is barely visible, 100 is extreme."
                >
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <span className="w-6 text-[10px] text-muted-foreground">Min</span>
                      <input
                        type="range"
                        min={0}
                        max={severityMax - 5}
                        value={severityMin}
                        onChange={(event) => setSeverityMin(Number(event.target.value))}
                        className="h-1 flex-1 accent-primary"
                      />
                      <span className="w-6 text-right font-mono text-[10px]">{severityMin}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="w-6 text-[10px] text-muted-foreground">Max</span>
                      <input
                        type="range"
                        min={severityMin + 5}
                        max={100}
                        value={severityMax}
                        onChange={(event) => setSeverityMax(Number(event.target.value))}
                        className="h-1 flex-1 accent-primary"
                      />
                      <span className="w-6 text-right font-mono text-[10px]">{severityMax}</span>
                    </div>
                  </div>
                </Field>

                <Field
                  label="Additional defect layers"
                  hint="Each layer is placed on a part where that damage can physically occur. Corrosion, for example, is offered on metal parts only — rust-coloured marks on a composite blade are runoff staining, and labelling them as corrosion would teach a detector something untrue."
                >
                  <div className="flex gap-2">
                    <select
                      value={defectToAdd}
                      onChange={(event) => setDefectToAdd(event.target.value)}
                      className="h-8 flex-1 appearance-none border border-input bg-background px-2.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                    >
                      <option value="">Add a defect…</option>
                      {addableDefects.map((entry) => (
                        <option key={entry.id} value={entry.id}>
                          {entry.label}
                          {isSupported(entry.id) ? '' : ' (renderer pending)'}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      disabled={!defectToAdd}
                      onClick={() => {
                        const type = DEFECT_CATALOGUE.find((entry) => entry.id === defectToAdd)
                        if (!type) return
                        setLayers([...layers, createDefectLayer(type, viewport.selectedPartId)])
                        setDefectToAdd('')
                      }}
                      className="flex h-8 w-8 items-center justify-center border border-border transition-colors hover:bg-muted/40 disabled:opacity-40"
                      aria-label="Add defect layer"
                    >
                      <Plus className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </Field>

                <div className="space-y-1.5">
                  {layers.map((layer, index) => (
                    <DefectLayerEditor
                      key={`${layer.defectId}-${index}`}
                      layer={layer}
                      supported={isSupported(layer.defectId)}
                      onChange={(next) =>
                        setLayers(layers.map((entry, i) => (i === index ? next : entry)))
                      }
                      onRemove={() => setLayers(layers.filter((_, i) => i !== index))}
                    />
                  ))}
                </div>
              </ConfigSection>

              <ConfigSection title="Painted region" badge={paintStrokes.length ? `${paintStrokes.length}` : undefined}>
                <p className="text-[10px] text-muted-foreground">
                  Pick a colour, assign a defect, then paint that region on the turbine.
                  Reassigning a colour updates the defect for existing paint — no need to
                  repaint. Middle-drag still orbits while paint mode is on.
                </p>

                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      const next = !paint.enabled
                      setPaint({ ...paint, enabled: next })
                      if (next) {
                        setViewport((current) =>
                          current.useOriginalMaterials
                            ? { ...current, useOriginalMaterials: false }
                            : current,
                        )
                      }
                    }}
                    className={`h-8 flex-1 border text-xs transition-colors ${
                      paint.enabled
                        ? 'border-primary/60 bg-primary/10 text-primary'
                        : 'border-border hover:bg-muted/40'
                    }`}
                  >
                    {paint.enabled ? 'Painting… click to stop' : 'Enter paint mode'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setPaint({ ...paint, mode: paint.mode === 'paint' ? 'erase' : 'paint' })}
                    disabled={!paint.enabled}
                    className="h-8 flex-1 border border-border text-xs transition-colors hover:bg-muted/40 disabled:opacity-40"
                  >
                    {paint.mode === 'erase' ? 'Eraser' : 'Brush'}
                  </button>
                </div>

                <div className="grid grid-cols-5 gap-1.5">
                  {PAINT_COLORS.map((color) => {
                    const active = paint.activeColorId === color.id
                    const strokeCount = paintStrokes.filter((s) => s.regionId === color.id).length
                    return (
                      <button
                        key={color.id}
                        type="button"
                        title={`${color.label}${strokeCount ? ` · ${strokeCount} stroke${strokeCount === 1 ? '' : 's'}` : ''}`}
                        onClick={() => selectPaintColor(color.id)}
                        className={`flex h-10 flex-col items-center justify-center gap-0.5 border transition-colors ${
                          active
                            ? 'border-foreground ring-1 ring-foreground'
                            : 'border-border hover:border-foreground/40'
                        }`}
                        style={{ backgroundColor: color.hex }}
                      >
                        <span className="text-[9px] font-medium text-white drop-shadow-[0_1px_1px_rgba(0,0,0,0.8)]">
                          {color.label}
                        </span>
                      </button>
                    )
                  })}
                </div>

                <Field label={`Defect for ${getPaintColor(paint.activeColorId).label}`}>
                  <select
                    value={colorAssignments[paint.activeColorId] ?? ''}
                    onChange={(event) =>
                      assignColor(paint.activeColorId, event.target.value || null)
                    }
                    className="h-8 w-full appearance-none border border-input bg-background px-2.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    <option value="">Unassigned</option>
                    {paintDefectOptions.map((defect) => (
                      <option key={defect.id} value={defect.id}>
                        {defect.label}
                      </option>
                    ))}
                  </select>
                </Field>

                <Slider
                  label="Brush size"
                  value={Math.round(paint.brushRadiusUv * 1000)}
                  min={5}
                  max={120}
                  onChange={(value) => setPaint({ ...paint, brushRadiusUv: value / 1000 })}
                />
                <Slider
                  label="Overlay opacity"
                  value={Math.round(paint.overlayOpacity * 100)}
                  min={10}
                  max={100}
                  suffix="%"
                  onChange={(value) => setPaint({ ...paint, overlayOpacity: value / 100 })}
                />

                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={paintStrokes.length === 0}
                    onClick={() => {
                      strokeHistory.current.undo()
                      setPaintStrokes([...strokeHistory.current.list])
                    }}
                    className="h-7 flex-1 border border-border text-[10px] hover:bg-muted/40 disabled:opacity-40"
                  >
                    Undo
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const redone = strokeHistory.current.redo()
                      if (redone) setPaintStrokes([...strokeHistory.current.list])
                    }}
                    className="h-7 flex-1 border border-border text-[10px] hover:bg-muted/40"
                  >
                    Redo
                  </button>
                  <button
                    type="button"
                    disabled={
                      !paintStrokes.some((stroke) => stroke.regionId === paint.activeColorId)
                    }
                    onClick={() => {
                      strokeHistory.current.clearColor(paint.activeColorId)
                      setPaintStrokes([...strokeHistory.current.list])
                    }}
                    className="h-7 flex-1 border border-border text-[10px] hover:bg-muted/40 disabled:opacity-40"
                  >
                    Clear colour
                  </button>
                  <button
                    type="button"
                    disabled={paintStrokes.length === 0}
                    onClick={() => {
                      strokeHistory.current.clear()
                      setPaintStrokes([])
                    }}
                    className="h-7 flex-1 border border-border text-[10px] text-destructive hover:bg-muted/40 disabled:opacity-40"
                  >
                    Clear all
                  </button>
                </div>

                <div className="space-y-1 border border-border/60 bg-background/40 p-2">
                  {PAINT_COLORS.map((color) => {
                    const defectId = colorAssignments[color.id]
                    const defect = defectId ? getDefectType(defectId) : null
                    const count = paintStrokes.filter((s) => s.regionId === color.id).length
                    return (
                      <div key={color.id} className="flex items-center gap-2">
                        <span
                          className="h-2.5 w-2.5 shrink-0 border border-black/20"
                          style={{ backgroundColor: color.hex }}
                        />
                        <span className="w-10 shrink-0 text-[10px]">{color.label}</span>
                        <span className="flex-1 truncate text-[10px] text-muted-foreground">
                          {defect?.label ?? 'Unassigned'}
                        </span>
                        <span className="font-mono text-[9px] text-muted-foreground">
                          {count === 0 ? '—' : `${count}`}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </ConfigSection>

              {/* Environment */}
              <ConfigSection title="Environment & weather">
                <Field
                  label="Environment preset"
                  hint="Each preset is a genuinely different scene. Captured presets use a real HDRI for both the backdrop and the lighting."
                >
                  <select
                    value={viewport.environmentId}
                    onChange={(event) =>
                      setViewport({ ...viewport, environmentId: event.target.value })
                    }
                    className="h-8 w-full appearance-none border border-input bg-background px-2.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    {environmentGroups.map(([group, entries]) => (
                      <optgroup key={group} label={group}>
                        {entries.map((entry) => (
                          <option key={entry.id} value={entry.id}>
                            {entry.label}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                  <p className="mt-1 text-[10px] text-muted-foreground">{environment.summary}</p>
                  {environment.hdriCredit && (
                    <p className="mt-1 text-[10px] text-muted-foreground/70">
                      {environment.hdriCredit}
                    </p>
                  )}
                </Field>

                <Field
                  label="Upload an HDRI"
                  hint="A 32-bit equirectangular EXR or Radiance HDR. Validated on its magic bytes and stored privately."
                >
                  <label className="flex h-8 cursor-pointer items-center justify-center gap-1.5 border border-border text-xs transition-colors hover:bg-muted/40">
                    {uploading === 'environment' ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Upload className="h-3 w-3" />
                    )}
                    {hdriAssetKey ? 'Replace uploaded HDRI' : 'Upload EXR or HDR'}
                    <input
                      type="file"
                      accept=".exr,.hdr"
                      className="hidden"
                      onChange={async (event) => {
                        const file = event.target.files?.[0]
                        event.target.value = ''
                        if (!file) return
                        const key = await uploadAsset('environment', file)
                        if (key) {
                          setHdriAssetKey(key)
                          setHdriAssetName(file.name)
                        }
                      }}
                    />
                  </label>
                  {hdriAssetKey && (
                    <div className="mt-1 flex items-start justify-between gap-2">
                      <p className="text-[10px] text-muted-foreground">
                        {hdriAssetName ?? 'Your map'} is lighting the preview now. The preset above still
                        controls weather, wetness and sun direction.
                      </p>
                      <button
                        type="button"
                        onClick={() => {
                          setHdriAssetKey(null)
                          setHdriAssetName(null)
                          setViewport((current) => ({ ...current, customHdriUrl: null }))
                        }}
                        className="flex-shrink-0 text-[10px] text-destructive hover:underline"
                      >
                        Restore default
                      </button>
                    </div>
                  )}
                  {environmentUploadError && (
                    <p className="mt-1 text-[10px] text-destructive">
                      {environmentUploadError}
                    </p>
                  )}
                </Field>

                <Field
                  label={`Weather intensity: ${Math.round(viewport.weatherIntensity * 100)}%`}
                  hint="One control for how harsh the conditions get. The technical parameters stay inside the validated preset."
                >
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={Math.round(viewport.weatherIntensity * 100)}
                    onChange={(event) =>
                      setViewport({
                        ...viewport,
                        weatherIntensity: Number(event.target.value) / 100,
                      })
                    }
                    className="h-1 w-full accent-primary"
                  />
                  <div className="mt-1 flex justify-between font-mono text-[10px] text-muted-foreground">
                    <span>mild</span>
                    <span>extreme</span>
                  </div>
                </Field>

                <dl className="space-y-1 border border-border/60 bg-background/40 p-2">
                  {[
                    ['Sun elevation', `${environment.sunElevationDeg.toFixed(0)}°`],
                    ['Cloud cover', `${Math.round(environment.cloudCover * 100)}%`],
                    [
                      'Rainfall',
                      environment.precipitationMmH > 0
                        ? `${environment.precipitationMmH.toFixed(1)} mm/h`
                        : 'none',
                    ],
                    [
                      'Snowfall',
                      (environment.snowIntensity ?? 0) > 0
                        ? `${Math.round((environment.snowIntensity ?? 0) * 100)}%`
                        : 'none',
                    ],
                    ['Surface wetness', `${Math.round(environment.wetness * 100)}%`],
                    [
                      'Visibility',
                      environment.visibilityM >= 1000
                        ? `${(environment.visibilityM / 1000).toFixed(1)} km`
                        : `${environment.visibilityM} m`,
                    ],
                  ].map(([label, value]) => (
                    <div key={label} className="flex justify-between gap-2">
                      <dt className="text-[10px] text-muted-foreground">{label}</dt>
                      <dd className="font-mono text-[10px]">{value}</dd>
                    </div>
                  ))}
                </dl>
              </ConfigSection>

              {/* Camera */}
              <ConfigSection title="Camera & sensor">
                <p className="text-[10px] text-muted-foreground">
                  Every control here moves the viewport camera immediately. What you see is
                  the angle that will be rendered.
                </p>

                <Slider
                  label="Field of view"
                  value={Math.round(camera.fovDeg)}
                  min={5}
                  max={120}
                  suffix="°"
                  onChange={(fovDeg) => setCamera({ ...camera, fovDeg })}
                />
                <Slider
                  label="Distance"
                  value={Math.round(camera.distanceM)}
                  min={2}
                  max={Math.max(400, Math.round((model?.bounds.radiusM ?? 150) * 6))}
                  suffix=" m"
                  onChange={(distanceM) => setCamera({ ...camera, distanceM })}
                />
                <Slider
                  label="Target height"
                  value={Math.round(camera.targetHeightM)}
                  min={0}
                  max={Math.max(50, Math.round(model ? model.bounds.max[2] : 150))}
                  suffix=" m"
                  onChange={(targetHeightM) => setCamera({ ...camera, targetHeightM })}
                />
                <Slider
                  label="Yaw (azimuth)"
                  value={Math.round(camera.azimuthDeg)}
                  min={-180}
                  max={180}
                  suffix="°"
                  onChange={(azimuthDeg) => setCamera({ ...camera, azimuthDeg })}
                />
                <Slider
                  label="Pitch (elevation)"
                  value={Math.round(camera.elevationDeg)}
                  min={-89}
                  max={89}
                  suffix="°"
                  onChange={(elevationDeg) => setCamera({ ...camera, elevationDeg })}
                />
                <Slider
                  label="Roll"
                  value={Math.round(camera.rollDeg)}
                  min={-180}
                  max={180}
                  suffix="°"
                  onChange={(rollDeg) => setCamera({ ...camera, rollDeg })}
                />

                <label className="flex cursor-pointer items-start gap-2 border border-border p-2">
                  <input
                    type="checkbox"
                    checked={generateAllAngles}
                    onChange={(event) => {
                      setGenerateAllAngles(event.target.checked)
                      if (event.target.checked) setPinCamera(false)
                    }}
                    className="mt-0.5 accent-primary"
                  />
                  <span>
                    <span className="block text-xs">Generate all angles</span>
                    <span className="block text-[10px] text-muted-foreground">
                      Spread the image count over distinct viewpoints around the selected
                      part instead of reusing one pose.
                    </span>
                  </span>
                </label>

                {generateAllAngles && (
                  <div className="border border-border/60 bg-background/40 p-2">
                    <p className="font-mono text-[10px] text-muted-foreground">
                      {describePlan(anglePlan)}
                    </p>
                    <ul className="mt-1.5 max-h-32 space-y-0.5 overflow-y-auto">
                      {anglePlan.slice(0, 24).map((angle) => (
                        <li
                          key={angle.index}
                          className="flex justify-between gap-2 font-mono text-[10px]"
                        >
                          <span className="truncate text-muted-foreground">{angle.label}</span>
                          <span>
                            {angle.azimuthDeg.toFixed(0)}°/{angle.elevationDeg.toFixed(0)}°
                          </span>
                        </li>
                      ))}
                      {anglePlan.length > 24 && (
                        <li className="text-[10px] text-muted-foreground">
                          …and {anglePlan.length - 24} more
                        </li>
                      )}
                    </ul>
                  </div>
                )}

                {!generateAllAngles && (
                  <label className="flex cursor-pointer items-start gap-2 border border-border p-2">
                    <input
                      type="checkbox"
                      checked={pinCamera}
                      onChange={(event) => setPinCamera(event.target.checked)}
                      className="mt-0.5 accent-primary"
                    />
                    <span>
                      <span className="block text-xs">Pin this exact angle</span>
                      <span className="block text-[10px] text-muted-foreground">
                        Every image uses the pose shown above. Leave off to sample angles
                        across the allowed range for variety.
                      </span>
                    </span>
                  </label>
                )}
              </ConfigSection>

              {/* Output */}
              <ConfigSection title="Output">
                <Field label="Image count" hint="Number of images to render in this batch.">
                  <div className="flex items-center gap-2">
                    <input
                      type="range"
                      min={1}
                      max={10000}
                      value={imageCount}
                      onChange={(event) => setImageCount(Number(event.target.value))}
                      className="h-1 flex-1 accent-primary"
                    />
                    <input
                      type="number"
                      min={1}
                      max={10000}
                      value={imageCount}
                      onChange={(event) => setImageCount(Number(event.target.value))}
                      className="h-8 w-16 border border-input bg-background px-2 text-right font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                  </div>
                </Field>

                <Field label="Annotation format">
                  <select
                    value={annotationFormat}
                    onChange={(event) => setAnnotationFormat(event.target.value)}
                    className="h-8 w-full appearance-none border border-input bg-background px-2.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    {ANNOTATION_FORMATS.map((format) => (
                      <option key={format.value} value={format.value}>
                        {format.label}
                      </option>
                    ))}
                  </select>
                </Field>

                <Field
                  label="What to extract"
                  hint="Whole frames show the defect in context. Crops zoom tightly on the damage. Both gives you each sample twice."
                >
                  <div className="space-y-1">
                    {[
                      {
                        value: 'full_frame' as const,
                        label: 'Whole frame',
                        detail: 'One full view per sample.',
                      },
                      {
                        value: 'defect_crop' as const,
                        label: 'Damaged area only',
                        detail: 'Tight crop around each defect.',
                      },
                      {
                        value: 'full_and_crop' as const,
                        label: 'Both',
                        detail: 'Full frame plus a matching crop.',
                      },
                    ].map((option) => (
                      <label
                        key={option.value}
                        className={`flex cursor-pointer items-start gap-2 border p-2 transition-colors ${
                          cropPolicy === option.value
                            ? 'border-primary/60 bg-primary/5'
                            : 'border-border hover:bg-muted/30'
                        }`}
                      >
                        <input
                          type="radio"
                          name="crop-policy"
                          value={option.value}
                          checked={cropPolicy === option.value}
                          onChange={() => setCropPolicy(option.value)}
                          className="mt-0.5 accent-primary"
                        />
                        <span>
                          <span className="block text-xs">{option.label}</span>
                          <span className="block text-[10px] text-muted-foreground">
                            {option.detail}
                          </span>
                        </span>
                      </label>
                    ))}
                  </div>
                </Field>

                {cropPolicy !== 'full_frame' && (
                  <Field
                    label={`Crop padding: ${cropPadding}%`}
                    hint="Margin kept around the defect bounding box, so the crop includes surrounding surface."
                  >
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={cropPadding}
                      onChange={(event) => setCropPadding(Number(event.target.value))}
                      className="h-1 w-full accent-primary"
                    />
                  </Field>
                )}

                <Field label="Dataset name" hint="The name shown in your Datasets library.">
                  <input
                    type="text"
                    value={datasetName}
                    onChange={(event) => setDatasetName(event.target.value)}
                    placeholder={jobName || 'Dataset name…'}
                    className="h-8 w-full border border-input bg-background px-2.5 text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </Field>
              </ConfigSection>

              {/* Renderer status — replaces the old, unexplained compatibility box */}
              <ConfigSection
                title="Renderer"
                badge={renderer ? renderer.engine : undefined}
                defaultOpen={false}
              >
                {!renderer ? (
                  <p className="text-[10px] text-muted-foreground">
                    Could not reach the API, so renderer capabilities are unknown. Controls
                    stay enabled and the backend validates your selections on submit.
                  </p>
                ) : (
                  <>
                    <dl className="space-y-1 border border-border/60 bg-background/40 p-2">
                      {[
                        ['Backend', renderer.backend],
                        ['Hardware', renderer.gpu_required ? 'GPU required' : 'CPU or GPU'],
                        ['Relative cost', `${renderer.relative_cost.toFixed(1)}× baseline`],
                      ].map(([label, value]) => (
                        <div key={label} className="flex justify-between gap-2">
                          <dt className="text-[10px] text-muted-foreground">{label}</dt>
                          <dd className="text-right font-mono text-[10px]">{value}</dd>
                        </div>
                      ))}
                    </dl>
                    <p className="text-[10px] text-muted-foreground">{renderer.description}</p>

                    <div>
                      <p className="mb-1 text-[10px] font-medium text-emerald-400">
                        Renders today
                      </p>
                      <p className="text-[10px] text-muted-foreground">
                        {renderer.supported_defects
                          .map((id) => getDefectType(id)?.label ?? id)
                          .join(', ')}
                        {renderer.supports_environments
                          ? '. Environments, weather and camera pose are applied.'
                          : '. Environment, weather, camera pose and part selection are recorded but not applied.'}
                      </p>
                    </div>

                    {renderer.unsupported_defects.length > 0 && (
                      <div>
                        <p className="mb-1 text-[10px] font-medium text-amber-400">
                          Not yet rendered
                        </p>
                        <p className="text-[10px] text-muted-foreground">
                          {renderer.unsupported_defects
                            .map((id) => getDefectType(id)?.label ?? id)
                            .join(', ')}
                        </p>
                      </div>
                    )}

                    <div>
                      <p className="mb-1 text-[10px] font-medium">Fallback behaviour</p>
                      <p className="text-[10px] text-muted-foreground">{renderer.fallback}</p>
                    </div>
                  </>
                )}
              </ConfigSection>
            </div>

            <div className="flex-shrink-0 border-t border-border p-4">
              {error && (
                <div className="mb-3 border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                  {error}
                </div>
              )}
              <button
                type="submit"
                disabled={submitting || !jobName}
                className="flex h-9 w-full items-center justify-center gap-2 bg-primary text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                <Zap className="h-4 w-4" />
                {submitting ? 'Submitting…' : 'Submit job'}
              </button>
              <p className="mt-2 text-center text-[10px] text-muted-foreground">
                Jobs wait for a healthy worker before entering the render queue.
              </p>
            </div>
          </div>
        </form>
      </main>
    </div>
  )
}
