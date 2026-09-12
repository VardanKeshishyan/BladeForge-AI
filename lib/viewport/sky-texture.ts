/**
 * Procedural equirectangular sky, generated in the browser.
 *
 * This exists instead of downloading HDRI files for two reasons. Legally, every asset in
 * the product needs a recorded source and licence, and a CDN fetch has neither. In
 * practice it also means the viewport lights itself correctly offline and on first load,
 * with no multi-megabyte texture download before the customer sees anything.
 *
 * The output is a float RGBA equirect used both as the visible background and as the
 * environment map for image-based lighting, so reflections on the blade come from the
 * same sky you can see behind it.
 */

import * as THREE from 'three'

import { kelvinToRgb, type ViewportEnvironment } from './environments'

const WIDTH = 256
const HEIGHT = 128

/** Deterministic hash, so the same environment always produces the same sky. */
function hash2(x: number, y: number, seed: number): number {
  let h = x * 374761393 + y * 668265263 + seed * 1274126177
  h = (h ^ (h >>> 13)) * 1274126177
  return ((h ^ (h >>> 16)) & 0x7fffffff) / 0x7fffffff
}

function smoothNoise(x: number, y: number, seed: number): number {
  const xi = Math.floor(x)
  const yi = Math.floor(y)
  const xf = x - xi
  const yf = y - yi
  const u = xf * xf * (3 - 2 * xf)
  const v = yf * yf * (3 - 2 * yf)
  const a = hash2(xi, yi, seed)
  const b = hash2(xi + 1, yi, seed)
  const c = hash2(xi, yi + 1, seed)
  const d = hash2(xi + 1, yi + 1, seed)
  return a * (1 - u) * (1 - v) + b * u * (1 - v) + c * (1 - u) * v + d * u * v
}

/** Layered noise, which gives cloud edges detail at more than one scale. */
function fbm(x: number, y: number, seed: number, octaves = 4): number {
  let value = 0
  let amplitude = 0.5
  let frequency = 1
  let normalisation = 0
  for (let i = 0; i < octaves; i += 1) {
    value += amplitude * smoothNoise(x * frequency, y * frequency, seed + i * 17)
    normalisation += amplitude
    amplitude *= 0.5
    frequency *= 2.15
  }
  return value / normalisation
}

export interface SkyResult {
  texture: THREE.DataTexture
  /** Sun direction in the Z-up frame, for placing the directional light. */
  sunDirection: [number, number, number]
  sunColor: THREE.Color
  /** Watts, mapped into a directional-light intensity that reads correctly on screen. */
  sunIntensity: number
  ambientColor: THREE.Color
  ambientIntensity: number
  /** Linear fog density derived from haze and visibility. */
  fogColor: THREE.Color
  fogDensity: number
}

/**
 * Build the sky for one environment preset.
 *
 * Caller owns the returned texture and must dispose it when the environment changes.
 */
export function buildSky(environment: ViewportEnvironment): SkyResult {
  const data = new Float32Array(WIDTH * HEIGHT * 4)

  const sunElevation = (environment.sunElevationDeg * Math.PI) / 180
  const sunAzimuth = (environment.sunAzimuthDeg * Math.PI) / 180
  const sunDirection: [number, number, number] = [
    Math.cos(sunElevation) * Math.cos(sunAzimuth),
    Math.cos(sunElevation) * Math.sin(sunAzimuth),
    Math.sin(sunElevation),
  ]

  const [sunR, sunG, sunB] = kelvinToRgb(environment.sunColorK)
  const [ambientR, ambientG, ambientB] = kelvinToRgb(environment.ambientColorK)

  // Turbidity whitens and brightens the horizon while desaturating the zenith, which is
  // the visible signature of a hazier atmosphere.
  const turbidity = Math.min(12, Math.max(1, environment.skyTurbidity))
  const turbidityMix = (turbidity - 1) / 11

  // Turbidity sets the colour, brightness sets the level. Separating them is what keeps
  // a storm dark and a hazy marine sky bright even though both scatter heavily.
  const level = environment.skyBrightness
  const zenith: [number, number, number] = environment.isNight
    ? [0.008 * level, 0.014 * level, 0.032 * level]
    : [
        (0.09 + 0.30 * turbidityMix) * level,
        (0.19 + 0.30 * turbidityMix) * level,
        (0.52 - 0.06 * turbidityMix) * level,
      ]
  const horizon: [number, number, number] = environment.isNight
    ? [0.020 * level, 0.026 * level, 0.046 * level]
    : [
        (0.52 + 0.30 * turbidityMix) * level,
        (0.60 + 0.24 * turbidityMix) * level,
        (0.72 + 0.10 * turbidityMix) * level,
      ]

  // Haze takes the colour of the sky it sits in, so it washes a bright marine scene out
  // to white and a storm out to dark grey, instead of always lifting towards white.
  const horizonLuminance = horizon[0] * 0.2126 + horizon[1] * 0.7152 + horizon[2] * 0.0722

  const seed = Math.round(environment.sunAzimuthDeg + environment.skyTurbidity * 31)
  const cloudCover = environment.cloudCover
  const haze = environment.hazeDensity

  // Each preset carries an exposure offset, which is what keeps the night sky visible
  // and stops the storm sky from clipping. Baking it into the texture means the scene's
  // background and environment intensity can both stay at their defaults.
  const exposure = Math.pow(2, environment.exposureEv)
  const skyExposure = Math.min(3, exposure * (environment.isNight ? 1.0 : 0.85))

  for (let y = 0; y < HEIGHT; y += 1) {
    // Three.js samples an equirectangular map with `u = atan2(d.z, d.x)` and
    // `v = asin(d.y)`, measured in its own Y-up frame, and row 0 of a DataTexture is
    // v = 0. Generating the texture against that exact convention — rather than against
    // this scene's Z-up frame — is what stops the horizon landing vertically and leaving
    // half the sky showing ground.
    const v = (y + 0.5) / HEIGHT
    const latitude = (v - 0.5) * Math.PI
    const ringRadius = Math.cos(latitude)
    const sampleY = Math.sin(latitude)

    for (let x = 0; x < WIDTH; x += 1) {
      const u = (x + 0.5) / WIDTH
      const longitude = (u - 0.5) * Math.PI * 2
      const sampleX = ringRadius * Math.cos(longitude)
      const sampleZ = ringRadius * Math.sin(longitude)

      // The scene applies ENVIRONMENT_ROTATION to stand equirectangular maps upright in
      // this Z-up world, so undo it here to recover the direction this texel is seen at.
      const dirX = sampleX
      const dirY = -sampleZ
      const dirZ = sampleY

      // Height above the horizon, 0 at the horizon and 1 at the zenith.
      const altitude = Math.max(0, dirZ)

      // Vertical gradient, biased so most of the visible sky is the mid tone.
      const gradient = Math.pow(altitude, 0.42)
      let r = horizon[0] + (zenith[0] - horizon[0]) * gradient
      let g = horizon[1] + (zenith[1] - horizon[1]) * gradient
      let b = horizon[2] + (zenith[2] - horizon[2]) * gradient

      // Below the horizon, ground bounce. The camera usually looks down at the blade, so
      // this fills most of the frame and has to track the sky rather than sit near black:
      // a bright overcast day lights the ground brightly, a moonlit night does not.
      if (dirZ < 0) {
        const depth = Math.min(1, -dirZ * 2.2)
        const skyLuminance = horizon[0] * 0.2126 + horizon[1] * 0.7152 + horizon[2] * 0.0722
        const albedo = environment.isNight ? 0.16 : 0.34
        const ground = skyLuminance * albedo
        r = r * (1 - depth) + ground * 1.02 * depth
        g = g * (1 - depth) + ground * 1.0 * depth
        b = b * (1 - depth) + ground * 0.94 * depth
      }

      const sunDot = dirX * sunDirection[0] + dirY * sunDirection[1] + dirZ * sunDirection[2]

      if (!environment.isNight) {
        // Forward-scattering glow around the sun, wider in a hazier sky.
        const glowWidth = 3.5 + turbidity * 1.6 + cloudCover * 22
        const glow = Math.pow(Math.max(0, sunDot), glowWidth)
        const glowStrength = 1.6 * (1 - cloudCover * 0.65)
        r += sunR * glow * glowStrength
        g += sunG * glow * glowStrength
        b += sunB * glow * glowStrength
      }

      // The disc itself. A large angular diameter is how the overcast and storm presets
      // become a broad soft source rather than a point.
      const angularRadius = (environment.sunAngularDiameterDeg * Math.PI) / 360
      const angle = Math.acos(Math.min(1, Math.max(-1, sunDot)))
      if (angle < angularRadius) {
        const falloff = 1 - angle / Math.max(1e-4, angularRadius)
        const discIntensity = environment.isNight ? 2.5 : 14 * (1 - cloudCover * 0.8)
        const weight = Math.pow(falloff, 0.55) * discIntensity
        r += sunR * weight
        g += sunG * weight
        b += sunB * weight
      }

      if (cloudCover > 0.02 && dirZ > -0.05) {
        // Project onto a flat cloud plane so the cells stretch towards the horizon the
        // way real cloud decks do, instead of looking like a painted dome.
        const planeScale = 2.6 / Math.max(0.12, altitude + 0.12)
        const cloudNoise = fbm(
          dirX * planeScale * 2.4 + 11.3,
          dirY * planeScale * 2.4 + 4.7,
          seed,
          4,
        )
        // Cover sets the threshold, so raising it grows the cloud rather than fading it.
        const threshold = 1 - cloudCover
        const density = Math.max(0, cloudNoise - threshold * 0.92) / Math.max(0.06, 1 - threshold * 0.92)
        const coverage = Math.min(1, density * (0.65 + cloudCover * 1.1))
        if (coverage > 0) {
          // Clouds are lit from the sun side and grey where they are thick.
          const lit = 0.55 + 0.45 * Math.max(0, sunDot)
          const thickness = Math.min(1, cloudCover * 1.15)
          const base = (environment.isNight ? 0.02 : 0.86 - 0.5 * thickness) * level
          const cloudR = base * lit * (environment.isNight ? 0.8 : 1)
          const cloudG = base * lit * 0.99
          const cloudB = base * lit * (environment.isNight ? 1.15 : 1.02)
          const blend = coverage * (dirZ < 0 ? Math.max(0, 1 + dirZ * 20) : 1)
          r = r * (1 - blend) + cloudR * blend
          g = g * (1 - blend) + cloudG * blend
          b = b * (1 - blend) + cloudB * blend
        }
      }

      if (environment.isNight) {
        // Sparse stars, thinned out where cloud covers them.
        const starField = hash2(x, y, seed + 991)
        if (starField > 0.9975 - cloudCover * 0.002) {
          const brightness = (starField - 0.9975) * 380 * (1 - cloudCover)
          r += brightness
          g += brightness
          b += brightness * 1.1
        }
      }

      if (haze > 0.01) {
        // Haze lifts and desaturates the lower sky, which is what kills distance contrast.
        const hazeWeight = haze * Math.pow(1 - altitude, 1.7)
        const grey = (r + g + b) / 3
        const hazeTint = horizonLuminance * 0.92
        r = r * (1 - hazeWeight) + (grey * 0.3 + hazeTint * 0.7) * hazeWeight
        g = g * (1 - hazeWeight) + (grey * 0.3 + hazeTint * 0.7) * hazeWeight
        b = b * (1 - hazeWeight) + (grey * 0.3 + hazeTint * 0.73) * hazeWeight
      }

      // Reduced colour response at night, applied last so it affects everything.
      if (environment.colorResponse < 1) {
        const grey = r * 0.2126 + g * 0.7152 + b * 0.0722
        const k = environment.colorResponse
        r = grey + (r - grey) * k
        g = grey + (g - grey) * k
        b = grey + (b - grey) * k
      }

      const offset = (y * WIDTH + x) * 4
      data[offset] = Math.max(0, r) * skyExposure
      data[offset + 1] = Math.max(0, g) * skyExposure
      data[offset + 2] = Math.max(0, b) * skyExposure
      data[offset + 3] = 1
    }
  }

  const texture = new THREE.DataTexture(data, WIDTH, HEIGHT, THREE.RGBAFormat, THREE.FloatType)
  texture.mapping = THREE.EquirectangularReflectionMapping
  texture.colorSpace = THREE.LinearSRGBColorSpace
  texture.minFilter = THREE.LinearFilter
  texture.magFilter = THREE.LinearFilter
  texture.generateMipmaps = false
  texture.needsUpdate = true

  // Map physical-ish watt values into intensities that behave on screen.
  const sunIntensity = Math.min(9, (environment.sunStrength / 620) * exposure * 3.1)
  const ambientIntensity = Math.min(4.5, environment.worldStrength * exposure * 0.5)

  const fogColor = new THREE.Color(
    horizon[0] * 0.85 + 0.1,
    horizon[1] * 0.85 + 0.1,
    horizon[2] * 0.85 + 0.1,
  )
  if (environment.isNight) fogColor.setRGB(0.02, 0.026, 0.05)

  return {
    texture,
    sunDirection,
    sunColor: new THREE.Color(sunR, sunG, sunB),
    sunIntensity,
    ambientColor: new THREE.Color(ambientR, ambientG, ambientB),
    ambientIntensity,
    fogColor,
    // Exponential fog tuned so the stated visibility is roughly where contrast is lost.
    fogDensity:
      Math.max(0, 2.6 / Math.max(200, environment.visibilityM)) *
      (0.35 + environment.hazeDensity * 2.4),
  }
}
