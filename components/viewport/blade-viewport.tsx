'use client'

/**
 * Interactive turbine viewport.
 *
 * Loads the real turbine model, lights it with either a captured HDRI or a procedural
 * sky, and lets the customer isolate a single part, frame a shot, and see the weather
 * they picked. The camera model matches the backend exactly, so a framed shot converts
 * into a bounded orbit the API can validate instead of an arbitrary browser matrix.
 */

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useStore, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { EXRLoader } from 'three/examples/jsm/loaders/EXRLoader.js'
import { HDRLoader } from 'three/examples/jsm/loaders/HDRLoader.js'
import {
  Axis3d,
  Box,
  Crosshair,
  Grid2x2,
  Loader2,
  Maximize2,
  Paintbrush,
  Palette,
  RotateCcw,
  TriangleAlert,
} from 'lucide-react'
import { RegionPainter } from '@/components/viewport/region-painter'
import {
  DEFAULT_PAINT_SETTINGS,
  type BrushStroke,
  type PaintSettings,
} from '@/lib/viewport/region-painting'

import {
  BUNDLED_TURBINE_URL,
  applyPartVisibility,
  createCleanWhiteMaterial,
  loadTurbineModel,
  type LoadedTurbineModel,
  type TurbinePartId,
} from '@/lib/viewport/turbine-model'
import {
  OrbitCameraController,
  describeScheme,
  resolveAction,
  type NavigationScheme,
  type StandardView,
} from '@/lib/viewport/camera-controls'
import { applyIntensity, getViewportEnvironment } from '@/lib/viewport/environments'
import { buildSky } from '@/lib/viewport/sky-texture'

/**
 * Rotation that stands an equirectangular map upright in this Z-up world.
 *
 * Equirectangular maps, both captured HDRIs and the procedural sky, are authored for a
 * Y-up world. Without this the horizon runs vertically and half the scene shows ground.
 */
const ENVIRONMENT_ROTATION = new THREE.Euler(-Math.PI / 2, 0, 0)

export interface ViewportCamera {
  /** Height up the turbine that the camera looks at, in metres above the base. */
  targetHeightM: number
  azimuthDeg: number
  elevationDeg: number
  distanceM: number
  fovDeg: number
  rollDeg: number
}

export interface ViewportSettings {
  modelUrl: string
  selectedPartId: TurbinePartId
  environmentId: string
  /** An uploaded environment map, which takes precedence over the preset's own. */
  customHdriUrl: string | null
  weatherIntensity: number
  showGrid: boolean
  showWireframe: boolean
  useOriginalMaterials: boolean
  navigationScheme: NavigationScheme
}

export const DEFAULT_VIEWPORT_CAMERA: ViewportCamera = {
  targetHeightM: 95,
  azimuthDeg: -55,
  elevationDeg: 8,
  distanceM: 55,
  fovDeg: 35,
  rollDeg: 0,
}

export const DEFAULT_VIEWPORT_SETTINGS: ViewportSettings = {
  modelUrl: BUNDLED_TURBINE_URL,
  selectedPartId: 'blades',
  environmentId: 'DESERT_CLEAR_V1',
  customHdriUrl: null,
  weatherIntensity: 0.5,
  showGrid: true,
  showWireframe: false,
  useOriginalMaterials: false,
  navigationScheme: 'blender',
}

/** Small deterministic generator, so a given scene always looks the same. */
function mulberry32(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// ─── Environment ──────────────────────────────────────────────────────────────

interface LoadedHdri {
  texture: THREE.DataTexture
  /** Log-average luminance, the standard estimate of a scene's middle grey. */
  logAverage: number
}

/**
 * Measure how bright a captured environment actually is.
 *
 * An HDRI stores absolute radiance, so a desert at noon and a moonlit sky are orders of
 * magnitude apart. Used as-is the desert map renders as a solid white frame. Measuring
 * the log-average lets each map be scaled to a chosen key value, which is how a camera's
 * light meter decides an exposure.
 */
function measureLogAverage(texture: THREE.DataTexture): number {
  const data = texture.image.data as Float32Array | Uint16Array
  const isHalf = !(data instanceof Float32Array)
  const read = (index: number) =>
    isHalf ? THREE.DataUtils.fromHalfFloat(data[index]) : data[index]

  const channels = data.length / (texture.image.width * texture.image.height)
  // Around forty thousand samples is ample for an average and keeps the load instant.
  const stride = Math.max(1, Math.floor(data.length / channels / 40000)) * channels

  let logSum = 0
  let samples = 0
  for (let i = 0; i < data.length; i += stride) {
    const luminance = read(i) * 0.2126 + read(i + 1) * 0.7152 + read(i + 2) * 0.0722
    if (!Number.isFinite(luminance) || luminance < 0) continue
    logSum += Math.log(1e-4 + luminance)
    samples += 1
  }
  return samples === 0 ? 1 : Math.exp(logSum / samples)
}

/**
 * Exposure gain for a captured map.
 *
 * Night keeps a much lower key so a moonlit sky stays a moonlit sky, rather than being
 * metered up into something that looks like an overcast afternoon.
 */
function exposureGainFor(logAverage: number, isNight: boolean): number {
  const keyValue = isNight ? 0.022 : 0.16
  // Clamped so a badly authored map cannot drive the scene to black or to a blowout.
  return Math.min(40, Math.max(0.005, keyValue / logAverage))
}

/** Load and cache captured HDRIs, so switching back to one is instant. */
const hdriCache = new Map<string, Promise<LoadedHdri>>()

function loadHdri(url: string): Promise<LoadedHdri> {
  const cached = hdriCache.get(url)
  if (cached) return cached
  // Customer uploads arrive as a signed URL, so the format is taken from the path before
  // the query string rather than from the whole URL.
  const isExr = /\.exr(\?|$)/i.test(url)
  const loader = isExr ? new EXRLoader() : new HDRLoader()
  const pending = new Promise<LoadedHdri>((resolve, reject) => {
    loader.load(
      url,
      (texture) => {
        texture.mapping = THREE.EquirectangularReflectionMapping
        resolve({ texture, logAverage: measureLogAverage(texture) })
      },
      undefined,
      () => reject(new Error(`Could not load the environment map at ${url}.`)),
    )
  })
  hdriCache.set(url, pending)
  return pending
}

function SceneEnvironment({
  environmentId,
  weatherIntensity,
  customHdriUrl,
  onHdriError,
}: {
  environmentId: string
  weatherIntensity: number
  customHdriUrl: string | null
  onHdriError: (message: string | null) => void
}) {
  const store = useStore()
  const preset = useMemo(
    () => applyIntensity(getViewportEnvironment(environmentId), weatherIntensity),
    [environmentId, weatherIntensity],
  )
  // An uploaded map replaces the preset's own, while the preset keeps driving weather,
  // wetness and the sun direction.
  const environment = useMemo(
    () => (customHdriUrl ? { ...preset, hdriUrl: customHdriUrl } : preset),
    [preset, customHdriUrl],
  )

  const sky = useMemo(() => buildSky(environment), [environment])

  // The loaded map is stored alongside the URL it came from. Deriving the active texture
  // by comparing the two means a preset switch takes effect on the very next render,
  // without an extra state write to clear the previous one.
  const [loaded, setLoaded] = useState<{ url: string; hdri: LoadedHdri } | null>(null)
  const hdri = loaded && loaded.url === environment.hdriUrl ? loaded.hdri : null

  // A captured environment replaces the procedural sky entirely. While it downloads the
  // procedural sky stands in, so the viewport is never blank.
  useEffect(() => {
    const url = environment.hdriUrl
    if (!url) {
      onHdriError(null)
      return
    }
    let cancelled = false
    onHdriError(null)
    loadHdri(url)
      .then((result) => {
        if (!cancelled) setLoaded({ url, hdri: result })
      })
      .catch((error: Error) => {
        if (cancelled) return
        onHdriError(`${error.message} Falling back to the procedural sky.`)
      })
    return () => {
      cancelled = true
    }
  }, [environment.hdriUrl, onHdriError])

  useEffect(() => {
    const { scene } = store.getState()
    const active = hdri ? hdri.texture : sky.texture
    scene.background = active
    scene.environment = active
    scene.backgroundRotation = ENVIRONMENT_ROTATION
    scene.environmentRotation = ENVIRONMENT_ROTATION
    // The procedural sky is authored at display brightness already; a captured map is
    // metered from its own measured luminance.
    const gain = hdri ? exposureGainFor(hdri.logAverage, environment.isNight) : 1
    scene.backgroundIntensity = gain
    scene.environmentIntensity = gain
    scene.fog = new THREE.FogExp2(sky.fogColor.getHex(), sky.fogDensity)
    return () => {
      scene.background = null
      scene.environment = null
      scene.fog = null
    }
  }, [store, sky, hdri, environment.isNight])

  // The procedural texture is generated per preset and owned here. Captured maps are
  // cached and shared, so they are deliberately not disposed.
  useEffect(() => () => sky.texture.dispose(), [sky])

  const distance = 400
  return (
    <>
      <directionalLight
        position={[
          sky.sunDirection[0] * distance,
          sky.sunDirection[1] * distance,
          sky.sunDirection[2] * distance,
        ]}
        intensity={hdri ? sky.sunIntensity * 0.35 : sky.sunIntensity}
        color={sky.sunColor}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-160}
        shadow-camera-right={160}
        shadow-camera-top={220}
        shadow-camera-bottom={-60}
        shadow-camera-near={1}
        shadow-camera-far={900}
        shadow-bias={-0.0006}
      />
      {!hdri && (
        <hemisphereLight
          intensity={sky.ambientIntensity}
          color={sky.ambientColor}
          groundColor={sky.fogColor}
        />
      )}
    </>
  )
}

// ─── Weather ──────────────────────────────────────────────────────────────────

function Rain({
  precipitationMmH,
  windSpeed,
  scaleM,
}: {
  precipitationMmH: number
  windSpeed: number
  scaleM: number
}) {
  const random = useMemo(() => mulberry32(0x9e3779b9), [])

  const { geometry, count, volume, fallSpeed, streakLength } = useMemo(() => {
    const intensity = Math.min(1, precipitationMmH / 40)
    const streaks = Math.round(600 + intensity * 3400)
    const box = { x: scaleM * 1.1, y: scaleM * 1.1, z: scaleM * 1.2 }
    const speed = scaleM * (0.18 + intensity * 0.3)
    const length = scaleM * (0.008 + intensity * 0.03)

    const positions = new Float32Array(streaks * 6)
    for (let i = 0; i < streaks; i += 1) {
      const x = (random() - 0.5) * box.x
      const y = (random() - 0.5) * box.y
      const z = random() * box.z
      positions[i * 6] = x
      positions[i * 6 + 1] = y
      positions[i * 6 + 2] = z
      positions[i * 6 + 3] = x
      positions[i * 6 + 4] = y
      positions[i * 6 + 5] = z + length
    }
    const buffer = new THREE.BufferGeometry()
    buffer.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    return { geometry: buffer, count: streaks, volume: box, fallSpeed: speed, streakLength: length }
  }, [precipitationMmH, scaleM, random])

  useEffect(() => () => geometry.dispose(), [geometry])

  const drift = Math.min(scaleM * 0.12, windSpeed * 0.9)

  useFrame((_, delta) => {
    const step = Math.min(delta, 0.05)
    const attribute = geometry.getAttribute('position') as THREE.BufferAttribute
    const array = attribute.array as Float32Array
    const fall = fallSpeed * step
    const sideways = drift * step

    for (let i = 0; i < count; i += 1) {
      const head = i * 6
      const tail = head + 3
      array[head + 2] -= fall
      array[tail + 2] -= fall
      array[head] += sideways
      array[tail] += sideways

      if (array[head + 2] < 0) {
        const x = (random() - 0.5) * volume.x
        const y = (random() - 0.5) * volume.y
        array[head] = x
        array[head + 1] = y
        array[head + 2] = volume.z
        array[tail] = x
        array[tail + 1] = y
        array[tail + 2] = volume.z + streakLength
      }
    }
    attribute.needsUpdate = true
  })

  const intensity = Math.min(1, precipitationMmH / 40)
  return (
    <lineSegments geometry={geometry} frustumCulled={false}>
      <lineBasicMaterial
        color="#cfd8e3"
        transparent
        opacity={0.16 + intensity * 0.3}
        depthWrite={false}
      />
    </lineSegments>
  )
}

/** A soft round dot, drawn once into a tiny canvas and reused by every snowflake. */
function createFlakeTexture(): THREE.Texture {
  const size = 32
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const context = canvas.getContext('2d')
  if (context) {
    const gradient = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
    gradient.addColorStop(0, 'rgba(255,255,255,1)')
    gradient.addColorStop(0.45, 'rgba(255,255,255,0.85)')
    gradient.addColorStop(1, 'rgba(255,255,255,0)')
    context.fillStyle = gradient
    context.fillRect(0, 0, size, size)
  }
  const texture = new THREE.CanvasTexture(canvas)
  texture.needsUpdate = true
  return texture
}

/**
 * Falling snow.
 *
 * Deliberately cheap: a few thousand point sprites in one draw call, a 32 px texture, no
 * depth writes and no lighting. Flakes drift on a sine wave rather than being simulated,
 * which costs two trig calls each and still reads as snow rather than falling dots.
 */
function Snow({
  intensity,
  windSpeed,
  scaleM,
}: {
  intensity: number
  windSpeed: number
  scaleM: number
}) {
  const random = useMemo(() => mulberry32(0x1b873593), [])
  const texture = useMemo(() => createFlakeTexture(), [])
  useEffect(() => () => texture.dispose(), [texture])

  const { geometry, count, volume, phases, fallSpeed } = useMemo(() => {
    // Kept low on purpose: snow must not cost more than the model it falls around.
    const flakes = Math.round(900 + Math.min(1, intensity) * 2100)
    const box = { x: scaleM * 1.0, y: scaleM * 1.0, z: scaleM * 1.1 }
    const positions = new Float32Array(flakes * 3)
    const drift = new Float32Array(flakes * 2)
    const sizes = new Float32Array(flakes)
    for (let i = 0; i < flakes; i += 1) {
      positions[i * 3] = (random() - 0.5) * box.x
      positions[i * 3 + 1] = (random() - 0.5) * box.y
      positions[i * 3 + 2] = random() * box.z
      drift[i * 2] = random() * Math.PI * 2
      drift[i * 2 + 1] = 0.4 + random() * 1.4
      sizes[i] = scaleM * (0.0016 + random() * 0.0032)
    }
    const buffer = new THREE.BufferGeometry()
    buffer.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    buffer.setAttribute('size', new THREE.BufferAttribute(sizes, 1))
    return {
      geometry: buffer,
      count: flakes,
      volume: box,
      phases: drift,
      fallSpeed: scaleM * (0.012 + intensity * 0.022),
    }
  }, [intensity, scaleM, random])

  useEffect(() => () => geometry.dispose(), [geometry])

  const elapsed = useRef(0)
  const gust = Math.min(scaleM * 0.05, windSpeed * 0.5)

  useFrame((_, delta) => {
    const step = Math.min(delta, 0.05)
    elapsed.current += step
    const attribute = geometry.getAttribute('position') as THREE.BufferAttribute
    const array = attribute.array as Float32Array
    const time = elapsed.current

    for (let i = 0; i < count; i += 1) {
      const offset = i * 3
      const phase = phases[i * 2]
      const rate = phases[i * 2 + 1]
      array[offset + 2] -= fallSpeed * rate * step
      // Lateral wander, which is what separates snow from rain visually.
      array[offset] += (Math.sin(time * rate + phase) * 0.35 + gust) * step
      array[offset + 1] += Math.cos(time * rate * 0.7 + phase) * 0.3 * step

      if (array[offset + 2] < 0) {
        array[offset] = (random() - 0.5) * volume.x
        array[offset + 1] = (random() - 0.5) * volume.y
        array[offset + 2] = volume.z
      }
    }
    attribute.needsUpdate = true
  })

  return (
    <points geometry={geometry} frustumCulled={false}>
      <pointsMaterial
        map={texture}
        color="#ffffff"
        size={scaleM * 0.004}
        sizeAttenuation
        transparent
        opacity={0.55 + Math.min(1, intensity) * 0.3}
        depthWrite={false}
        // Snow scatters light rather than blocking it, so it brightens what is behind it.
        blending={THREE.AdditiveBlending}
      />
    </points>
  )
}

// ─── Model ────────────────────────────────────────────────────────────────────

function Turbine({
  model,
  settings,
  wetness,
  paintEnabled,
}: {
  model: LoadedTurbineModel
  settings: ViewportSettings
  wetness: number
  paintEnabled: boolean
}) {
  const whiteMaterial = useMemo(() => {
    const material = createCleanWhiteMaterial(wetness)
    material.wireframe = settings.showWireframe
    return material
  }, [wetness, settings.showWireframe])
  useEffect(() => () => whiteMaterial.dispose(), [whiteMaterial])

  // While painting, always show the clean white coating so colours stay readable —
  // the FBX's own materials can be near-black when textures are missing.
  const showOriginal = settings.useOriginalMaterials && !paintEnabled

  useEffect(() => {
    const originals = new Map<string, THREE.Material | THREE.Material[]>()
    model.object.traverse((child) => {
      const mesh = child as THREE.Mesh
      if (!mesh.isMesh) return
      if (mesh.name.endsWith('-paint-overlay')) return
      originals.set(mesh.uuid, mesh.material)
      if (!showOriginal) mesh.material = whiteMaterial
    })
    return () => {
      model.object.traverse((child) => {
        const mesh = child as THREE.Mesh
        if (!mesh.isMesh) return
        if (mesh.name.endsWith('-paint-overlay')) return
        const original = originals.get(mesh.uuid)
        if (original) mesh.material = original
      })
    }
  }, [model, showOriginal, whiteMaterial])

  useEffect(() => {
    model.object.traverse((child) => {
      const mesh = child as THREE.Mesh
      if (!mesh.isMesh) return
      const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
      for (const material of materials) {
        ;(material as THREE.MeshStandardMaterial).wireframe = settings.showWireframe
      }
    })
  }, [model, settings.showWireframe])

  useEffect(() => {
    applyPartVisibility(model, settings.selectedPartId)
  }, [model, settings.selectedPartId])

  return <primitive object={model.object} />
}

function Ground({ showGrid, extentM }: { showGrid: boolean; extentM: number }) {
  const grid = useMemo(() => {
    const size = Math.ceil(extentM * 2)
    const helper = new THREE.GridHelper(size, Math.max(10, Math.round(size / 20)), 0x3c4a5c, 0x232c38)
    helper.rotation.x = Math.PI / 2
    const material = helper.material as THREE.Material | THREE.Material[]
    for (const entry of Array.isArray(material) ? material : [material]) {
      entry.transparent = true
      entry.opacity = 0.35
      entry.depthWrite = false
    }
    return helper
  }, [extentM])

  useEffect(() => () => grid.dispose(), [grid])

  return (
    <>
      <mesh receiveShadow renderOrder={-1}>
        <planeGeometry args={[extentM * 6, extentM * 6]} />
        <shadowMaterial opacity={0.3} />
      </mesh>
      {showGrid && <primitive object={grid} />}
    </>
  )
}

// ─── Camera and input ─────────────────────────────────────────────────────────

interface ControlsHandle {
  frameAll: () => void
  frameSelection: (centre: [number, number, number], radiusM: number) => void
  setView: (view: StandardView) => void
  reset: () => void
}

function Controls({
  scheme,
  camera: requested,
  onCameraChange,
  onHandle,
  fallbackRadiusM,
  paintMode,
}: {
  scheme: NavigationScheme
  camera: ViewportCamera
  onCameraChange: (camera: ViewportCamera) => void
  onHandle: (handle: ControlsHandle) => void
  fallbackRadiusM: number
  paintMode: boolean
}) {
  const { camera, gl, size } = useThree()
  const store = useStore()

  const schemeRef = useRef(scheme)
  const paintModeRef = useRef(paintMode)
  useEffect(() => {
    schemeRef.current = scheme
  }, [scheme])
  useEffect(() => {
    paintModeRef.current = paintMode
  }, [paintMode])

  const controller = useMemo(
    () =>
      new OrbitCameraController(
        {
          target: [0, 0, DEFAULT_VIEWPORT_CAMERA.targetHeightM],
          azimuthDeg: DEFAULT_VIEWPORT_CAMERA.azimuthDeg,
          elevationDeg: DEFAULT_VIEWPORT_CAMERA.elevationDeg,
          distanceM: DEFAULT_VIEWPORT_CAMERA.distanceM,
        },
        DEFAULT_VIEWPORT_CAMERA.fovDeg,
        { maxDistanceM: 4000 },
      ),
    [],
  )

  // Two-way binding between the sliders and the mouse. `lastEmitted` marks the value this
  // component published; anything different arriving as a prop came from the panel and is
  // applied to the controller, which is what stops the two fighting each other.
  const lastEmitted = useRef<string>('')
  const rollRef = useRef(requested.rollDeg)
  useEffect(() => {
    rollRef.current = requested.rollDeg
  }, [requested.rollDeg])

  const key = (value: ViewportCamera) =>
    [
      value.targetHeightM.toFixed(2),
      value.azimuthDeg.toFixed(2),
      value.elevationDeg.toFixed(2),
      value.distanceM.toFixed(2),
    ].join('|')

  useEffect(() => {
    if (key(requested) === lastEmitted.current) return
    controller.jumpTo({
      target: [0, 0, requested.targetHeightM],
      azimuthDeg: requested.azimuthDeg,
      elevationDeg: requested.elevationDeg,
      distanceM: requested.distanceM,
    })
    lastEmitted.current = key(requested)
  }, [controller, requested])

  useEffect(() => {
    controller.setFov(requested.fovDeg)
    const perspective = store.getState().camera as THREE.PerspectiveCamera
    perspective.fov = requested.fovDeg
    perspective.updateProjectionMatrix()
  }, [controller, store, requested.fovDeg])

  useEffect(() => {
    controller.setAspect(size.width / Math.max(1, size.height))
  }, [controller, size.width, size.height])

  useFrame((_, delta) => {
    controller.advance(delta)
    const [x, y, z] = controller.position
    const state = controller.state
    camera.position.set(x, y, z)
    camera.up.set(0, 0, 1)
    camera.lookAt(state.target[0], state.target[1], state.target[2])
    if (rollRef.current !== 0) {
      // Roll is a rotation about the view axis, applied after aiming.
      camera.rotateZ((rollRef.current * Math.PI) / 180)
    }

    const current = controller.requestedState
    const published: ViewportCamera = {
      targetHeightM: current.target[2],
      azimuthDeg: current.azimuthDeg,
      elevationDeg: current.elevationDeg,
      distanceM: current.distanceM,
      fovDeg: requested.fovDeg,
      rollDeg: rollRef.current,
    }
    const published_key = key(published)
    if (published_key !== lastEmitted.current) {
      lastEmitted.current = published_key
      onCameraChange(published)
    }
  })

  useEffect(() => {
    onHandle({
      frameAll: () => {
        controller.focusOn([0, 0, requested.targetHeightM])
        controller.frame({ centre: [0, 0, fallbackRadiusM * 0.62], radiusM: fallbackRadiusM })
      },
      frameSelection: (centre, radiusM) => controller.frame({ centre, radiusM }, 1.25),
      setView: (view) => controller.setView(view),
      reset: () => controller.reset(),
    })
  }, [controller, onHandle, fallbackRadiusM, requested.targetHeightM])

  useEffect(() => {
    const element = gl.domElement
    let activeAction: ReturnType<typeof resolveAction> = 'none'
    let activePointer: number | null = null
    let lastX = 0
    let lastY = 0

    function onPointerDown(event: PointerEvent) {
      const action = resolveAction(schemeRef.current, {
        button: event.button,
        altKey: event.altKey,
        ctrlKey: event.ctrlKey,
        shiftKey: event.shiftKey,
        metaKey: event.metaKey,
        paintMode: paintModeRef.current,
      })
      if (action === 'none' || action === 'paint') return
      activeAction = action
      activePointer = event.pointerId
      lastX = event.clientX
      lastY = event.clientY
      element.setPointerCapture(event.pointerId)
      event.preventDefault()
    }

    function onPointerMove(event: PointerEvent) {
      if (activePointer !== event.pointerId || activeAction === 'none') return
      const deltaX = event.clientX - lastX
      const deltaY = event.clientY - lastY
      lastX = event.clientX
      lastY = event.clientY
      if (activeAction === 'orbit') controller.orbit(deltaX, deltaY)
      else if (activeAction === 'pan') controller.pan(deltaX, deltaY, element.clientHeight)
      else if (activeAction === 'dolly') controller.dollyByPixels(deltaY)
    }

    function endDrag(event: PointerEvent) {
      if (activePointer !== event.pointerId) return
      activeAction = 'none'
      activePointer = null
      if (element.hasPointerCapture(event.pointerId)) {
        element.releasePointerCapture(event.pointerId)
      }
    }

    function onWheel(event: WheelEvent) {
      event.preventDefault()
      controller.dollyByWheel(event.deltaY)
    }

    function onContextMenu(event: MouseEvent) {
      event.preventDefault()
    }

    element.addEventListener('pointerdown', onPointerDown)
    element.addEventListener('pointermove', onPointerMove)
    element.addEventListener('pointerup', endDrag)
    element.addEventListener('pointercancel', endDrag)
    element.addEventListener('wheel', onWheel, { passive: false })
    element.addEventListener('contextmenu', onContextMenu)
    return () => {
      element.removeEventListener('pointerdown', onPointerDown)
      element.removeEventListener('pointermove', onPointerMove)
      element.removeEventListener('pointerup', endDrag)
      element.removeEventListener('pointercancel', endDrag)
      element.removeEventListener('wheel', onWheel)
      element.removeEventListener('contextmenu', onContextMenu)
    }
  }, [controller, gl])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return
      if (event.metaKey || event.ctrlKey) return
      switch (event.key) {
        case '1':
          controller.setView('front')
          break
        case '3':
          controller.setView('right')
          break
        case '7':
          controller.setView('top')
          break
        case '5':
        case '0':
          controller.setView('perspective')
          break
        case 'r':
        case 'R':
          controller.reset()
          break
        default:
          return
      }
      event.preventDefault()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [controller])

  return null
}

// ─── Overlays ─────────────────────────────────────────────────────────────────

function ViewportMessage({
  icon,
  title,
  detail,
  action,
}: {
  icon: React.ReactNode
  title: string
  detail: string
  action?: { label: string; onClick: () => void }
}) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[#0e1117]/92 px-6 text-center">
      <div className="text-muted-foreground">{icon}</div>
      <p className="text-sm font-medium">{title}</p>
      <p className="max-w-sm text-xs text-muted-foreground">{detail}</p>
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="mt-1 h-8 border border-border px-3 text-xs hover:bg-muted/40"
        >
          {action.label}
        </button>
      )}
    </div>
  )
}

function ToolbarButton({
  active,
  title,
  onClick,
  children,
}: {
  active?: boolean
  title: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      aria-pressed={active}
      onClick={onClick}
      className={`flex h-7 w-7 items-center justify-center border transition-colors ${
        active
          ? 'border-primary/60 bg-primary/15 text-primary'
          : 'border-border/70 bg-background/70 text-muted-foreground hover:text-foreground'
      }`}
    >
      {children}
    </button>
  )
}

const VIEW_BUTTONS: { view: StandardView; label: string; title: string }[] = [
  { view: 'perspective', label: 'P', title: 'Perspective view (0)' },
  { view: 'front', label: 'F', title: 'Front view (1)' },
  { view: 'right', label: 'S', title: 'Side view (3)' },
  { view: 'top', label: 'T', title: 'Top view (7)' },
]

// ─── Public component ─────────────────────────────────────────────────────────

export interface BladeViewportProps {
  settings: ViewportSettings
  onSettingsChange: (settings: ViewportSettings) => void
  camera: ViewportCamera
  onCameraChange: (camera: ViewportCamera) => void
  onModelLoaded?: (model: LoadedTurbineModel | null) => void
  paint?: PaintSettings
  paintStrokes?: readonly BrushStroke[]
  onPaintStroke?: (stroke: BrushStroke) => void
  onPaintChange?: (paint: PaintSettings) => void
  className?: string
}

export function BladeViewport({
  settings,
  onSettingsChange,
  camera,
  onCameraChange,
  onModelLoaded,
  paint = DEFAULT_PAINT_SETTINGS,
  paintStrokes = [],
  onPaintStroke,
  onPaintChange,
  className = '',
}: BladeViewportProps) {
  // Both the model and any failure are stored against the URL they belong to, so
  // switching source resolves on the next render rather than needing a clearing write.
  const [loaded, setLoaded] = useState<{ url: string; model: LoadedTurbineModel } | null>(null)
  const [failure, setFailure] = useState<{ url: string; message: string } | null>(null)
  const [hdriError, setHdriError] = useState<string | null>(null)
  const [contextLost, setContextLost] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const handleRef = useRef<ControlsHandle | null>(null)

  const environment = useMemo(
    () => applyIntensity(getViewportEnvironment(settings.environmentId), settings.weatherIntensity),
    [settings.environmentId, settings.weatherIntensity],
  )

  const url = settings.modelUrl
  const model = loaded && loaded.url === url ? loaded.model : null
  const loadError = failure && failure.url === url ? failure.message : null

  useEffect(() => {
    let cancelled = false
    loadTurbineModel(url)
      .then((result) => {
        if (cancelled) return
        setLoaded({ url, model: result })
        onModelLoaded?.(result)
      })
      .catch((error: Error) => {
        if (cancelled) return
        setFailure({ url, message: error.message })
        onModelLoaded?.(null)
      })
    return () => {
      cancelled = true
    }
  }, [url, onModelLoaded])

  const sceneScaleM = model ? Math.max(40, model.bounds.radiusM * 1.6) : 200
  const selectedPart = model?.parts.find((part) => part.id === settings.selectedPartId)

  const handleHdriError = useCallback((message: string | null) => setHdriError(message), [])

  function attachContextRecovery(canvas: HTMLCanvasElement) {
    canvas.addEventListener('webglcontextlost', (event) => {
      event.preventDefault()
      setContextLost(true)
    })
    canvas.addEventListener('webglcontextrestored', () => setContextLost(false))
  }

  const update = (patch: Partial<ViewportSettings>) => onSettingsChange({ ...settings, ...patch })

  return (
    <div className={`relative h-full w-full overflow-hidden bg-[#0e1117] ${className}`}>
      <Canvas
        shadows
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: false, preserveDrawingBuffer: true }}
        camera={{
          fov: camera.fovDeg,
          near: 0.1,
          far: 20000,
          position: [200, -200, 120],
          up: [0, 0, 1],
        }}
        onCreated={({ gl, scene }) => {
          gl.toneMapping = THREE.ACESFilmicToneMapping
          gl.toneMappingExposure = 1
          gl.outputColorSpace = THREE.SRGBColorSpace
          scene.up.set(0, 0, 1)
          attachContextRecovery(gl.domElement)
        }}
      >
        <Suspense fallback={null}>
          <SceneEnvironment
            environmentId={settings.environmentId}
            weatherIntensity={settings.weatherIntensity}
            customHdriUrl={settings.customHdriUrl}
            onHdriError={handleHdriError}
          />
          {model && (
            <Turbine
              model={model}
              settings={settings}
              wetness={environment.wetness}
              paintEnabled={paint.enabled}
            />
          )}
          <Ground showGrid={settings.showGrid} extentM={sceneScaleM} />
          {environment.precipitationMmH > 0.1 && (
            <Rain
              precipitationMmH={environment.precipitationMmH}
              windSpeed={environment.windSpeedMs}
              scaleM={sceneScaleM}
            />
          )}
          {(environment.snowIntensity ?? 0) > 0.02 && (
            <Snow
              intensity={environment.snowIntensity ?? 0}
              windSpeed={environment.windSpeedMs}
              scaleM={sceneScaleM}
            />
          )}
          <Controls
            scheme={settings.navigationScheme}
            camera={camera}
            onCameraChange={onCameraChange}
            onHandle={(handle) => {
              handleRef.current = handle
            }}
            fallbackRadiusM={model?.bounds.radiusM ?? 120}
            paintMode={paint.enabled}
          />
          {model && onPaintStroke && (
            <RegionPainter
              paint={paint}
              strokes={paintStrokes}
              onStrokeComplete={onPaintStroke}
              target={model.object}
            />
          )}
        </Suspense>
      </Canvas>

      <div className="pointer-events-none absolute left-3 top-3 flex flex-col gap-0.5">
        <span className="font-mono text-[10px] uppercase tracking-widest text-primary/70">
          {selectedPart?.displayName ?? 'Turbine'}
        </span>
        <span className="font-mono text-[10px] text-muted-foreground">
          {model
            ? `${(model.bounds.max[2] - model.bounds.min[2]).toFixed(0)} m tall · ${model.triangleCount.toLocaleString()} tris`
            : 'loading model'}
          {' · '}
          {environment.label}
        </span>
      </div>

      <div className="absolute right-3 top-3 flex flex-col items-end gap-2">
        <div className="flex gap-1">
          {VIEW_BUTTONS.map((entry) => (
            <button
              key={entry.view}
              type="button"
              title={entry.title}
              onClick={() => handleRef.current?.setView(entry.view)}
              className="flex h-7 w-7 items-center justify-center border border-border/70 bg-background/70 font-mono text-[10px] text-muted-foreground transition-colors hover:text-foreground"
            >
              {entry.label}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          <ToolbarButton
            title="Frame the selected part"
            onClick={() => {
              if (selectedPart?.bounds) {
                handleRef.current?.frameSelection(
                  selectedPart.bounds.centre,
                  selectedPart.bounds.radiusM,
                )
              } else {
                handleRef.current?.frameAll()
              }
            }}
          >
            <Maximize2 className="h-3.5 w-3.5" />
          </ToolbarButton>
          <ToolbarButton title="Reset camera (R)" onClick={() => handleRef.current?.reset()}>
            <RotateCcw className="h-3.5 w-3.5" />
          </ToolbarButton>
          <ToolbarButton
            title="Toggle grid"
            active={settings.showGrid}
            onClick={() => update({ showGrid: !settings.showGrid })}
          >
            <Grid2x2 className="h-3.5 w-3.5" />
          </ToolbarButton>
          <ToolbarButton
            title="Toggle wireframe"
            active={settings.showWireframe}
            onClick={() => update({ showWireframe: !settings.showWireframe })}
          >
            <Box className="h-3.5 w-3.5" />
          </ToolbarButton>
          <ToolbarButton
            title="Use the model's own materials instead of the clean white coating"
            active={settings.useOriginalMaterials}
            onClick={() => update({ useOriginalMaterials: !settings.useOriginalMaterials })}
          >
            <Palette className="h-3.5 w-3.5" />
          </ToolbarButton>
          {onPaintChange && (
            <ToolbarButton
              title={
                paint.enabled
                  ? 'Exit paint mode (middle-drag still orbits)'
                  : 'Paint defect regions on the model'
              }
              active={paint.enabled}
              onClick={() => {
                const next = !paint.enabled
                onPaintChange({ ...paint, enabled: next })
                if (next && settings.useOriginalMaterials) {
                  update({ useOriginalMaterials: false })
                }
              }}
            >
              <Paintbrush className="h-3.5 w-3.5" />
            </ToolbarButton>
          )}
        </div>
      </div>

      <div className="absolute bottom-3 left-3 flex items-center gap-2">
        <select
          value={settings.navigationScheme}
          onChange={(event) => update({ navigationScheme: event.target.value as NavigationScheme })}
          title="Mouse navigation style"
          className="h-7 border border-border/70 bg-background/80 px-2 text-[10px] text-muted-foreground focus:outline-none"
        >
          <option value="blender">Blender navigation</option>
          <option value="maya">Maya navigation</option>
          <option value="simple">Simple navigation</option>
        </select>
        <button
          type="button"
          onClick={() => setShowHelp((value) => !value)}
          className="flex h-7 items-center gap-1 border border-border/70 bg-background/80 px-2 text-[10px] text-muted-foreground hover:text-foreground"
        >
          <Crosshair className="h-3 w-3" />
          Controls
        </button>
        {showHelp && (
          <div className="absolute bottom-9 left-0 w-60 border border-border bg-popover/95 p-2.5 backdrop-blur">
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {settings.navigationScheme} navigation
            </p>
            <dl className="space-y-1">
              {describeScheme(settings.navigationScheme).map((row) => (
                <div key={row.action} className="flex justify-between gap-3">
                  <dt className="text-[10px] text-muted-foreground">{row.action}</dt>
                  <dd className="font-mono text-[10px] text-foreground">{row.binding}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>

      <div className="pointer-events-none absolute bottom-3 right-3 text-right font-mono text-[10px] leading-relaxed text-muted-foreground">
        <div>
          yaw {camera.azimuthDeg.toFixed(0)}° · pitch {camera.elevationDeg.toFixed(0)}° · roll{' '}
          {camera.rollDeg.toFixed(0)}°
        </div>
        <div>
          {camera.distanceM.toFixed(0)} m out · {camera.targetHeightM.toFixed(0)} m up ·{' '}
          {camera.fovDeg.toFixed(0)}° fov
        </div>
      </div>

      {hdriError && (
        <div className="absolute left-1/2 top-3 -translate-x-1/2 border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-[10px] text-amber-300">
          {hdriError}
        </div>
      )}

      {!model && !loadError && !contextLost && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading turbine model…
          </div>
        </div>
      )}

      {loadError && (
        <ViewportMessage
          icon={<TriangleAlert className="h-7 w-7" />}
          title="The model could not be loaded"
          detail={loadError}
        />
      )}

      {contextLost && (
        <ViewportMessage
          icon={<Axis3d className="h-7 w-7" />}
          title="3D context was lost"
          detail="The graphics driver reset the WebGL context, usually after a GPU switch or sleep. The viewport recovers automatically; reload if it does not."
          action={{ label: 'Reload viewport', onClick: () => window.location.reload() }}
        />
      )}
    </div>
  )
}
