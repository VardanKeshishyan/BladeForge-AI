/**
 * Fixed five-colour region palette.
 *
 * Colours are the stable identity of a painted region. A defect is *assigned* to a
 * colour, and can be reassigned later without losing the strokes — the paint stays on
 * the colour, the job config reads whichever defect is currently bound to it.
 *
 * Black and white are deliberately excluded: black reads as a broken material on a
 * white turbine, and white is invisible against the clean coating.
 */

export const STROKE_SCHEMA_VERSION = '4.0.0'
export const DEFAULT_MASK_WIDTH = 1024
export const DEFAULT_MASK_HEIGHT = 512

export type StrokeMode = 'paint' | 'erase'

export type PaintColorId = 'red' | 'blue' | 'green' | 'yellow' | 'brown'

export interface PaintColor {
  id: PaintColorId
  hex: string
  label: string
  /** Suggested first defect for this colour, so a new user has somewhere to start. */
  suggestedDefectId: string
}

export const PAINT_COLORS: PaintColor[] = [
  {
    id: 'red',
    hex: '#e11d48',
    label: 'Red',
    suggestedDefectId: 'lightning_strike',
  },
  {
    id: 'blue',
    hex: '#2563eb',
    label: 'Blue',
    suggestedDefectId: 'delamination',
  },
  {
    id: 'green',
    hex: '#16a34a',
    label: 'Green',
    suggestedDefectId: 'leading_edge_erosion',
  },
  {
    id: 'yellow',
    hex: '#ca8a04',
    label: 'Yellow',
    suggestedDefectId: 'coating_loss',
  },
  {
    id: 'brown',
    hex: '#a16207',
    label: 'Brown',
    suggestedDefectId: 'rust_staining',
  },
]

export function getPaintColor(id: PaintColorId): PaintColor {
  return PAINT_COLORS.find((entry) => entry.id === id) ?? PAINT_COLORS[0]
}

/** Colour → defect assignment. Null means the colour is unused. */
export type ColorAssignments = Record<PaintColorId, string | null>

export function defaultColorAssignments(): ColorAssignments {
  return {
    red: null,
    blue: null,
    green: 'leading_edge_erosion',
    yellow: null,
    brown: null,
  }
}

export interface BrushStroke {
  /** Always a palette colour id — never a defect id. */
  regionId: PaintColorId
  mode: StrokeMode
  radiusUv: number
  points: Array<[number, number]>
  /** Stable semantic identity of the exact mesh that received this gesture. */
  surfaceId: string
  /** Classified turbine part containing the surface (for renderer mapping/debugging). */
  surfacePartId: string
  /** Triangle hit for each sampled point. Prevents overlap on repeated UV islands. */
  faceIndices: number[]
  /** Object-local samples allow a renderer to reproject onto the imported model. */
  localPoints: Array<[number, number, number]>
  localNormals: Array<[number, number, number]>
  /** Normalized scene coordinates remain stable when FBX/OBJ importers bake transforms differently. */
  worldPoints: Array<[number, number, number]>
  worldNormals: Array<[number, number, number]>
}

export interface PaintSettings {
  enabled: boolean
  mode: StrokeMode
  brushRadiusUv: number
  overlayOpacity: number
  activeColorId: PaintColorId
}

export const DEFAULT_PAINT_SETTINGS: PaintSettings = {
  enabled: false,
  mode: 'paint',
  brushRadiusUv: 0.04,
  overlayOpacity: 0.7,
  activeColorId: 'green',
}

export interface RegionLayerSpec {
  regionId: string
  layerIndex: number
  displayName: string
  colorKey: string
  hexColor: string
  defectProfileId: string
  defectProfileVersion: string
  severityMin: number
  severityMax: number
  coverageTarget: number
}

interface RegionLayerPayload {
  region_id: string
  layer_index: number
  display_name: string
  color_key: string
  hex_color: string
  defect_profile_id: string
  defect_profile_version: string
  severity_min: number
  severity_max: number
  coverage_target: number
}

export interface RegionStrokeDocument {
  name: string
  blade_model_id: string
  blade_model_version: string
  uv_set_name: string
  uv_layout_checksum: string
  mask_width: number
  mask_height: number
  layers: RegionLayerPayload[]
  strokes: Array<{
    region_id: PaintColorId
    mode: StrokeMode
    radius_uv: number
    points: Array<[number, number]>
    surface_id: string
    surface_part_id: string
    face_indices: number[]
    local_points: Array<[number, number, number]>
    local_normals: Array<[number, number, number]>
    world_points: Array<[number, number, number]>
    world_normals: Array<[number, number, number]>
  }>
  schema_version: string
}

/**
 * Build the job payload from strokes + the current colour→defect mapping.
 *
 * Reassigning a colour to a different defect regenerates the layers without touching
 * the strokes, which is how a customer can change their mind after painting.
 */
export function buildDocumentFromPalette(input: {
  name: string
  modelId: string
  modelVersion: string
  uvChecksum: string
  assignments: ColorAssignments
  strokes: readonly BrushStroke[]
  severityForDefect?: (defectId: string) => { min: number; max: number; coverage: number }
}): RegionStrokeDocument | null {
  const usedColors = PAINT_COLORS.filter((color) => {
    const defectId = input.assignments[color.id]
    if (!defectId) return false
    return input.strokes.some((stroke) => stroke.regionId === color.id)
  })
  if (usedColors.length === 0) return null

  const layers: RegionLayerSpec[] = usedColors.map((color, index) => {
    const defectId = input.assignments[color.id]!
    const severity = input.severityForDefect?.(defectId) ?? { min: 20, max: 60, coverage: 0.2 }
    return {
      regionId: color.id,
      layerIndex: index + 1,
      displayName: color.label,
      colorKey: color.id,
      hexColor: color.hex,
      defectProfileId: defectId.toUpperCase(),
      defectProfileVersion: '1.0.0',
      severityMin: severity.min,
      severityMax: severity.max,
      coverageTarget: Math.max(0.01, Math.min(1, severity.coverage)),
    }
  })

  const allowed = new Set(layers.map((layer) => layer.regionId))
  const strokes = input.strokes
    .filter((stroke) => allowed.has(stroke.regionId))
    .map((stroke) => ({
      region_id: stroke.regionId,
      mode: stroke.mode,
      radius_uv: stroke.radiusUv,
      points: stroke.points,
      surface_id: stroke.surfaceId,
      surface_part_id: stroke.surfacePartId,
      face_indices: stroke.faceIndices,
      local_points: stroke.localPoints,
      local_normals: stroke.localNormals,
      world_points: stroke.worldPoints,
      world_normals: stroke.worldNormals,
    }))

  return {
    name: input.name,
    blade_model_id: input.modelId,
    blade_model_version: input.modelVersion,
    uv_set_name: 'UVMap',
    uv_layout_checksum: input.uvChecksum,
    mask_width: DEFAULT_MASK_WIDTH,
    mask_height: DEFAULT_MASK_HEIGHT,
    layers: layers.map((layer) => ({
      region_id: layer.regionId,
      layer_index: layer.layerIndex,
      display_name: layer.displayName,
      color_key: layer.colorKey,
      hex_color: layer.hexColor,
      defect_profile_id: layer.defectProfileId,
      defect_profile_version: layer.defectProfileVersion,
      severity_min: layer.severityMin,
      severity_max: layer.severityMax,
      coverage_target: layer.coverageTarget,
    })),
    strokes,
    schema_version: STROKE_SCHEMA_VERSION,
  }
}

/**
 * Defect layers for the job config, derived from painted colours that have an assignment.
 * One layer per colour that was actually painted.
 */
export function defectLayersFromPalette(input: {
  assignments: ColorAssignments
  strokes: readonly BrushStroke[]
  partId: string
}): Array<{
  defectId: string
  partId: string
  colorHex: string
  regionId: string
}> {
  const result: Array<{
    defectId: string
    partId: string
    colorHex: string
    regionId: string
  }> = []

  for (const color of PAINT_COLORS) {
    const defectId = input.assignments[color.id]
    if (!defectId) continue
    const paintedParts = new Set(
      input.strokes
        .filter((stroke) => stroke.regionId === color.id && stroke.mode === 'paint')
        .map((stroke) => stroke.surfacePartId),
    )
    for (const partId of paintedParts) {
      if (!partId || partId === 'all' || partId === 'rotor' || partId === 'unclassified') continue
      result.push({
        defectId,
        partId,
        colorHex: color.hex,
        regionId: color.id,
      })
    }
  }
  return result
}

export class StrokeHistory {
  private strokes: BrushStroke[] = []
  private undone: BrushStroke[] = []

  get list(): readonly BrushStroke[] {
    return this.strokes
  }

  push(stroke: BrushStroke): void {
    this.strokes = [...this.strokes, stroke]
    this.undone = []
  }

  undo(): BrushStroke | null {
    if (this.strokes.length === 0) return null
    const last = this.strokes[this.strokes.length - 1]
    this.strokes = this.strokes.slice(0, -1)
    this.undone = [...this.undone, last]
    return last
  }

  redo(): BrushStroke | null {
    if (this.undone.length === 0) return null
    const next = this.undone[this.undone.length - 1]
    this.undone = this.undone.slice(0, -1)
    this.strokes = [...this.strokes, next]
    return next
  }

  clear(): void {
    this.strokes = []
    this.undone = []
  }

  clearColor(colorId: PaintColorId): void {
    this.strokes = this.strokes.filter((stroke) => stroke.regionId !== colorId)
    this.undone = []
  }

  get canUndo(): boolean {
    return this.strokes.length > 0
  }

  get canRedo(): boolean {
    return this.undone.length > 0
  }
}

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace('#', '')
  const n = Number.parseInt(value, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

/** Draw the painted colours onto a canvas used as a transparent overlay on the model. */
export function rasteriseOverlay(
  canvas: HTMLCanvasElement,
  strokes: readonly BrushStroke[],
  opacity: number,
  surfaceId?: string,
): void {
  const width = canvas.width
  const height = canvas.height
  const context = canvas.getContext('2d')
  if (!context) return

  context.clearRect(0, 0, width, height)

  for (const stroke of strokes) {
    if (surfaceId !== undefined && stroke.surfaceId !== surfaceId) continue
    const color = getPaintColor(stroke.regionId)
    const [r, g, b] = hexToRgb(color.hex)
    const radiusPx = Math.max(1.5, stroke.radiusUv * Math.min(width, height))
    context.globalCompositeOperation = stroke.mode === 'erase' ? 'destination-out' : 'source-over'
    context.fillStyle =
      stroke.mode === 'erase' ? 'rgba(0,0,0,1)' : `rgba(${r},${g},${b},${Math.min(1, opacity)})`
    context.strokeStyle = context.fillStyle
    context.lineWidth = radiusPx * 2
    context.lineCap = 'round'
    context.lineJoin = 'round'

    for (let i = 0; i < stroke.points.length; i += 1) {
      const [u, v] = stroke.points[i]
      const x = u * width
      const y = (1 - v) * height
      context.beginPath()
      context.arc(x, y, radiusPx, 0, Math.PI * 2)
      context.fill()
      if (i > 0) {
        const [pu, pv] = stroke.points[i - 1]
        context.beginPath()
        context.moveTo(pu * width, (1 - pv) * height)
        context.lineTo(x, y)
        context.stroke()
      }
    }
  }
  context.globalCompositeOperation = 'source-over'
}

export function hashUvLayout(sample: Array<[number, number]>): string {
  let h = 2166136261
  for (const [u, v] of sample) {
    const packed = Math.round(u * 1e6) ^ (Math.round(v * 1e6) << 1)
    h ^= packed
    h = Math.imul(h, 16777619)
  }
  return (h >>> 0).toString(16).padStart(8, '0')
}

// Kept for older imports that still name these helpers.
export function regionIdForDefect(defectId: string, _partId: string): string {
  void _partId
  return defectId
}

export function layerFromDefect(): never {
  throw new Error('layerFromDefect was replaced by the fixed colour palette.')
}

export function buildStrokeDocument(): never {
  throw new Error('buildStrokeDocument was replaced by buildDocumentFromPalette.')
}
