/**
 * Turbine model loading and part classification.
 *
 * Supports the bundled model and customer uploads in FBX and OBJ. Uploaded models rarely
 * use helpful object names — the bundled turbine calls its blades "Cube" — so parts are
 * identified from geometry (where a mesh sits, how big it is, how slender it is) with
 * object names used only as a hint. That way the part selector works on a model nobody
 * has hand-labelled.
 */

import * as THREE from 'three'
import { FBXLoader } from 'three/examples/jsm/loaders/FBXLoader.js'
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js'

export type TurbinePartId =
  | 'all'
  | 'blades'
  | 'hub'
  | 'rotor'
  | 'nacelle'
  | 'tower'
  | 'foundation'

export interface PartBounds {
  min: [number, number, number]
  max: [number, number, number]
  centre: [number, number, number]
  radiusM: number
}

export interface TurbinePart {
  id: TurbinePartId
  displayName: string
  description: string
  /** Names of the meshes that make up this part. Empty when the model has no such part. */
  meshNames: string[]
  present: boolean
  /** Why the part is unavailable, shown in the UI instead of a dead control. */
  unavailableReason?: string
  bounds: PartBounds | null
}

export interface LoadedTurbineModel {
  object: THREE.Group
  parts: TurbinePart[]
  bounds: PartBounds
  /** Metres per source unit that was applied. */
  unitScale: number
  triangleCount: number
  meshCount: number
  hasUvs: boolean
  warnings: string[]
  sourceFormat: 'fbx' | 'obj'
}

export const TURBINE_PART_ORDER: TurbinePartId[] = [
  'all',
  'rotor',
  'blades',
  'hub',
  'nacelle',
  'tower',
  'foundation',
]

const PART_LABELS: Record<TurbinePartId, { displayName: string; description: string }> = {
  all: {
    displayName: 'Entire turbine',
    description: 'Every part. Useful for wide contextual shots and whole-asset inspection.',
  },
  rotor: {
    displayName: 'Rotor assembly',
    description: 'Hub and blades together, as seen in a rotor-plane inspection pass.',
  },
  blades: {
    displayName: 'Blades',
    description: 'The blade surfaces. Where erosion, cracks, delamination and lightning damage occur.',
  },
  hub: {
    displayName: 'Hub',
    description: 'The rotor hub and spinner, including blade-root fixings.',
  },
  nacelle: {
    displayName: 'Nacelle / body',
    description: 'The housing behind the rotor. Oil staining and coating loss show up here.',
  },
  tower: {
    displayName: 'Tower',
    description: 'The supporting tower. Corrosion, rust runoff and paint failure occur here.',
  },
  foundation: {
    displayName: 'Foundation / base',
    description: 'Tower base and foundation structure at ground level.',
  },
}

const NAME_HINTS: { id: TurbinePartId; pattern: RegExp }[] = [
  { id: 'blades', pattern: /blade|rotorblade|wing/i },
  { id: 'hub', pattern: /hub|spinner|nose/i },
  { id: 'nacelle', pattern: /nacelle|housing|body|generator|gearbox/i },
  { id: 'tower', pattern: /tower|mast|column|pole/i },
  { id: 'foundation', pattern: /foundation|base|footing|plinth|pad/i },
]

interface MeshInfo {
  mesh: THREE.Mesh
  box: THREE.Box3
  size: THREE.Vector3
  centre: THREE.Vector3
  triangles: number
}

function measure(mesh: THREE.Mesh): MeshInfo {
  const box = new THREE.Box3().setFromObject(mesh)
  const geometry = mesh.geometry
  const triangles = geometry.index
    ? geometry.index.count / 3
    : (geometry.attributes.position?.count ?? 0) / 3
  return {
    mesh,
    box,
    size: box.getSize(new THREE.Vector3()),
    centre: box.getCenter(new THREE.Vector3()),
    triangles,
  }
}

function toBounds(box: THREE.Box3): PartBounds {
  const centre = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3())
  return {
    min: [box.min.x, box.min.y, box.min.z],
    max: [box.max.x, box.max.y, box.max.z],
    centre: [centre.x, centre.y, centre.z],
    radiusM: size.length() / 2,
  }
}

/**
 * Work out which mesh is which.
 *
 * Everything here is expressed as a fraction of the model's own bounding box, so the
 * rules hold whatever scale or proportions the uploaded turbine uses. The scene is Z-up
 * by this point, so Z is height.
 */
function classifyParts(meshes: MeshInfo[], overall: THREE.Box3): Map<TurbinePartId, MeshInfo[]> {
  const groups = new Map<TurbinePartId, MeshInfo[]>()
  const add = (id: TurbinePartId, info: MeshInfo) => {
    const existing = groups.get(id) ?? []
    existing.push(info)
    groups.set(id, existing)
  }

  const overallSize = overall.getSize(new THREE.Vector3())
  const totalHeight = Math.max(1e-6, overallSize.z)
  const totalWidth = Math.max(1e-6, Math.max(overallSize.x, overallSize.y))

  for (const info of meshes) {
    const named = NAME_HINTS.find((hint) => hint.pattern.test(info.mesh.name))
    if (named) {
      add(named.id, info)
      continue
    }

    const heightFraction = info.size.z / totalHeight
    const widthFraction = Math.max(info.size.x, info.size.y) / totalWidth
    // Where the mesh sits vertically, 0 at ground and 1 at the very top.
    const elevation = (info.centre.z - overall.min.z) / totalHeight
    const slenderness = info.size.z / Math.max(1e-6, Math.max(info.size.x, info.size.y))

    if (slenderness > 4 && heightFraction > 0.3) {
      // Tall and thin, running most of the model's height.
      add('tower', info)
    } else if (widthFraction > 0.35 && elevation > 0.5) {
      // Wide and high up: only the rotor sweeps that much area.
      add('blades', info)
    } else if (elevation > 0.6 && widthFraction < 0.35) {
      // Compact and near the top, behind the rotor.
      add('nacelle', info)
    } else if (elevation < 0.2) {
      add('foundation', info)
    } else {
      add('nacelle', info)
    }
  }

  // Generic FBX/OBJ exports frequently name both top assemblies Cube/Cylinder. If
  // there are multiple compact top meshes, the smallest-volume one is the hub. The
  // Blender renderer applies this same deterministic rule so painted surface ids map
  // to exactly the same mesh at generation time.
  const nacelleMembers = groups.get('nacelle') ?? []
  if ((groups.get('hub')?.length ?? 0) === 0 && nacelleMembers.length >= 2 && (groups.get('blades')?.length ?? 0) > 0) {
    const hub = [...nacelleMembers].sort(
      (left, right) =>
        left.size.x * left.size.y * left.size.z - right.size.x * right.size.y * right.size.z,
    )[0]
    groups.set('hub', [hub])
    groups.set(
      'nacelle',
      nacelleMembers.filter((member) => member !== hub),
    )
  }

  return groups
}

function buildParts(
  groups: Map<TurbinePartId, MeshInfo[]>,
  overall: THREE.Box3,
): TurbinePart[] {
  const parts: TurbinePart[] = []

  for (const id of TURBINE_PART_ORDER) {
    if (id === 'all') {
      parts.push({
        id,
        ...PART_LABELS.all,
        meshNames: [...groups.values()].flat().map((info) => info.mesh.name),
        present: true,
        bounds: toBounds(overall),
      })
      continue
    }

    // The rotor is not a mesh of its own; it is the hub and blades considered together.
    const members =
      id === 'rotor'
        ? [...(groups.get('hub') ?? []), ...(groups.get('blades') ?? [])]
        : (groups.get(id) ?? [])

    if (members.length === 0) {
      parts.push({
        id,
        ...PART_LABELS[id],
        meshNames: [],
        present: false,
        unavailableReason: `This model has no separable ${PART_LABELS[id].displayName.toLowerCase()}. Import a model with that part as its own mesh, or select a part that is present.`,
        bounds: null,
      })
      continue
    }

    const box = new THREE.Box3()
    for (const member of members) box.union(member.box)
    parts.push({
      id,
      ...PART_LABELS[id],
      meshNames: members.map((member) => member.mesh.name),
      present: true,
      bounds: toBounds(box),
    })
  }

  return parts
}

/**
 * Give every renderable surface a deterministic identity for region painting.
 *
 * UUIDs cannot be used here because Three creates new UUIDs whenever a model is
 * reloaded. The semantic part plus its traversal order is stable for the same file and
 * also maps cleanly to the renderer's blade_0 / blade_1 / blade_2 objects.
 */
function assignSurfaceMetadata(groups: Map<TurbinePartId, MeshInfo[]>): void {
  for (const [partId, members] of groups) {
    members.forEach((info, index) => {
      info.mesh.userData.bladeforgeSurfaceId = `${partId}:${index}`
      info.mesh.userData.bladeforgePartId = partId
    })
  }
}

/**
 * Convert the model into the viewport's frame: Z-up, metres, root at the origin.
 *
 * Most FBX exports are Y-up and authored in centimetres. Both are detected rather than
 * assumed, because an uploaded model may be either.
 */
function normalise(group: THREE.Group): { unitScale: number; warnings: string[] } {
  const warnings: string[] = []

  const raw = new THREE.Box3().setFromObject(group)
  const rawSize = raw.getSize(new THREE.Vector3())

  // A turbine is far taller than it is deep. Whichever horizontal axis carries that
  // extent is the real up axis.
  const isYUp = rawSize.y > rawSize.z * 1.5
  if (isYUp) {
    group.rotation.x = Math.PI / 2
    group.updateMatrixWorld(true)
  }

  const uprightSize = new THREE.Box3().setFromObject(group).getSize(new THREE.Vector3())
  const height = uprightSize.z

  // A utility-scale turbine stands roughly 80-260 m. Anything an order of magnitude
  // larger was authored in centimetres or millimetres.
  let unitScale = 1
  if (height > 20000) {
    unitScale = 0.001
    warnings.push('Model appeared to be in millimetres and was scaled to metres.')
  } else if (height > 1000) {
    unitScale = 0.01
    warnings.push('Model appeared to be in centimetres and was scaled to metres.')
  } else if (height < 5) {
    unitScale = 100
    warnings.push('Model was very small and was scaled up; check the reported dimensions.')
  }
  group.scale.setScalar(unitScale)
  group.updateMatrixWorld(true)

  // Sit the base on the ground plane and centre it horizontally, so camera framing and
  // the ground grid line up regardless of where the model's origin was authored.
  const scaled = new THREE.Box3().setFromObject(group)
  const centre = scaled.getCenter(new THREE.Vector3())
  group.position.x -= centre.x
  group.position.y -= centre.y
  group.position.z -= scaled.min.z
  group.updateMatrixWorld(true)

  return { unitScale, warnings }
}

/** A clean white coating — always bright enough that paint colours stay readable. */
export function createCleanWhiteMaterial(wetness = 0): THREE.MeshPhysicalMaterial {
  const shade = 1 - 0.18 * wetness
  return new THREE.MeshPhysicalMaterial({
    color: new THREE.Color(shade, shade * 0.995, shade * 0.98),
    roughness: Math.max(0.12, 0.42 * (1 - 0.5 * wetness)),
    metalness: 0.02,
    clearcoat: Math.min(1, 0.15 + 0.55 * wetness),
    clearcoatRoughness: Math.max(0.04, 0.3 * (1 - wetness)),
    envMapIntensity: 1.35,
    side: THREE.DoubleSide,
  })
}

export function isSupportedModelExtension(fileName: string): boolean {
  return /\.(fbx|obj)$/i.test(fileName)
}

/**
 * Load a turbine from a URL.
 *
 * `onProgress` receives 0-1 where the server reports a content length, so the viewport
 * can show real progress rather than an indefinite spinner.
 */
export async function loadTurbineModel(
  url: string,
  onProgress?: (fraction: number) => void,
): Promise<LoadedTurbineModel> {
  const extension = url.split('?')[0].split('.').pop()?.toLowerCase()
  if (extension !== 'fbx' && extension !== 'obj') {
    throw new Error(`Unsupported model format ".${extension}". Import an FBX or OBJ file.`)
  }

  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`Could not download the model (HTTP ${response.status}).`)
  }
  const buffer = await response.arrayBuffer()
  onProgress?.(1)

  let group: THREE.Group
  if (extension === 'fbx') {
    group = new FBXLoader().parse(buffer, '') as unknown as THREE.Group
  } else {
    group = new OBJLoader().parse(new TextDecoder().decode(buffer))
  }

  const { unitScale, warnings } = normalise(group)

  const meshes: MeshInfo[] = []
  let triangleCount = 0
  let hasUvs = true
  group.traverse((child) => {
    if (!(child as THREE.Mesh).isMesh) return
    const mesh = child as THREE.Mesh
    mesh.castShadow = true
    mesh.receiveShadow = true
    if (!mesh.geometry.attributes.normal) mesh.geometry.computeVertexNormals()
    if (!mesh.geometry.attributes.uv) hasUvs = false
    const info = measure(mesh)
    triangleCount += info.triangles
    meshes.push(info)
  })

  if (meshes.length === 0) {
    throw new Error('The model contains no renderable meshes.')
  }
  if (!hasUvs) {
    warnings.push(
      'Some meshes have no UV coordinates. Region painting needs UVs and will be unavailable for those meshes.',
    )
  }

  const overall = new THREE.Box3().setFromObject(group)
  const groups = classifyParts(meshes, overall)
  assignSurfaceMetadata(groups)
  const parts = buildParts(groups, overall)

  return {
    object: group,
    parts,
    bounds: toBounds(overall),
    unitScale,
    triangleCount,
    meshCount: meshes.length,
    hasUvs,
    warnings,
    sourceFormat: extension,
  }
}

/** Show only the meshes belonging to the selected part. */
export function applyPartVisibility(model: LoadedTurbineModel, partId: TurbinePartId): void {
  const part = model.parts.find((entry) => entry.id === partId)
  const visibleNames =
    !part || partId === 'all' || !part.present ? null : new Set(part.meshNames)
  model.object.traverse((child) => {
    if (!(child as THREE.Mesh).isMesh) return
    child.visible = visibleNames === null ? true : visibleNames.has(child.name)
  })
}

export const BUNDLED_TURBINE_URL = '/assets/models/wind-turbine.fbx'
