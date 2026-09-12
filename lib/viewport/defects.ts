/**
 * Defect catalogue for the generation UI.
 *
 * Each entry names a damage mode a customer would recognise from an inspection report,
 * says which turbine parts it can physically occur on, and carries the parameters that
 * control how it is generated. Restricting defects to plausible parts matters: rust on a
 * composite blade shell is not corrosion, it is runoff staining, and a dataset that
 * labels it as corrosion teaches a model the wrong thing.
 */

import type { TurbinePartId } from './turbine-model'

export type DefectCategory =
  | 'surface'
  | 'structural'
  | 'coating'
  | 'corrosion'
  | 'contamination'
  | 'environmental'

export interface DefectType {
  id: string
  label: string
  description: string
  category: DefectCategory
  /** Parts this damage can physically occur on. */
  applicableParts: TurbinePartId[]
  /** Suggested layer colour, used as the region-painting identifier in the UI. */
  colorHex: string
  /** Whether the customer choosing a colour is meaningful, as it is for stains. */
  colorIsMeaningful: boolean
  defaultSeverity: number
  defaultCoverage: number
}

export const DEFECT_CATALOGUE: DefectType[] = [
  {
    id: 'surface_crack',
    label: 'Surface cracks',
    description: 'Fissures in the shell surface, following the local curvature.',
    category: 'structural',
    applicableParts: ['blades', 'hub', 'nacelle', 'tower'],
    colorHex: '#ef4444',
    colorIsMeaningful: false,
    defaultSeverity: 45,
    defaultCoverage: 12,
  },
  {
    id: 'leading_edge_erosion',
    label: 'Leading-edge erosion',
    description: 'Coating and laminate loss along the leading edge from rain impact.',
    category: 'surface',
    applicableParts: ['blades'],
    colorHex: '#22c55e',
    colorIsMeaningful: false,
    defaultSeverity: 50,
    defaultCoverage: 25,
  },
  {
    id: 'trailing_edge_damage',
    label: 'Trailing-edge damage',
    description: 'Split or eroded trailing-edge bond line and shell separation.',
    category: 'structural',
    applicableParts: ['blades'],
    colorHex: '#f97316',
    colorIsMeaningful: false,
    defaultSeverity: 40,
    defaultCoverage: 15,
  },
  {
    id: 'corrosion',
    label: 'Corrosion',
    description: 'Electrochemical attack on metal. Only valid on metallic parts.',
    category: 'corrosion',
    applicableParts: ['tower', 'nacelle', 'hub', 'foundation'],
    colorHex: '#b45309',
    colorIsMeaningful: false,
    defaultSeverity: 45,
    defaultCoverage: 18,
  },
  {
    id: 'rust_staining',
    label: 'Rust / runoff staining',
    description: 'Iron-oxide staining washed down from a metallic source onto any surface.',
    category: 'corrosion',
    applicableParts: ['blades', 'hub', 'nacelle', 'tower', 'foundation'],
    colorHex: '#a16207',
    colorIsMeaningful: true,
    defaultSeverity: 35,
    defaultCoverage: 20,
  },
  {
    id: 'paint_peeling',
    label: 'Paint peeling',
    description: 'Lifted and flaking paint exposing the layer beneath.',
    category: 'coating',
    applicableParts: ['blades', 'hub', 'nacelle', 'tower', 'foundation'],
    colorHex: '#eab308',
    colorIsMeaningful: false,
    defaultSeverity: 40,
    defaultCoverage: 22,
  },
  {
    id: 'coating_loss',
    label: 'Coating loss',
    description: 'Thinning, chalking and worn-through protective coating.',
    category: 'coating',
    applicableParts: ['blades', 'hub', 'nacelle', 'tower'],
    colorHex: '#facc15',
    colorIsMeaningful: false,
    defaultSeverity: 35,
    defaultCoverage: 25,
  },
  {
    id: 'scratches',
    label: 'Scratches',
    description: 'Linear surface abrasion from handling, transport or debris.',
    category: 'surface',
    applicableParts: ['blades', 'hub', 'nacelle', 'tower'],
    colorHex: '#94a3b8',
    colorIsMeaningful: false,
    defaultSeverity: 25,
    defaultCoverage: 10,
  },
  {
    id: 'dents',
    label: 'Dents',
    description: 'Localised inward deformation without a break in the surface.',
    category: 'structural',
    applicableParts: ['nacelle', 'tower', 'hub', 'foundation'],
    colorHex: '#64748b',
    colorIsMeaningful: false,
    defaultSeverity: 35,
    defaultCoverage: 8,
  },
  {
    id: 'lightning_strike',
    label: 'Lightning-strike damage',
    description: 'Entry point, scorching, branching burn tracks and local delamination.',
    category: 'structural',
    applicableParts: ['blades', 'hub'],
    colorHex: '#a855f7',
    colorIsMeaningful: false,
    defaultSeverity: 60,
    defaultCoverage: 10,
  },
  {
    id: 'holes',
    label: 'Holes / punctures',
    description: 'Through-thickness penetration of the shell.',
    category: 'structural',
    applicableParts: ['blades', 'nacelle', 'hub'],
    colorHex: '#7f1d1d',
    colorIsMeaningful: false,
    defaultSeverity: 70,
    defaultCoverage: 5,
  },
  {
    id: 'chips',
    label: 'Chips',
    description: 'Small pieces broken away from an edge or corner.',
    category: 'surface',
    applicableParts: ['blades', 'hub', 'nacelle', 'tower'],
    colorHex: '#fb7185',
    colorIsMeaningful: false,
    defaultSeverity: 30,
    defaultCoverage: 12,
  },
  {
    id: 'delamination',
    label: 'Delamination',
    description: 'Separated or blistered composite layers, lifted from the substrate.',
    category: 'structural',
    applicableParts: ['blades', 'hub'],
    colorHex: '#3b82f6',
    colorIsMeaningful: false,
    defaultSeverity: 50,
    defaultCoverage: 15,
  },
  {
    id: 'oil_stains',
    label: 'Oil / fluid stains',
    description: 'Gearbox or hydraulic fluid leaking and streaking down the surface.',
    category: 'contamination',
    applicableParts: ['nacelle', 'hub', 'tower', 'blades'],
    colorHex: '#1f2937',
    colorIsMeaningful: true,
    defaultSeverity: 35,
    defaultCoverage: 18,
  },
  {
    id: 'dirt_buildup',
    label: 'Dirt buildup',
    description: 'Accumulated dust, salt and organic soiling.',
    category: 'contamination',
    applicableParts: ['blades', 'hub', 'nacelle', 'tower', 'foundation'],
    colorHex: '#78716c',
    colorIsMeaningful: true,
    defaultSeverity: 25,
    defaultCoverage: 35,
  },
  {
    id: 'ice_buildup',
    label: 'Ice buildup',
    description: 'Accreted ice on leading edges and exposed surfaces.',
    category: 'environmental',
    applicableParts: ['blades', 'hub', 'nacelle'],
    colorHex: '#67e8f9',
    colorIsMeaningful: false,
    defaultSeverity: 45,
    defaultCoverage: 30,
  },
  {
    id: 'structural_deformation',
    label: 'Structural deformation',
    description: 'Bending, buckling or twist beyond the designed shape.',
    category: 'structural',
    applicableParts: ['blades', 'tower', 'nacelle'],
    colorHex: '#c026d3',
    colorIsMeaningful: false,
    defaultSeverity: 55,
    defaultCoverage: 20,
  },
]

/** Per-instance configuration for one selected defect. */
export interface DefectLayer {
  defectId: string
  /** Which part the damage is placed on. Must be in the defect's applicable list. */
  partId: TurbinePartId
  severity: number
  coverage: number
  sizeScale: number
  opacity: number
  rotationDeg: number
  spread: number
  randomness: number
  colorHex: string
  /** Painted region this layer is confined to. Null means the whole selected part. */
  regionId: string | null
}

export function getDefectType(defectId: string): DefectType | undefined {
  return DEFECT_CATALOGUE.find((entry) => entry.id === defectId)
}

export function defectsForPart(partId: TurbinePartId): DefectType[] {
  if (partId === 'all') return DEFECT_CATALOGUE
  if (partId === 'rotor') {
    return DEFECT_CATALOGUE.filter(
      (entry) => entry.applicableParts.includes('blades') || entry.applicableParts.includes('hub'),
    )
  }
  return DEFECT_CATALOGUE.filter((entry) => entry.applicableParts.includes(partId))
}

export function createDefectLayer(defect: DefectType, partId: TurbinePartId): DefectLayer {
  // Default the layer onto a part the defect can actually occur on, so a selection made
  // while viewing the whole turbine is still physically valid.
  const target =
    partId !== 'all' && partId !== 'rotor' && defect.applicableParts.includes(partId)
      ? partId
      : defect.applicableParts[0]
  return {
    defectId: defect.id,
    partId: target,
    severity: defect.defaultSeverity,
    coverage: defect.defaultCoverage,
    sizeScale: 1,
    opacity: 100,
    rotationDeg: 0,
    spread: 40,
    randomness: 50,
    colorHex: defect.colorHex,
    regionId: null,
  }
}
