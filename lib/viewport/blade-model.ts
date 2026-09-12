/**
 * Blade geometry for the interactive viewport.
 *
 * The surface is lofted from the same airfoil stations, and unwrapped with the same UV
 * convention, that `bladeforge_core.blades.BF_GENERIC_BLADE_V1` declares. That matters
 * for more than looks: region painting records brush strokes in UV space, so if this
 * unwrap disagreed with the renderer's, every painted region would land in the wrong
 * place on the blade.
 *
 * Coordinate frame matches Blender and the backend camera model:
 *   +Z  span, root at z=0 and tip at z=length
 *   -X  leading edge,  +X  trailing edge
 *   +Y  suction side
 *   Z is up.
 */

export interface AirfoilStation {
  spanFraction: number
  chordM: number
  twistDeg: number
  thicknessRatio: number
  prebendM: number
}

export interface BladeSectionSpec {
  id: string
  displayName: string
  spanStartFraction: number
  spanEndFraction: number
  description: string
}

export interface UvLayoutSpec {
  uvSetName: string
  chordwiseSamples: number
  spanwiseSamples: number
  landmarks: Record<string, [number, number]>
}

export interface BladeModelSpec {
  id: string
  version: string
  title: string
  lengthM: number
  rootDiameterM: number
  maxChordM: number
  tipChordM: number
  stations: AirfoilStation[]
  sections: BladeSectionSpec[]
  uvLayout: UvLayoutSpec
  metallicComponents: string[]
}

/**
 * Mirrors BF_GENERIC_BLADE_V1. The backend remains authoritative — the capabilities
 * endpoint serves these numbers and a contract test asserts the two agree — but the
 * viewport keeps a local copy so it can draw a blade before any network call resolves.
 */
export const BF_GENERIC_BLADE_V1: BladeModelSpec = {
  id: 'BF_GENERIC_BLADE_V1',
  version: '1.0.0',
  title: 'BladeForge generic utility-scale blade',
  lengthM: 62.0,
  rootDiameterM: 3.4,
  maxChordM: 4.2,
  tipChordM: 0.55,
  stations: [
    { spanFraction: 0.0, chordM: 3.4, twistDeg: 14.0, thicknessRatio: 1.0, prebendM: 0.0 },
    { spanFraction: 0.035, chordM: 3.42, twistDeg: 13.6, thicknessRatio: 0.88, prebendM: 0.002 },
    { spanFraction: 0.08, chordM: 3.7, twistDeg: 12.8, thicknessRatio: 0.62, prebendM: 0.01 },
    { spanFraction: 0.15, chordM: 4.12, twistDeg: 11.2, thicknessRatio: 0.4, prebendM: 0.038 },
    { spanFraction: 0.22, chordM: 4.2, twistDeg: 9.1, thicknessRatio: 0.32, prebendM: 0.082 },
    { spanFraction: 0.3, chordM: 3.94, twistDeg: 6.8, thicknessRatio: 0.272, prebendM: 0.152 },
    { spanFraction: 0.4, chordM: 3.42, twistDeg: 4.6, thicknessRatio: 0.238, prebendM: 0.286 },
    { spanFraction: 0.5, chordM: 2.9, twistDeg: 3.1, thicknessRatio: 0.212, prebendM: 0.47 },
    { spanFraction: 0.6, chordM: 2.4, twistDeg: 1.9, thicknessRatio: 0.192, prebendM: 0.732 },
    { spanFraction: 0.7, chordM: 1.92, twistDeg: 0.95, thicknessRatio: 0.178, prebendM: 1.108 },
    { spanFraction: 0.8, chordM: 1.46, twistDeg: 0.1, thicknessRatio: 0.166, prebendM: 1.64 },
    { spanFraction: 0.9, chordM: 1.02, twistDeg: -0.8, thicknessRatio: 0.156, prebendM: 2.36 },
    { spanFraction: 0.96, chordM: 0.76, twistDeg: -1.3, thicknessRatio: 0.15, prebendM: 2.86 },
    { spanFraction: 1.0, chordM: 0.55, twistDeg: -1.5, thicknessRatio: 0.146, prebendM: 3.2 },
  ],
  sections: [
    {
      id: 'root_transition',
      displayName: 'Root transition',
      spanStartFraction: 0.0,
      spanEndFraction: 0.15,
      description:
        'Cylindrical root and the transition into the first airfoil. Carries the metallic attachment hardware.',
    },
    {
      id: 'inboard',
      displayName: 'Inboard',
      spanStartFraction: 0.15,
      spanEndFraction: 0.35,
      description: 'Maximum chord region. Thick sections, high structural loading.',
    },
    {
      id: 'midspan',
      displayName: 'Mid-span',
      spanStartFraction: 0.35,
      spanEndFraction: 0.65,
      description: 'The long tapering mid-section where cracks and delamination are common.',
    },
    {
      id: 'outboard',
      displayName: 'Outboard',
      spanStartFraction: 0.65,
      spanEndFraction: 0.88,
      description: 'High relative velocity. The dominant region for leading-edge erosion.',
    },
    {
      id: 'tip',
      displayName: 'Tip',
      spanStartFraction: 0.88,
      spanEndFraction: 1.0,
      description: 'Tip region. Highest erosion rate and the usual lightning attachment zone.',
    },
  ],
  uvLayout: {
    uvSetName: 'BF_UV',
    chordwiseSamples: 96,
    spanwiseSamples: 64,
    landmarks: {
      root_leading_edge: [0.0, 0.0],
      tip_leading_edge: [0.0, 1.0],
      root_trailing_edge: [0.5, 0.0],
      tip_trailing_edge: [0.5, 1.0],
      midspan_leading_edge: [0.0, 0.5],
      midspan_trailing_edge: [0.5, 0.5],
      midspan_pressure_side: [0.75, 0.5],
    },
  },
  metallicComponents: [
    'BF_RootFlangeBolts',
    'BF_TipLightningReceptor',
    'BF_MidspanLightningReceptor',
  ],
}

/** Cosine spacing packs samples towards the leading and trailing edges, where curvature is highest. */
function cosineSpacing(count: number): number[] {
  const values: number[] = []
  for (let i = 0; i < count; i += 1) {
    const t = i / (count - 1)
    values.push(0.5 * (1 - Math.cos(Math.PI * t)))
  }
  return values
}

/** NACA 4-digit half-thickness distribution. */
function nacaHalfThickness(x: number, thickness: number): number {
  return (
    5 *
    thickness *
    (0.2969 * Math.sqrt(Math.max(x, 0)) -
      0.126 * x -
      0.3516 * x * x +
      0.2843 * x * x * x -
      0.1015 * x * x * x * x)
  )
}

/** Mean camber line of a NACA 4-digit section, giving the surface an asymmetric, lifting shape. */
function camberLine(x: number, maxCamber: number, camberPosition: number): number {
  if (x < camberPosition) {
    return (maxCamber / (camberPosition * camberPosition)) * (2 * camberPosition * x - x * x)
  }
  const q = 1 - camberPosition
  return (maxCamber / (q * q)) * (1 - 2 * camberPosition + 2 * camberPosition * x - x * x)
}

interface SectionPoint {
  /** Chordwise position, 0 at the leading edge and 1 at the trailing edge. */
  x: number
  /** Thickness-wise offset. */
  y: number
  /** Chordwise-arclength UV coordinate, 0 at the leading-edge seam. */
  u: number
}

/**
 * One closed airfoil outline, ordered leading edge → suction side → trailing edge →
 * pressure side → back to the leading edge.
 *
 * `thicknessRatio` of 1 produces the circular root, and lower values blend towards a
 * true airfoil, which is how a real blade transitions out of its cylindrical root.
 */
function airfoilOutline(thicknessRatio: number, halfCount: number): SectionPoint[] {
  // How far this station has progressed from a cylinder towards a slender airfoil.
  const airfoilBlend = Math.min(1, Math.max(0, (1 - thicknessRatio) / 0.75))
  const maxCamber = 0.035 * airfoilBlend
  const camberPosition = 0.4
  const xs = cosineSpacing(halfCount + 1)

  const upper: { x: number; y: number }[] = []
  const lower: { x: number; y: number }[] = []
  for (const x of xs) {
    const airfoilThickness = nacaHalfThickness(x, thicknessRatio)
    // A circle of unit diameter, used for the root where thicknessRatio is 1.
    const circle = Math.sqrt(Math.max(0, 0.25 - (x - 0.5) * (x - 0.5)))
    const half = airfoilBlend * airfoilThickness + (1 - airfoilBlend) * circle
    const camber = camberLine(x, maxCamber, camberPosition)
    upper.push({ x, y: camber + half })
    lower.push({ x, y: camber - half })
  }

  // Normalise arclength independently per side so the trailing edge always lands on
  // u = 0.5, which is the landmark the backend and the region rasteriser rely on.
  const measure = (points: { x: number; y: number }[]) => {
    const cumulative = [0]
    for (let i = 1; i < points.length; i += 1) {
      const dx = points[i].x - points[i - 1].x
      const dy = points[i].y - points[i - 1].y
      cumulative.push(cumulative[i - 1] + Math.hypot(dx, dy))
    }
    const total = cumulative[cumulative.length - 1] || 1
    return cumulative.map((value) => value / total)
  }

  const upperT = measure(upper)
  const lowerT = measure(lower)

  const outline: SectionPoint[] = []
  for (let i = 0; i < upper.length; i += 1) {
    outline.push({ x: upper[i].x, y: upper[i].y, u: 0.5 * upperT[i] })
  }
  // Walk the pressure side back from the trailing edge, skipping the shared TE point.
  for (let i = lower.length - 2; i >= 0; i -= 1) {
    const travelled = 1 - lowerT[i] / lowerT[lower.length - 1]
    outline.push({ x: lower[i].x, y: lower[i].y, u: 0.5 + 0.5 * travelled })
  }
  // Close the loop with a duplicate of the leading edge carrying u = 1, so the UV seam
  // is explicit rather than wrapping and smearing the texture across the whole chord.
  outline.push({ x: upper[0].x, y: upper[0].y, u: 1 })
  return outline
}

function interpolateStation(stations: AirfoilStation[], spanFraction: number): AirfoilStation {
  if (spanFraction <= stations[0].spanFraction) return stations[0]
  const last = stations[stations.length - 1]
  if (spanFraction >= last.spanFraction) return last
  let index = 0
  while (index < stations.length - 2 && stations[index + 1].spanFraction < spanFraction) {
    index += 1
  }
  const a = stations[index]
  const b = stations[index + 1]
  const span = b.spanFraction - a.spanFraction
  const t = span <= 0 ? 0 : (spanFraction - a.spanFraction) / span
  // Smoothstep keeps the lofted surface free of the visible creases that linear
  // interpolation leaves at each station.
  const s = t * t * (3 - 2 * t)
  return {
    spanFraction,
    chordM: a.chordM + (b.chordM - a.chordM) * s,
    twistDeg: a.twistDeg + (b.twistDeg - a.twistDeg) * s,
    thicknessRatio: a.thicknessRatio + (b.thicknessRatio - a.thicknessRatio) * s,
    prebendM: a.prebendM + (b.prebendM - a.prebendM) * s,
  }
}

export interface BladeGeometryData {
  positions: Float32Array
  normals: Float32Array
  uvs: Float32Array
  indices: Uint32Array
  /** Span fraction per vertex, used to highlight a selected blade section. */
  spanFractions: Float32Array
  ringCount: number
  ringSize: number
  triangleCount: number
}

export interface BladeGeometryOptions {
  /** Multiplies the registry's declared sample counts. 1 matches the renderer exactly. */
  detail?: number
}

/**
 * Build the lofted blade surface.
 *
 * Returns raw typed arrays rather than a THREE.BufferGeometry so this stays testable
 * without a WebGL context and can run in a worker later if it ever needs to.
 */
export function buildBladeGeometry(
  spec: BladeModelSpec = BF_GENERIC_BLADE_V1,
  options: BladeGeometryOptions = {},
): BladeGeometryData {
  const detail = Math.max(0.25, Math.min(4, options.detail ?? 1))
  const halfCount = Math.max(8, Math.round((spec.uvLayout.chordwiseSamples * detail) / 2))
  const ringCount = Math.max(8, Math.round(spec.uvLayout.spanwiseSamples * detail))
  const ringSize = halfCount * 2 + 1

  const vertexCount = ringCount * ringSize
  const positions = new Float32Array(vertexCount * 3)
  const uvs = new Float32Array(vertexCount * 2)
  const spanFractions = new Float32Array(vertexCount)

  for (let ring = 0; ring < ringCount; ring += 1) {
    const v = ring / (ringCount - 1)
    const station = interpolateStation(spec.stations, v)
    const outline = airfoilOutline(station.thicknessRatio, halfCount)
    const twist = (station.twistDeg * Math.PI) / 180
    const cos = Math.cos(twist)
    const sin = Math.sin(twist)
    const z = v * spec.lengthM

    for (let i = 0; i < ringSize; i += 1) {
      const point = outline[i]
      // Rotate about the pitch axis at 30% chord, which is roughly where a real blade's
      // structural spar sits.
      const chordwise = (point.x - 0.3) * station.chordM
      const thicknessWise = point.y * station.chordM
      const x = chordwise * cos - thicknessWise * sin + station.prebendM
      const y = chordwise * sin + thicknessWise * cos

      const vertex = ring * ringSize + i
      positions[vertex * 3] = x
      positions[vertex * 3 + 1] = y
      positions[vertex * 3 + 2] = z
      uvs[vertex * 2] = point.u
      uvs[vertex * 2 + 1] = v
      spanFractions[vertex] = v
    }
  }

  const quadCount = (ringCount - 1) * (ringSize - 1)
  const indices = new Uint32Array(quadCount * 6)
  let cursor = 0
  for (let ring = 0; ring < ringCount - 1; ring += 1) {
    for (let i = 0; i < ringSize - 1; i += 1) {
      const a = ring * ringSize + i
      const b = a + 1
      const c = a + ringSize
      const d = c + 1
      indices[cursor] = a
      indices[cursor + 1] = c
      indices[cursor + 2] = b
      indices[cursor + 3] = b
      indices[cursor + 4] = c
      indices[cursor + 5] = d
      cursor += 6
    }
  }

  return {
    positions,
    normals: computeNormals(positions, indices),
    uvs,
    indices,
    spanFractions,
    ringCount,
    ringSize,
    triangleCount: quadCount * 2,
  }
}

/** Area-weighted vertex normals, so the lofted surface shades smoothly. */
function computeNormals(positions: Float32Array, indices: Uint32Array): Float32Array {
  const normals = new Float32Array(positions.length)
  for (let i = 0; i < indices.length; i += 3) {
    const ia = indices[i] * 3
    const ib = indices[i + 1] * 3
    const ic = indices[i + 2] * 3

    const abx = positions[ib] - positions[ia]
    const aby = positions[ib + 1] - positions[ia + 1]
    const abz = positions[ib + 2] - positions[ia + 2]
    const acx = positions[ic] - positions[ia]
    const acy = positions[ic + 1] - positions[ia + 1]
    const acz = positions[ic + 2] - positions[ia + 2]

    // Cross product magnitude is twice the triangle area, which weights the average.
    const nx = aby * acz - abz * acy
    const ny = abz * acx - abx * acz
    const nz = abx * acy - aby * acx

    for (const offset of [ia, ib, ic]) {
      normals[offset] += nx
      normals[offset + 1] += ny
      normals[offset + 2] += nz
    }
  }
  for (let i = 0; i < normals.length; i += 3) {
    const length = Math.hypot(normals[i], normals[i + 1], normals[i + 2]) || 1
    normals[i] /= length
    normals[i + 1] /= length
    normals[i + 2] /= length
  }
  return normals
}

/** Where along the span a named section sits, for camera framing and highlighting. */
export function sectionSpan(
  spec: BladeModelSpec,
  sectionId: string,
): { start: number; end: number; centre: number } {
  const section = spec.sections.find((entry) => entry.id === sectionId)
  if (!section) return { start: 0, end: 1, centre: 0.5 }
  return {
    start: section.spanStartFraction,
    end: section.spanEndFraction,
    centre: (section.spanStartFraction + section.spanEndFraction) / 2,
  }
}

export interface HardwarePlacement {
  name: string
  /** Metres, in the blade's own frame. */
  position: [number, number, number]
  radiusM: number
  heightM: number
  kind: 'bolt_ring' | 'receptor'
}

/**
 * The metallic parts. Corrosion is only physically honest on these, which is why the
 * viewport draws them separately and the properties panel can point at them.
 */
export function hardwarePlacements(spec: BladeModelSpec = BF_GENERIC_BLADE_V1): HardwarePlacement[] {
  return [
    {
      name: 'BF_RootFlangeBolts',
      position: [0, 0, 0.15],
      radiusM: spec.rootDiameterM / 2,
      heightM: 0.3,
      kind: 'bolt_ring',
    },
    {
      name: 'BF_MidspanLightningReceptor',
      position: [0, 0, spec.lengthM * 0.62],
      radiusM: 0.09,
      heightM: 0.04,
      kind: 'receptor',
    },
    {
      name: 'BF_TipLightningReceptor',
      position: [0, 0, spec.lengthM * 0.985],
      radiusM: 0.07,
      heightM: 0.04,
      kind: 'receptor',
    },
  ]
}
