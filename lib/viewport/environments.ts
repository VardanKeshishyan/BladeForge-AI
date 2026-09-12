/**
 * Environment and weather presets for the viewport.
 *
 * Mirrors `bladeforge_core.environments`, reduced to the parameters that change what you
 * see: sun position and colour, sky brightness and turbidity, cloud cover, haze,
 * wetness, and exposure. The backend stays authoritative for rendering; these values
 * drive the interactive preview so the customer sees the lighting they picked before
 * spending a render on it.
 */

export interface ViewportEnvironment {
  id: string
  label: string
  summary: string
  /** Grouping used by the picker. */
  group: 'Captured' | 'Daylight' | 'Low light' | 'Marine' | 'Wet weather' | 'Winter'
  sunElevationDeg: number
  sunAzimuthDeg: number
  /** Apparent diameter of the light source. Large means soft shadows. */
  sunAngularDiameterDeg: number
  sunStrength: number
  sunColorK: number
  skyTurbidity: number
  /**
   * How bright the sky dome itself is, independent of turbidity. Turbidity alone would
   * make a storm sky the brightest of all, because thick air scatters the most light.
   */
  skyBrightness: number
  worldStrength: number
  ambientColorK: number
  exposureEv: number
  cloudCover: number
  hazeDensity: number
  wetness: number
  precipitationMmH: number
  /** Drives rain slant and, in the renderer, camera stability. */
  windSpeedMs: number
  visibilityM: number
  isNight: boolean
  /** Desaturation applied at night, standing in for reduced colour response. */
  colorResponse: number
  /**
   * A real captured environment. When present it replaces the procedural sky for both
   * the backdrop and the lighting, which is what makes reflections look photographed
   * rather than computed.
   */
  hdriUrl?: string
  /** Attribution and terms, recorded because every asset needs a traceable licence. */
  hdriCredit?: string
  /** Snowfall, 0 to 1. Kept separate from rain because it falls and scatters differently. */
  snowIntensity?: number
}

export const VIEWPORT_ENVIRONMENTS: ViewportEnvironment[] = [
  {
    id: 'DESERT_CLEAR_V1',
    label: 'Desert (HDRI)',
    summary: 'Captured desert sky. Real sun, real reflections.',
    group: 'Captured',
    sunElevationDeg: 46,
    sunAzimuthDeg: 128,
    sunAngularDiameterDeg: 0.6,
    sunStrength: 900,
    sunColorK: 5400,
    skyTurbidity: 3.2,
    skyBrightness: 1.0,
    worldStrength: 1.3,
    ambientColorK: 9500,
    exposureEv: -0.2,
    cloudCover: 0.1,
    hazeDensity: 0.06,
    wetness: 0,
    precipitationMmH: 0,
    windSpeedMs: 5.0,
    visibilityM: 30000,
    isNight: false,
    colorResponse: 1,
    hdriUrl: '/assets/hdri/desert.hdr',
    hdriCredit: 'hdrmaps.com free sample, supplied by the customer for use in this product.',
  },
  {
    id: 'MOONLIGHT_HDRI_V1',
    label: 'Moonlight (HDRI)',
    summary: 'Captured night sky with real moonlight and stars.',
    group: 'Captured',
    sunElevationDeg: 40,
    sunAzimuthDeg: 205,
    sunAngularDiameterDeg: 0.52,
    sunStrength: 0.02,
    sunColorK: 4300,
    skyTurbidity: 2,
    skyBrightness: 1.0,
    worldStrength: 0.05,
    ambientColorK: 11000,
    exposureEv: 3.4,
    cloudCover: 0.1,
    hazeDensity: 0.02,
    wetness: 0.04,
    precipitationMmH: 0,
    windSpeedMs: 3.5,
    visibilityM: 14000,
    isNight: true,
    colorResponse: 0.7,
    hdriUrl: '/assets/hdri/moon-light.hdr',
    hdriCredit: 'NightSkyHDRI003, supplied by the customer for use in this product.',
  },
  {
    id: 'LIGHT_SNOW_V1',
    label: 'Light snow',
    summary: 'Drifting snow, overcast light, cold cast.',
    group: 'Winter',
    sunElevationDeg: 24,
    sunAzimuthDeg: 155,
    sunAngularDiameterDeg: 38,
    sunStrength: 150,
    sunColorK: 7600,
    skyTurbidity: 8,
    skyBrightness: 1.05,
    worldStrength: 2.4,
    ambientColorK: 8600,
    exposureEv: 0.2,
    cloudCover: 0.85,
    hazeDensity: 0.14,
    wetness: 0.18,
    precipitationMmH: 0,
    windSpeedMs: 6.0,
    visibilityM: 9000,
    isNight: false,
    colorResponse: 0.93,
    snowIntensity: 0.35,
  },
  {
    id: 'SNOW_STORM_V1',
    label: 'Snow storm',
    summary: 'Heavy wind-driven snow and low visibility.',
    group: 'Winter',
    sunElevationDeg: 20,
    sunAzimuthDeg: 170,
    sunAngularDiameterDeg: 55,
    sunStrength: 60,
    sunColorK: 7900,
    skyTurbidity: 10,
    skyBrightness: 0.78,
    worldStrength: 1.5,
    ambientColorK: 8200,
    exposureEv: 0.35,
    cloudCover: 0.97,
    hazeDensity: 0.4,
    wetness: 0.3,
    precipitationMmH: 0,
    windSpeedMs: 20.0,
    visibilityM: 1200,
    isNight: false,
    colorResponse: 0.88,
    snowIntensity: 1,
  },
  {
    id: 'CLEAR_DAY_V1',
    label: 'Clear day',
    summary: 'High sun, hard shadows, clean sky.',
    group: 'Daylight',
    sunElevationDeg: 52,
    sunAzimuthDeg: 135,
    sunAngularDiameterDeg: 0.53,
    sunStrength: 1000,
    sunColorK: 5600,
    skyTurbidity: 2.4,
    skyBrightness: 1.05,
    worldStrength: 1.0,
    ambientColorK: 11000,
    exposureEv: 0,
    cloudCover: 0.08,
    hazeDensity: 0.02,
    wetness: 0,
    precipitationMmH: 0,
    windSpeedMs: 6.0,
    visibilityM: 40000,
    isNight: false,
    colorResponse: 1,
  },
  {
    id: 'OVERCAST_DAY_V1',
    label: 'Overcast',
    summary: 'Bright cloud dome, soft shadows, low contrast.',
    group: 'Daylight',
    sunElevationDeg: 44,
    sunAzimuthDeg: 150,
    sunAngularDiameterDeg: 42,
    sunStrength: 130,
    sunColorK: 6800,
    skyTurbidity: 8.5,
    skyBrightness: 0.92,
    worldStrength: 2.6,
    ambientColorK: 7200,
    exposureEv: 0.2,
    cloudCover: 0.92,
    hazeDensity: 0.05,
    wetness: 0.02,
    precipitationMmH: 0,
    windSpeedMs: 8.0,
    visibilityM: 18000,
    isNight: false,
    colorResponse: 0.97,
  },
  {
    id: 'CLOUDY_DAY_V1',
    label: 'Broken cloud',
    summary: 'Partial direct sun and an uneven sky.',
    group: 'Daylight',
    sunElevationDeg: 40,
    sunAzimuthDeg: 120,
    sunAngularDiameterDeg: 8,
    sunStrength: 470,
    sunColorK: 6100,
    skyTurbidity: 5.5,
    skyBrightness: 1.0,
    worldStrength: 1.7,
    ambientColorK: 8200,
    exposureEv: 0.1,
    cloudCover: 0.6,
    hazeDensity: 0.04,
    wetness: 0.04,
    precipitationMmH: 0,
    windSpeedMs: 9.5,
    visibilityM: 25000,
    isNight: false,
    colorResponse: 0.99,
  },
  {
    id: 'GOLDEN_HOUR_V1',
    label: 'Golden hour',
    summary: 'Low warm sun, long shadows, cool ambient.',
    group: 'Low light',
    sunElevationDeg: 7,
    sunAzimuthDeg: 265,
    sunAngularDiameterDeg: 0.6,
    sunStrength: 420,
    sunColorK: 3300,
    skyTurbidity: 4.5,
    skyBrightness: 0.72,
    worldStrength: 0.75,
    ambientColorK: 9500,
    exposureEv: 0.35,
    cloudCover: 0.2,
    hazeDensity: 0.08,
    wetness: 0.02,
    precipitationMmH: 0,
    windSpeedMs: 4.5,
    visibilityM: 22000,
    isNight: false,
    colorResponse: 1,
  },
  {
    id: 'NIGHT_MOONLIT_V1',
    label: 'Moonlit night',
    summary: 'Moonlight only, high sensor noise, muted colour.',
    group: 'Low light',
    sunElevationDeg: 34,
    sunAzimuthDeg: 200,
    sunAngularDiameterDeg: 0.52,
    sunStrength: 0.0015,
    sunColorK: 4100,
    skyTurbidity: 2,
    skyBrightness: 1.0,
    worldStrength: 0.004,
    ambientColorK: 12000,
    exposureEv: 6.5,
    cloudCover: 0.15,
    hazeDensity: 0.03,
    wetness: 0.06,
    precipitationMmH: 0,
    windSpeedMs: 4.0,
    visibilityM: 12000,
    isNight: true,
    colorResponse: 0.55,
  },
  {
    id: 'OFFSHORE_HAZE_V1',
    label: 'Offshore haze',
    summary: 'Marine haze, reduced distance contrast, salt film.',
    group: 'Marine',
    sunElevationDeg: 36,
    sunAzimuthDeg: 110,
    sunAngularDiameterDeg: 5,
    sunStrength: 520,
    sunColorK: 6400,
    skyTurbidity: 7,
    skyBrightness: 0.88,
    worldStrength: 1.9,
    ambientColorK: 8000,
    exposureEv: 0.15,
    cloudCover: 0.35,
    hazeDensity: 0.55,
    wetness: 0.15,
    precipitationMmH: 0,
    windSpeedMs: 11.0,
    visibilityM: 3200,
    isNight: false,
    colorResponse: 0.94,
  },
  {
    id: 'LIGHT_RAIN_WET_V1',
    label: 'Light rain',
    summary: 'Moderate rain, wet reflective surface.',
    group: 'Wet weather',
    sunElevationDeg: 34,
    sunAzimuthDeg: 160,
    sunAngularDiameterDeg: 34,
    sunStrength: 110,
    sunColorK: 6900,
    skyTurbidity: 9,
    skyBrightness: 0.55,
    worldStrength: 1.5,
    ambientColorK: 7000,
    exposureEv: 0.4,
    cloudCover: 0.88,
    hazeDensity: 0.18,
    wetness: 0.65,
    precipitationMmH: 3.2,
    windSpeedMs: 9.0,
    visibilityM: 6000,
    isNight: false,
    colorResponse: 0.95,
  },
  {
    id: 'HEAVY_RAIN_STORM_V1',
    label: 'Heavy storm',
    summary: 'Dense rain, poor visibility, unstable camera.',
    group: 'Wet weather',
    sunElevationDeg: 26,
    sunAzimuthDeg: 175,
    sunAngularDiameterDeg: 55,
    sunStrength: 42,
    sunColorK: 7400,
    skyTurbidity: 11,
    skyBrightness: 0.26,
    worldStrength: 0.85,
    ambientColorK: 6600,
    exposureEv: 0.3,
    cloudCover: 0.98,
    hazeDensity: 0.45,
    wetness: 0.91,
    precipitationMmH: 38,
    windSpeedMs: 24.0,
    visibilityM: 900,
    isNight: false,
    colorResponse: 0.9,
  },
  {
    id: 'POST_RAIN_WET_V1',
    label: 'Post-rain',
    summary: 'Rain stopped, surfaces still wet and reflective.',
    group: 'Wet weather',
    sunElevationDeg: 38,
    sunAzimuthDeg: 140,
    sunAngularDiameterDeg: 14,
    sunStrength: 400,
    sunColorK: 6300,
    skyTurbidity: 6,
    skyBrightness: 0.8,
    worldStrength: 1.9,
    ambientColorK: 7800,
    exposureEv: 0.05,
    cloudCover: 0.55,
    hazeDensity: 0.06,
    wetness: 0.8,
    precipitationMmH: 0,
    windSpeedMs: 6.5,
    visibilityM: 16000,
    isNight: false,
    colorResponse: 0.96,
  },
]

export const DEFAULT_ENVIRONMENT_ID = 'DESERT_CLEAR_V1'

export function getViewportEnvironment(id: string): ViewportEnvironment {
  return (
    VIEWPORT_ENVIRONMENTS.find((entry) => entry.id === id) ??
    VIEWPORT_ENVIRONMENTS.find((entry) => entry.id === DEFAULT_ENVIRONMENT_ID)!
  )
}

/**
 * Blend a preset towards its harsher end, mirroring the single intensity control the
 * customer sees. Zero is the mildest form of the preset, one is the most extreme.
 */
export function applyIntensity(
  environment: ViewportEnvironment,
  intensity: number,
): ViewportEnvironment {
  const t = Math.min(1, Math.max(0, intensity))
  // Only conditions that a customer would call "more intense" scale here. Sun position
  // is not one of them, so it stays put.
  const scale = (base: number, extreme: number) => base + (extreme - base) * t
  return {
    ...environment,
    cloudCover: Math.min(1, scale(environment.cloudCover * 0.85, Math.min(1, environment.cloudCover * 1.08))),
    hazeDensity: scale(environment.hazeDensity * 0.6, environment.hazeDensity * 1.5),
    wetness: Math.min(1, scale(environment.wetness * 0.75, Math.min(1, environment.wetness * 1.12))),
    precipitationMmH: scale(environment.precipitationMmH * 0.45, environment.precipitationMmH * 1.4),
    snowIntensity:
      environment.snowIntensity === undefined
        ? undefined
        : Math.min(1, scale(environment.snowIntensity * 0.4, environment.snowIntensity * 1.3)),
    visibilityM: scale(environment.visibilityM * 1.6, environment.visibilityM * 0.6),
    sunStrength: scale(environment.sunStrength * 1.15, environment.sunStrength * 0.8),
  }
}

/** Approximate blackbody colour, used for both the sun and the ambient tint. */
export function kelvinToRgb(kelvin: number): [number, number, number] {
  const temperature = Math.min(20000, Math.max(1000, kelvin)) / 100
  let red: number
  let green: number
  let blue: number

  if (temperature <= 66) {
    red = 255
    green = 99.4708025861 * Math.log(temperature) - 161.1195681661
  } else {
    red = 329.698727446 * Math.pow(temperature - 60, -0.1332047592)
    green = 288.1221695283 * Math.pow(temperature - 60, -0.0755148492)
  }

  if (temperature >= 66) {
    blue = 255
  } else if (temperature <= 19) {
    blue = 0
  } else {
    blue = 138.5177312231 * Math.log(temperature - 10) - 305.0447927307
  }

  return [
    Math.min(1, Math.max(0, red / 255)),
    Math.min(1, Math.max(0, green / 255)),
    Math.min(1, Math.max(0, blue / 255)),
  ]
}
