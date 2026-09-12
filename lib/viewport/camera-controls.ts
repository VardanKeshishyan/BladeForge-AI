/**
 * Viewport camera controller.
 *
 * The orbit model is deliberately identical to `bladeforge_core.cameras`: a target
 * point, an azimuth measured in the XY plane, an elevation above it, and a distance,
 * with +Z up. That means a view the user frames here converts straight into a
 * backend-validated camera configuration — the browser never has to hand the renderer a
 * raw transformation matrix, which the backend would have no safe way to bound.
 *
 * Navigation follows the conventions of the tools this audience already uses, so no one
 * has to learn a new mouse language.
 */

export type NavigationScheme = 'blender' | 'maya' | 'simple'

export type NavigationAction = 'orbit' | 'pan' | 'dolly' | 'paint' | 'none'

export type StandardView = 'perspective' | 'front' | 'back' | 'left' | 'right' | 'top' | 'bottom'

export interface OrbitState {
  target: [number, number, number]
  azimuthDeg: number
  elevationDeg: number
  distanceM: number
}

export interface ControllerLimits {
  minDistanceM: number
  maxDistanceM: number
  minElevationDeg: number
  maxElevationDeg: number
}

const DEFAULT_LIMITS: ControllerLimits = {
  minDistanceM: 0.35,
  maxDistanceM: 900,
  // Stopping just short of the poles avoids the gimbal flip that makes an orbit camera
  // feel broken when you drag past vertical.
  minElevationDeg: -89.5,
  maxElevationDeg: 89.5,
}

export interface PointerContext {
  button: number
  altKey: boolean
  ctrlKey: boolean
  shiftKey: boolean
  metaKey: boolean
  /** True while the paint tool is active, which claims the left button. */
  paintMode: boolean
}

const LEFT = 0
const MIDDLE = 1
const RIGHT = 2

/**
 * Decide what a drag means.
 *
 * Every scheme also accepts the middle-button and Ctrl combinations, because those are
 * the ones people reach for regardless of which package they came from.
 */
export function resolveAction(scheme: NavigationScheme, event: PointerContext): NavigationAction {
  const { button, altKey, ctrlKey, shiftKey, metaKey, paintMode } = event
  const alt = altKey || metaKey

  // Middle button behaves the same everywhere: it is the universal navigation button.
  if (button === MIDDLE) {
    if (shiftKey) return 'pan'
    if (ctrlKey) return 'dolly'
    return 'orbit'
  }

  if (scheme === 'maya') {
    if (alt && button === LEFT) return 'orbit'
    if (alt && button === RIGHT) return 'dolly'
    if (paintMode && button === LEFT) return 'paint'
    if (button === RIGHT) return 'dolly'
    if (ctrlKey && button === LEFT) return 'pan'
    if (button === LEFT) return paintMode ? 'paint' : 'orbit'
    return 'none'
  }

  if (scheme === 'blender') {
    // Blender drives navigation from the middle button, so the left button stays free
    // for selection and painting.
    if (button === RIGHT) return 'pan'
    if (ctrlKey && button === LEFT) return 'dolly'
    if (shiftKey && button === LEFT) return 'pan'
    if (alt && button === LEFT) return 'orbit'
    if (button === LEFT) return paintMode ? 'paint' : 'orbit'
    return 'none'
  }

  // simple: left orbits, Ctrl or right pans, and the wheel zooms.
  if (button === LEFT) {
    if (paintMode && !ctrlKey && !shiftKey && !alt) return 'paint'
    if (ctrlKey) return 'dolly'
    if (shiftKey) return 'pan'
    return 'orbit'
  }
  if (button === RIGHT) return 'pan'
  return 'none'
}

export function describeScheme(scheme: NavigationScheme): { action: string; binding: string }[] {
  if (scheme === 'maya') {
    return [
      { action: 'Orbit', binding: 'Alt + left drag' },
      { action: 'Pan', binding: 'Alt + middle drag' },
      { action: 'Zoom', binding: 'Alt + right drag, or wheel' },
      { action: 'Frame selection', binding: 'F' },
      { action: 'Frame all', binding: 'A' },
    ]
  }
  if (scheme === 'blender') {
    return [
      { action: 'Orbit', binding: 'Middle drag' },
      { action: 'Pan', binding: 'Shift + middle drag, or right drag' },
      { action: 'Zoom', binding: 'Ctrl + middle drag, or wheel' },
      { action: 'Front / right / top', binding: '1 / 3 / 7' },
      { action: 'Frame selection', binding: 'Period' },
      { action: 'Frame all', binding: 'Home' },
    ]
  }
  return [
    { action: 'Orbit', binding: 'Left drag' },
    { action: 'Pan', binding: 'Right drag, or Shift + left drag' },
    { action: 'Zoom', binding: 'Wheel, or Ctrl + left drag' },
    { action: 'Frame all', binding: 'Home' },
  ]
}

export interface BoundingSphere {
  centre: [number, number, number]
  radiusM: number
}

/** View direction presets, expressed as azimuth and elevation in the Z-up frame. */
const STANDARD_VIEWS: Record<StandardView, { azimuthDeg: number; elevationDeg: number }> = {
  // A shallow three-quarter view. Keeping the elevation low leaves the horizon in frame,
  // which gives the blade a sense of scale that a steep top-down view loses.
  perspective: { azimuthDeg: -55, elevationDeg: 12 },
  front: { azimuthDeg: -90, elevationDeg: 0 },
  back: { azimuthDeg: 90, elevationDeg: 0 },
  left: { azimuthDeg: 180, elevationDeg: 0 },
  right: { azimuthDeg: 0, elevationDeg: 0 },
  top: { azimuthDeg: -90, elevationDeg: 89.5 },
  bottom: { azimuthDeg: -90, elevationDeg: -89.5 },
}

/**
 * The blade registry defines the span along +Z, which with a Z-up camera would stand a
 * 62 m blade on its root and reduce it to a sliver in a widescreen viewport. The
 * viewport therefore lays it down, rotating blade +Z onto display +X, and converts back
 * whenever a pose has to leave the browser.
 *
 * Keeping the conversion in one pair of functions is deliberate: an orientation mismatch
 * between the viewport and the renderer would silently point every saved camera at the
 * wrong part of the blade.
 */
export function displayFromBlade(
  point: readonly [number, number, number],
): [number, number, number] {
  return [point[2], point[1], -point[0]]
}

export function bladeFromDisplay(
  point: readonly [number, number, number],
): [number, number, number] {
  return [-point[2], point[1], point[0]]
}

/** Recover azimuth, elevation, and distance. Mirrors `cartesian_to_spherical`. */
export function orbitFromPositions(
  target: readonly [number, number, number],
  location: readonly [number, number, number],
): { azimuthDeg: number; elevationDeg: number; distanceM: number } {
  const dx = location[0] - target[0]
  const dy = location[1] - target[1]
  const dz = location[2] - target[2]
  const distance = Math.hypot(dx, dy, dz)
  if (distance < 1e-9) return { azimuthDeg: 0, elevationDeg: 0, distanceM: 0 }
  return {
    azimuthDeg: (Math.atan2(dy, dx) * 180) / Math.PI,
    elevationDeg: (Math.asin(Math.min(1, Math.max(-1, dz / distance))) * 180) / Math.PI,
    distanceM: distance,
  }
}

/** Convert a viewport pose into the blade-space orbit the backend validates and renders. */
export function toBladeSpaceOrbit(displayState: OrbitState): OrbitState {
  const azimuth = (displayState.azimuthDeg * Math.PI) / 180
  const elevation = (displayState.elevationDeg * Math.PI) / 180
  const horizontal = displayState.distanceM * Math.cos(elevation)
  const displayPosition: [number, number, number] = [
    displayState.target[0] + horizontal * Math.cos(azimuth),
    displayState.target[1] + horizontal * Math.sin(azimuth),
    displayState.target[2] + displayState.distanceM * Math.sin(elevation),
  ]

  const target = bladeFromDisplay(displayState.target)
  const orbit = orbitFromPositions(target, bladeFromDisplay(displayPosition))
  return { target, ...orbit }
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value))
}

function wrapDegrees(value: number): number {
  return ((value + 180) % 360 + 360) % 360 - 180
}

/**
 * Smoothly damped orbit camera.
 *
 * Input mutates a desired state; `advance` eases the live state towards it. The damping
 * is what separates a viewport that feels like a tool from one that feels like a toy.
 */
export class OrbitCameraController {
  readonly limits: ControllerLimits

  private desired: OrbitState
  private current: OrbitState
  private home: OrbitState
  /** Vertical field of view in degrees, needed to convert a radius into a distance. */
  private fovDeg: number
  private aspect = 1

  constructor(initial: OrbitState, fovDeg = 40, limits: Partial<ControllerLimits> = {}) {
    this.limits = { ...DEFAULT_LIMITS, ...limits }
    this.desired = { ...initial, target: [...initial.target] as [number, number, number] }
    this.current = { ...initial, target: [...initial.target] as [number, number, number] }
    this.home = { ...initial, target: [...initial.target] as [number, number, number] }
    this.fovDeg = fovDeg
  }

  setFov(fovDeg: number): void {
    this.fovDeg = fovDeg
  }

  setAspect(aspect: number): void {
    this.aspect = aspect > 0 ? aspect : 1
  }

  /** The eased state the camera should currently use. */
  get state(): OrbitState {
    return {
      target: [...this.current.target] as [number, number, number],
      azimuthDeg: this.current.azimuthDeg,
      elevationDeg: this.current.elevationDeg,
      distanceM: this.current.distanceM,
    }
  }

  /** The state the user has asked for, which is what gets saved as a camera view. */
  get requestedState(): OrbitState {
    return {
      target: [...this.desired.target] as [number, number, number],
      azimuthDeg: wrapDegrees(this.desired.azimuthDeg),
      elevationDeg: this.desired.elevationDeg,
      distanceM: this.desired.distanceM,
    }
  }

  /** Camera position for the eased state. Matches `spherical_to_cartesian` exactly. */
  get position(): [number, number, number] {
    const { target, azimuthDeg, elevationDeg, distanceM } = this.current
    const azimuth = (azimuthDeg * Math.PI) / 180
    const elevation = (elevationDeg * Math.PI) / 180
    const horizontal = distanceM * Math.cos(elevation)
    return [
      target[0] + horizontal * Math.cos(azimuth),
      target[1] + horizontal * Math.sin(azimuth),
      target[2] + distanceM * Math.sin(elevation),
    ]
  }

  orbit(deltaX: number, deltaY: number, sensitivity = 0.32): void {
    this.desired.azimuthDeg -= deltaX * sensitivity
    this.desired.elevationDeg = clamp(
      this.desired.elevationDeg + deltaY * sensitivity,
      this.limits.minElevationDeg,
      this.limits.maxElevationDeg,
    )
  }

  /**
   * Pan in the camera's own screen plane.
   *
   * Scaling by distance and field of view keeps a drag moving the model the same number
   * of screen pixels whether you are inspecting a bolt or looking at the whole blade.
   */
  pan(deltaX: number, deltaY: number, viewportHeight: number): void {
    const worldPerPixel =
      (2 * this.desired.distanceM * Math.tan(((this.fovDeg / 2) * Math.PI) / 180)) /
      Math.max(1, viewportHeight)

    const azimuth = (this.desired.azimuthDeg * Math.PI) / 180
    const elevation = (this.desired.elevationDeg * Math.PI) / 180

    // Screen right, perpendicular to the view direction and horizontal in world space.
    const rightX = -Math.sin(azimuth)
    const rightY = Math.cos(azimuth)

    // Screen up, tilted by the current elevation.
    const upX = -Math.cos(azimuth) * Math.sin(elevation)
    const upY = -Math.sin(azimuth) * Math.sin(elevation)
    const upZ = Math.cos(elevation)

    const shiftRight = -deltaX * worldPerPixel
    const shiftUp = deltaY * worldPerPixel

    this.desired.target[0] += rightX * shiftRight + upX * shiftUp
    this.desired.target[1] += rightY * shiftRight + upY * shiftUp
    this.desired.target[2] += upZ * shiftUp
  }

  /** Multiplicative dolly, so each notch feels the same at any scale. */
  dolly(factor: number): void {
    this.desired.distanceM = clamp(
      this.desired.distanceM * factor,
      this.limits.minDistanceM,
      this.limits.maxDistanceM,
    )
  }

  dollyByPixels(deltaY: number): void {
    this.dolly(Math.exp(deltaY * 0.006))
  }

  dollyByWheel(deltaY: number): void {
    this.dolly(Math.exp(deltaY * 0.0012))
  }

  setView(view: StandardView): void {
    const preset = STANDARD_VIEWS[view]
    this.desired.azimuthDeg = preset.azimuthDeg
    this.desired.elevationDeg = preset.elevationDeg
  }

  /** Frame a bounding sphere, leaving a small margin so nothing touches the edge. */
  frame(sphere: BoundingSphere, margin = 1.18): void {
    this.desired.target = [...sphere.centre] as [number, number, number]
    const verticalFov = (this.fovDeg * Math.PI) / 180
    const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * this.aspect)
    const limiting = Math.min(verticalFov, horizontalFov)
    const distance = (sphere.radiusM * margin) / Math.max(0.05, Math.sin(limiting / 2))
    this.desired.distanceM = clamp(distance, this.limits.minDistanceM, this.limits.maxDistanceM)
  }

  /** Orbit around a picked point without moving the camera, the way "focus" behaves. */
  focusOn(point: [number, number, number], distanceM?: number): void {
    this.desired.target = [...point] as [number, number, number]
    if (distanceM !== undefined) {
      this.desired.distanceM = clamp(
        distanceM,
        this.limits.minDistanceM,
        this.limits.maxDistanceM,
      )
    }
  }

  /** Remember the current view as the one the reset button returns to. */
  setHome(state?: OrbitState): void {
    const source = state ?? this.desired
    this.home = { ...source, target: [...source.target] as [number, number, number] }
  }

  reset(): void {
    this.desired = { ...this.home, target: [...this.home.target] as [number, number, number] }
  }

  /** Jump straight to a state with no easing, for restoring a saved view. */
  jumpTo(state: OrbitState): void {
    this.desired = { ...state, target: [...state.target] as [number, number, number] }
    this.current = { ...state, target: [...state.target] as [number, number, number] }
  }

  /**
   * Ease the live state towards the desired state.
   *
   * `delta` is the frame time in seconds, so the motion is identical on a 60 Hz and a
   * 144 Hz display instead of being three times faster on better hardware.
   */
  advance(delta: number, responsiveness = 14): boolean {
    const blend = 1 - Math.exp(-responsiveness * Math.max(0, Math.min(delta, 0.1)))

    // Take the shortest way round, so dragging past 180 degrees does not unwind.
    const azimuthDelta = wrapDegrees(this.desired.azimuthDeg - this.current.azimuthDeg)
    const elevationDelta = this.desired.elevationDeg - this.current.elevationDeg
    const distanceRatio = this.desired.distanceM / Math.max(1e-6, this.current.distanceM)
    const targetDelta = [
      this.desired.target[0] - this.current.target[0],
      this.desired.target[1] - this.current.target[1],
      this.desired.target[2] - this.current.target[2],
    ]

    const settled =
      Math.abs(azimuthDelta) < 0.002 &&
      Math.abs(elevationDelta) < 0.002 &&
      Math.abs(distanceRatio - 1) < 0.00002 &&
      Math.hypot(targetDelta[0], targetDelta[1], targetDelta[2]) < 0.0005

    if (settled) {
      this.current.azimuthDeg = this.desired.azimuthDeg
      this.current.elevationDeg = this.desired.elevationDeg
      this.current.distanceM = this.desired.distanceM
      this.current.target = [...this.desired.target] as [number, number, number]
      return false
    }

    this.current.azimuthDeg += azimuthDelta * blend
    this.current.elevationDeg += elevationDelta * blend
    // Interpolating distance geometrically keeps zoom smooth across orders of magnitude.
    this.current.distanceM *= Math.pow(distanceRatio, blend)
    this.current.target[0] += targetDelta[0] * blend
    this.current.target[1] += targetDelta[1] * blend
    this.current.target[2] += targetDelta[2] * blend
    return true
  }
}
