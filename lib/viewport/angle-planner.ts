/**
 * Camera angle planning for "Generate all angles".
 *
 * Spreads a requested image count over viewpoints that are actually useful for training:
 * the four cardinal directions, raised and lowered elevations, and three working
 * distances. Angles are emitted in order of how much each one adds, so a small batch
 * still gets good coverage rather than eight variations on the same front view.
 *
 * Near-duplicates are dropped, because a pair of images taken two degrees apart teaches
 * a model almost nothing but still costs a full render.
 */

export interface PlannedAngle {
  index: number
  label: string
  azimuthDeg: number
  elevationDeg: number
  distanceM: number
  targetHeightM: number
}

export interface AnglePlanInput {
  /** How many images the customer asked for. Never exceeded. */
  imageCount: number
  /** Distance that frames the selected part comfortably. */
  baseDistanceM: number
  /** Height of the point being inspected, in metres above the base. */
  targetHeightM: number
}

/** Distance bands, as multiples of the framing distance. */
const DISTANCE_BANDS = [
  { key: 'close', label: 'close-up', factor: 0.45 },
  { key: 'medium', label: 'medium', factor: 1.0 },
  { key: 'wide', label: 'wide', factor: 2.1 },
] as const

/** Elevation bands. Slightly raised reads as a drone, lowered as a ground inspector. */
const ELEVATION_BANDS = [
  { key: 'level', label: 'level', elevationDeg: 4 },
  { key: 'elevated', label: 'elevated', elevationDeg: 32 },
  { key: 'lower', label: 'lower', elevationDeg: -18 },
] as const

const CARDINALS = [
  { key: 'front', label: 'front', azimuthDeg: -90 },
  { key: 'right', label: 'right', azimuthDeg: 0 },
  { key: 'back', label: 'back', azimuthDeg: 90 },
  { key: 'left', label: 'left', azimuthDeg: 180 },
] as const

function wrap(value: number): number {
  return ((value + 180) % 360 + 360) % 360 - 180
}

/**
 * Two angles are treated as the same shot when they are close on every axis. The
 * thresholds are deliberately generous — a model learns more from ten genuinely
 * different views than from forty near-identical ones.
 */
function isDuplicate(a: PlannedAngle, b: PlannedAngle): boolean {
  const azimuthGap = Math.abs(wrap(a.azimuthDeg - b.azimuthDeg))
  const elevationGap = Math.abs(a.elevationDeg - b.elevationDeg)
  const distanceRatio =
    Math.max(a.distanceM, b.distanceM) / Math.max(1e-6, Math.min(a.distanceM, b.distanceM))
  const heightGap = Math.abs(a.targetHeightM - b.targetHeightM)
  return azimuthGap < 18 && elevationGap < 10 && distanceRatio < 1.25 && heightGap < 3
}

/**
 * Build the ordered candidate list.
 *
 * The ordering is the important part. The first four entries are the cardinal views at a
 * medium distance, so a four-image batch gets all round the turbine. Detail and context
 * views come next, then off-axis angles fill in the gaps.
 */
function candidates(input: AnglePlanInput): PlannedAngle[] {
  const { baseDistanceM, targetHeightM } = input
  const list: Omit<PlannedAngle, 'index'>[] = []

  const push = (
    label: string,
    azimuthDeg: number,
    elevationDeg: number,
    factor: number,
    heightOffset = 0,
  ) => {
    list.push({
      label,
      azimuthDeg: wrap(azimuthDeg),
      elevationDeg,
      distanceM: baseDistanceM * factor,
      targetHeightM: Math.max(1, targetHeightM + heightOffset),
    })
  }

  // Pass 1: the four sides, level, at working distance.
  for (const cardinal of CARDINALS) {
    push(`${cardinal.label} · medium`, cardinal.azimuthDeg, ELEVATION_BANDS[0].elevationDeg, 1.0)
  }

  // Pass 2: detail and context from the two most informative sides.
  for (const cardinal of [CARDINALS[0], CARDINALS[2]]) {
    push(`${cardinal.label} · close-up`, cardinal.azimuthDeg, 6, DISTANCE_BANDS[0].factor)
    push(`${cardinal.label} · wide`, cardinal.azimuthDeg, 10, DISTANCE_BANDS[2].factor)
  }

  // Pass 3: raised and lowered looks all round.
  for (const cardinal of CARDINALS) {
    push(`${cardinal.label} · elevated`, cardinal.azimuthDeg, ELEVATION_BANDS[1].elevationDeg, 1.0)
  }
  for (const cardinal of CARDINALS) {
    push(`${cardinal.label} · lower`, cardinal.azimuthDeg, ELEVATION_BANDS[2].elevationDeg, 1.1)
  }

  // Pass 4: the diagonals, which catch damage the cardinals foreshorten.
  for (const cardinal of CARDINALS) {
    push(`${cardinal.label} oblique`, cardinal.azimuthDeg + 45, 12, 1.0)
  }

  // Pass 5: remaining combinations of distance and elevation, off-axis.
  for (const band of DISTANCE_BANDS) {
    for (const elevation of ELEVATION_BANDS) {
      for (const cardinal of CARDINALS) {
        push(
          `${cardinal.label} · ${elevation.label} ${band.label}`,
          cardinal.azimuthDeg + 22.5,
          elevation.elevationDeg,
          band.factor,
        )
      }
    }
  }

  return list.map((entry, index) => ({ ...entry, index }))
}

/**
 * Produce at most `imageCount` distinct angles.
 *
 * When the count exceeds the distinct candidates, extra azimuths are interleaved around
 * the turbine rather than repeating a view, so a large batch stays varied.
 */
export function planAngles(input: AnglePlanInput): PlannedAngle[] {
  const limit = Math.max(1, Math.floor(input.imageCount))
  const chosen: PlannedAngle[] = []

  for (const candidate of candidates(input)) {
    if (chosen.length >= limit) break
    if (chosen.some((existing) => isDuplicate(existing, candidate))) continue
    chosen.push({ ...candidate, index: chosen.length })
  }

  if (chosen.length < limit) {
    // Sweep azimuth on a golden-angle step, which spreads new views as evenly as
    // possible over the circle no matter how many are still needed.
    const goldenAngle = 137.507_764_05
    let cursor = 0
    while (chosen.length < limit) {
      const azimuth = wrap(cursor * goldenAngle)
      const elevationBand = ELEVATION_BANDS[cursor % ELEVATION_BANDS.length]
      const distanceBand = DISTANCE_BANDS[Math.floor(cursor / ELEVATION_BANDS.length) % DISTANCE_BANDS.length]
      const candidate: PlannedAngle = {
        index: chosen.length,
        label: `sweep ${chosen.length + 1} · ${distanceBand.label}`,
        azimuthDeg: azimuth,
        elevationDeg: elevationBand.elevationDeg,
        distanceM: input.baseDistanceM * distanceBand.factor,
        targetHeightM: input.targetHeightM,
      }
      cursor += 1
      if (chosen.some((existing) => isDuplicate(existing, candidate))) {
        // Guard against an unbounded loop once the circle is saturated.
        if (cursor > limit * 12) {
          chosen.push(candidate)
        }
        continue
      }
      chosen.push(candidate)
    }
  }

  return chosen.slice(0, limit)
}

/** One-line description of the coverage a plan gives, for the UI. */
export function describePlan(angles: PlannedAngle[]): string {
  if (angles.length === 0) return 'No angles planned.'
  const distances = new Set(angles.map((angle) => Math.round(angle.distanceM)))
  const elevations = new Set(angles.map((angle) => Math.round(angle.elevationDeg)))
  return `${angles.length} distinct angles · ${distances.size} distances · ${elevations.size} elevations`
}
