/**
 * Print the node hierarchy of an FBX so the viewport's part classifier can be written
 * against the real object names rather than guesses.
 */

import { readFileSync } from 'node:fs'

// The FBX embeds texture references and the loader reaches for an <img> to resolve them.
// Only the hierarchy matters here, so a stub is enough to get past it.
globalThis.document = {
  createElementNS: () => ({
    addEventListener() {},
    removeEventListener() {},
    setAttribute() {},
    style: {},
  }),
  createElement: () => ({ getContext: () => null, style: {} }),
}

const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
const { Box3, Vector3 } = await import('three')

const path = process.argv[2] ?? 'public/assets/models/wind-turbine.fbx'
const file = readFileSync(path)
const buffer = file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength)

const group = new FBXLoader().parse(buffer, '')

const overall = new Box3().setFromObject(group)
const size = overall.getSize(new Vector3())
console.log(`overall size: ${size.x.toFixed(2)} x ${size.y.toFixed(2)} x ${size.z.toFixed(2)}`)
console.log(`overall min: ${overall.min.toArray().map((v) => v.toFixed(2)).join(', ')}`)
console.log(`overall max: ${overall.max.toArray().map((v) => v.toFixed(2)).join(', ')}`)
console.log('---')

function walk(object, depth) {
  const pad = '  '.repeat(depth)
  let detail = ''
  if (object.isMesh) {
    const box = new Box3().setFromObject(object)
    const extent = box.getSize(new Vector3())
    const centre = box.getCenter(new Vector3())
    const triangles = object.geometry.index
      ? object.geometry.index.count / 3
      : object.geometry.attributes.position.count / 3
    const materials = Array.isArray(object.material) ? object.material : [object.material]
    detail =
      ` | tris=${triangles}` +
      ` size=(${extent.toArray().map((v) => v.toFixed(1)).join(',')})` +
      ` centre=(${centre.toArray().map((v) => v.toFixed(1)).join(',')})` +
      ` mats=[${materials.map((m) => m?.name || '?').join(',')}]` +
      ` uv=${object.geometry.attributes.uv ? 'yes' : 'NO'}`
  }
  console.log(`${pad}${object.type} "${object.name}"${detail}`)
  for (const child of object.children) walk(child, depth + 1)
}

walk(group, 0)
