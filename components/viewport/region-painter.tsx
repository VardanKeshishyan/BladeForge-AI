'use client'

/**
 * Paints coloured regions on one exact turbine surface.
 *
 * Every stroke carries a stable surface id plus the triangle and object-local hit data
 * for each point. Each source mesh owns a separate overlay texture and only triangles
 * touched on that mesh are drawn. Shared/repeated UVs therefore cannot mirror a stroke
 * onto another blade, another object, or another UV island in the same object.
 */

import { useEffect, useMemo, useRef } from 'react'
import { useThree } from '@react-three/fiber'
import * as THREE from 'three'

import {
  getPaintColor,
  rasteriseOverlay,
  type BrushStroke,
  type PaintColorId,
  type PaintSettings,
  type StrokeMode,
} from '@/lib/viewport/region-painting'

export interface RegionPainterProps {
  paint: PaintSettings
  strokes: readonly BrushStroke[]
  onStrokeComplete: (stroke: BrushStroke) => void
  target: THREE.Object3D | null
}

interface HitSample {
  uv: [number, number]
  surfaceId: string
  surfacePartId: string
  faceIndex: number
  localPoint: [number, number, number]
  localNormal: [number, number, number]
  worldPoint: [number, number, number]
  worldNormal: [number, number, number]
}

interface DraftStroke {
  regionId: PaintColorId
  mode: StrokeMode
  radiusUv: number
  surfaceId: string
  surfacePartId: string
  points: Array<[number, number]>
  faceIndices: number[]
  localPoints: Array<[number, number, number]>
  localNormals: Array<[number, number, number]>
  worldPoints: Array<[number, number, number]>
  worldNormals: Array<[number, number, number]>
}

interface OverlayEntry {
  source: THREE.Mesh
  surfaceId: string
  canvas: HTMLCanvasElement
  texture: THREE.CanvasTexture
  geometry: THREE.BufferGeometry
  material: THREE.MeshBasicMaterial
  overlay: THREE.Mesh
  committedFaces: Set<number>
  liveFaces: Set<number>
}

function collectPaintableMeshes(root: THREE.Object3D, visibleOnly = false): THREE.Mesh[] {
  const meshes: THREE.Mesh[] = []
  root.traverse((child) => {
    const mesh = child as THREE.Mesh
    if (!mesh.isMesh || (visibleOnly && !mesh.visible)) return
    if (mesh.name.endsWith('-paint-overlay')) return
    if (!mesh.geometry?.attributes?.uv) return
    meshes.push(mesh)
  })
  meshes.forEach((mesh, index) => {
    if (!mesh.userData.bladeforgeSurfaceId) {
      mesh.userData.bladeforgeSurfaceId = `unclassified:${index}`
    }
    if (!mesh.userData.bladeforgePartId) {
      mesh.userData.bladeforgePartId = 'unclassified'
    }
  })
  return meshes
}

function makeOverlayGeometry(source: THREE.BufferGeometry): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry()
  for (const [name, attribute] of Object.entries(source.attributes)) {
    geometry.setAttribute(name, attribute)
  }
  geometry.morphAttributes = source.morphAttributes
  geometry.morphTargetsRelative = source.morphTargetsRelative
  geometry.boundingBox = source.boundingBox?.clone() ?? null
  geometry.boundingSphere = source.boundingSphere?.clone() ?? null
  geometry.setIndex([])
  return geometry
}

function setVisibleFaces(entry: OverlayEntry): void {
  const faces = new Set([...entry.committedFaces, ...entry.liveFaces])
  const sourceIndex = entry.source.geometry.index
  const triangleCount = sourceIndex
    ? Math.floor(sourceIndex.count / 3)
    : Math.floor((entry.source.geometry.attributes.position?.count ?? 0) / 3)
  const indices: number[] = []
  for (const faceIndex of [...faces].sort((a, b) => a - b)) {
    if (faceIndex < 0 || faceIndex >= triangleCount) continue
    const offset = faceIndex * 3
    if (sourceIndex) {
      indices.push(sourceIndex.getX(offset), sourceIndex.getX(offset + 1), sourceIndex.getX(offset + 2))
    } else {
      indices.push(offset, offset + 1, offset + 2)
    }
  }
  entry.geometry.setIndex(indices)
  entry.geometry.index!.needsUpdate = true
  entry.overlay.visible = entry.overlay.visible && indices.length > 0
}

function refreshEntry(entry: OverlayEntry, strokes: readonly BrushStroke[], opacity: number): void {
  rasteriseOverlay(entry.canvas, strokes, opacity, entry.surfaceId)
  entry.texture.needsUpdate = true
  entry.committedFaces.clear()
  for (const stroke of strokes) {
    if (stroke.surfaceId !== entry.surfaceId) continue
    for (const faceIndex of stroke.faceIndices) entry.committedFaces.add(faceIndex)
  }
  entry.liveFaces.clear()
  setVisibleFaces(entry)
}

export function RegionPainter({ paint, strokes, onStrokeComplete, target }: RegionPainterProps) {
  const { camera, gl } = useThree()
  const raycaster = useMemo(() => new THREE.Raycaster(), [])
  const pointer = useMemo(() => new THREE.Vector2(), [])
  const draftRef = useRef<DraftStroke | null>(null)
  const paintingRef = useRef(false)
  const paintRef = useRef(paint)
  const strokesRef = useRef(strokes)
  const onCompleteRef = useRef(onStrokeComplete)
  const targetRef = useRef(target)
  const canvasElRef = useRef<HTMLCanvasElement>(gl.domElement)
  const overlaysRef = useRef<Map<string, OverlayEntry>>(new Map())

  useEffect(() => {
    paintRef.current = paint
  }, [paint])
  useEffect(() => {
    strokesRef.current = strokes
  }, [strokes])
  useEffect(() => {
    onCompleteRef.current = onStrokeComplete
  }, [onStrokeComplete])
  useEffect(() => {
    targetRef.current = target
  }, [target])
  useEffect(() => {
    canvasElRef.current = gl.domElement
  }, [gl])

  useEffect(() => {
    if (!target) return
    const entries = new Map<string, OverlayEntry>()
    for (const source of collectPaintableMeshes(target)) {
      const surfaceId = String(source.userData.bladeforgeSurfaceId)
      const canvas = document.createElement('canvas')
      canvas.width = 1024
      canvas.height = 512
      const texture = new THREE.CanvasTexture(canvas)
      texture.colorSpace = THREE.SRGBColorSpace
      const geometry = makeOverlayGeometry(source.geometry)
      const material = new THREE.MeshBasicMaterial({
        map: texture,
        transparent: true,
        depthWrite: false,
        toneMapped: false,
        side: THREE.DoubleSide,
        polygonOffset: true,
        polygonOffsetFactor: -2,
        polygonOffsetUnits: -2,
      })
      const overlay = new THREE.Mesh(geometry, material)
      overlay.name = `${source.name || 'mesh'}-paint-overlay`
      overlay.renderOrder = 20
      overlay.frustumCulled = false
      overlay.visible = paintRef.current.enabled
      source.add(overlay)
      const entry: OverlayEntry = {
        source,
        surfaceId,
        canvas,
        texture,
        geometry,
        material,
        overlay,
        committedFaces: new Set(),
        liveFaces: new Set(),
      }
      entries.set(surfaceId, entry)
      refreshEntry(entry, strokesRef.current, paintRef.current.overlayOpacity)
      overlay.visible = paintRef.current.enabled && (geometry.index?.count ?? 0) > 0
    }
    overlaysRef.current = entries
    return () => {
      overlaysRef.current = new Map()
      for (const entry of entries.values()) {
        entry.overlay.removeFromParent()
        entry.geometry.dispose()
        entry.material.dispose()
        entry.texture.dispose()
      }
    }
  }, [target])

  useEffect(() => {
    for (const entry of overlaysRef.current.values()) {
      refreshEntry(entry, strokes, paint.overlayOpacity)
      entry.overlay.visible = paint.enabled && (entry.geometry.index?.count ?? 0) > 0
    }
  }, [strokes, paint.overlayOpacity, paint.enabled])

  useEffect(() => {
    if (!paint.enabled) return
    const element = canvasElRef.current

    function hitSurface(clientX: number, clientY: number): HitSample | null {
      const object = targetRef.current
      if (!object) return null
      const rect = element.getBoundingClientRect()
      if (rect.width <= 0 || rect.height <= 0) return null
      pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1
      pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1
      raycaster.setFromCamera(pointer, camera)

      const hits = raycaster.intersectObjects(collectPaintableMeshes(object, true), false)
      for (const hit of hits) {
        const mesh = hit.object as THREE.Mesh
        if (!hit.uv || hit.faceIndex === undefined || hit.faceIndex === null) continue
        const worldPoint = hit.point.clone()
        const localPoint = mesh.worldToLocal(worldPoint.clone())
        const localNormal = hit.face?.normal.clone().normalize() ?? new THREE.Vector3(0, 0, 1)
        const worldNormal = localNormal
          .clone()
          .applyMatrix3(new THREE.Matrix3().getNormalMatrix(mesh.matrixWorld))
          .normalize()
        return {
          uv: [Math.min(1, Math.max(0, hit.uv.x)), Math.min(1, Math.max(0, hit.uv.y))],
          surfaceId: String(mesh.userData.bladeforgeSurfaceId),
          surfacePartId: String(mesh.userData.bladeforgePartId),
          faceIndex: hit.faceIndex,
          localPoint: [localPoint.x, localPoint.y, localPoint.z],
          localNormal: [localNormal.x, localNormal.y, localNormal.z],
          worldPoint: [worldPoint.x, worldPoint.y, worldPoint.z],
          worldNormal: [worldNormal.x, worldNormal.y, worldNormal.z],
        }
      }
      return null
    }

    function stampLive(sample: HitSample, last: [number, number] | null) {
      const draft = draftRef.current
      if (!draft || draft.surfaceId !== sample.surfaceId) return
      const entry = overlaysRef.current.get(draft.surfaceId)
      if (!entry) return
      entry.liveFaces.add(sample.faceIndex)
      setVisibleFaces(entry)
      entry.overlay.visible = true

      const color = getPaintColor(draft.regionId)
      const context = entry.canvas.getContext('2d')
      if (!context) return
      const width = entry.canvas.width
      const height = entry.canvas.height
      const radiusPx = Math.max(2, draft.radiusUv * Math.min(width, height))
      const hex = color.hex.replace('#', '')
      const n = Number.parseInt(hex, 16)
      const r = (n >> 16) & 255
      const g = (n >> 8) & 255
      const b = n & 255
      context.globalCompositeOperation = draft.mode === 'erase' ? 'destination-out' : 'source-over'
      const style =
        draft.mode === 'erase'
          ? 'rgba(0,0,0,1)'
          : `rgba(${r},${g},${b},${paintRef.current.overlayOpacity})`
      context.fillStyle = style
      context.strokeStyle = style
      context.lineWidth = radiusPx * 2
      context.lineCap = 'round'
      context.lineJoin = 'round'
      context.beginPath()
      context.arc(sample.uv[0] * width, (1 - sample.uv[1]) * height, radiusPx, 0, Math.PI * 2)
      context.fill()
      if (last) {
        context.beginPath()
        context.moveTo(last[0] * width, (1 - last[1]) * height)
        context.lineTo(sample.uv[0] * width, (1 - sample.uv[1]) * height)
        context.stroke()
      }
      context.globalCompositeOperation = 'source-over'
      entry.texture.needsUpdate = true
    }

    function beginStroke(event: PointerEvent) {
      const current = paintRef.current
      if (!current.enabled || event.button !== 0) return
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
      const hit = hitSurface(event.clientX, event.clientY)
      if (!hit) return

      paintingRef.current = true
      draftRef.current = {
        regionId: current.activeColorId,
        mode: current.mode,
        radiusUv: current.brushRadiusUv,
        surfaceId: hit.surfaceId,
        surfacePartId: hit.surfacePartId,
        points: [hit.uv],
        faceIndices: [hit.faceIndex],
        localPoints: [hit.localPoint],
        localNormals: [hit.localNormal],
        worldPoints: [hit.worldPoint],
        worldNormals: [hit.worldNormal],
      }
      stampLive(hit, null)
      try {
        element.setPointerCapture(event.pointerId)
      } catch {
        // Painting still works when a browser declines pointer capture.
      }
      event.preventDefault()
      event.stopPropagation()
    }

    function moveStroke(event: PointerEvent) {
      const draft = draftRef.current
      if (!paintingRef.current || !draft) return
      const hit = hitSurface(event.clientX, event.clientY)
      // One gesture is intentionally locked to its starting mesh. Crossing a seam
      // cannot accidentally paint the next blade or another turbine component.
      if (!hit || hit.surfaceId !== draft.surfaceId) return
      const last = draft.points[draft.points.length - 1]
      const du = hit.uv[0] - last[0]
      const dv = hit.uv[1] - last[1]
      if (du * du + dv * dv < 0.00000025 && hit.faceIndex === draft.faceIndices.at(-1)) return
      draft.points.push(hit.uv)
      draft.faceIndices.push(hit.faceIndex)
      draft.localPoints.push(hit.localPoint)
      draft.localNormals.push(hit.localNormal)
      draft.worldPoints.push(hit.worldPoint)
      draft.worldNormals.push(hit.worldNormal)
      stampLive(hit, last)
      event.preventDefault()
      event.stopPropagation()
    }

    function endStroke(event: PointerEvent) {
      if (!paintingRef.current) return
      paintingRef.current = false
      const draft = draftRef.current
      draftRef.current = null
      try {
        if (element.hasPointerCapture(event.pointerId)) element.releasePointerCapture(event.pointerId)
      } catch {
        // ignore
      }
      if (draft && draft.points.length > 0) onCompleteRef.current(draft)
      event.preventDefault()
      event.stopPropagation()
    }

    element.addEventListener('pointerdown', beginStroke, true)
    element.addEventListener('pointermove', moveStroke, true)
    element.addEventListener('pointerup', endStroke, true)
    element.addEventListener('pointercancel', endStroke, true)
    return () => {
      element.removeEventListener('pointerdown', beginStroke, true)
      element.removeEventListener('pointermove', moveStroke, true)
      element.removeEventListener('pointerup', endStroke, true)
      element.removeEventListener('pointercancel', endStroke, true)
    }
  }, [paint.enabled, camera, raycaster, pointer])

  return null
}
