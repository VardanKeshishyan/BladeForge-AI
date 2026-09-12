/**
 * Downsample the supplied 4K EXR environments and re-encode them as Radiance .hdr.
 *
 * The originals are 96 MB and 19 MB, which is far too much to pull over the wire every
 * time the viewport mounts. A 2K RGBE file carries more than enough detail for a
 * background and for image-based lighting, and lands around 8 MB.
 *
 * Run with: node scripts/prepare-hdri.mjs
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { EXRLoader } from 'three/examples/jsm/loaders/EXRLoader.js'
import { FloatType } from 'three'

const TARGET_WIDTH = 2048
const TARGET_HEIGHT = 1024

const SOURCES = [
  { input: 'var/hdri-source/desert.exr', output: 'public/assets/hdri/desert.hdr' },
  { input: 'var/hdri-source/moon-light.exr', output: 'public/assets/hdri/moon-light.hdr' },
]

function readExr(path) {
  const file = readFileSync(path)
  const buffer = file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength)
  // EXRLoader defaults to half float, which hands back raw 16-bit patterns rather than
  // numbers. Asking for full float is what makes the samples below actually radiance.
  const loader = new EXRLoader().setDataType(FloatType)
  const result = loader.parse(buffer)
  if (!(result.data instanceof Float32Array)) {
    throw new Error('Expected float EXR samples; got ' + result.data.constructor.name)
  }
  return result
}

/** Box-filter downsample, averaging every source texel that falls inside a target texel. */
function resample(source, width, height, channels, targetWidth, targetHeight) {
  const out = new Float32Array(targetWidth * targetHeight * 3)
  const xRatio = width / targetWidth
  const yRatio = height / targetHeight

  for (let y = 0; y < targetHeight; y += 1) {
    const y0 = Math.floor(y * yRatio)
    const y1 = Math.min(height, Math.max(y0 + 1, Math.floor((y + 1) * yRatio)))
    for (let x = 0; x < targetWidth; x += 1) {
      const x0 = Math.floor(x * xRatio)
      const x1 = Math.min(width, Math.max(x0 + 1, Math.floor((x + 1) * xRatio)))
      let r = 0
      let g = 0
      let b = 0
      let n = 0
      for (let sy = y0; sy < y1; sy += 1) {
        for (let sx = x0; sx < x1; sx += 1) {
          const i = (sy * width + sx) * channels
          r += source[i]
          g += source[i + 1]
          b += source[i + 2]
          n += 1
        }
      }
      const o = (y * targetWidth + x) * 3
      out[o] = r / n
      out[o + 1] = g / n
      out[o + 2] = b / n
    }
  }
  return out
}

/** Pack a linear float triple into Radiance's shared-exponent RGBE representation. */
function toRgbe(r, g, b, target, offset) {
  const peak = Math.max(r, g, b)
  if (peak < 1e-32) {
    target[offset] = 0
    target[offset + 1] = 0
    target[offset + 2] = 0
    target[offset + 3] = 0
    return
  }
  const exponent = Math.ceil(Math.log2(peak))
  const scale = Math.pow(2, -exponent) * 256
  target[offset] = Math.min(255, Math.floor(r * scale))
  target[offset + 1] = Math.min(255, Math.floor(g * scale))
  target[offset + 2] = Math.min(255, Math.floor(b * scale))
  target[offset + 3] = exponent + 128
}

/**
 * Write RLE-compressed Radiance HDR.
 *
 * Each scanline stores its four components separately. Everything is emitted as literal
 * runs, which compresses nothing but is unambiguous — a flat dump risks a pixel whose
 * bytes happen to look like an RLE marker and derails the whole scanline.
 */
function encodeHdr(pixels, width, height) {
  const header = Buffer.from(
    `#?RADIANCE\nFORMAT=32-bit_rle_rgbe\nEXPOSURE=1.0\n\n-Y ${height} +X ${width}\n`,
    'ascii',
  )

  const scanline = new Uint8Array(width * 4)
  const chunks = [header]

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = (y * width + x) * 3
      const rgbe = new Uint8Array(4)
      toRgbe(pixels[i], pixels[i + 1], pixels[i + 2], rgbe, 0)
      scanline[x] = rgbe[0]
      scanline[width + x] = rgbe[1]
      scanline[width * 2 + x] = rgbe[2]
      scanline[width * 3 + x] = rgbe[3]
    }

    const body = [Buffer.from([2, 2, (width >> 8) & 0xff, width & 0xff])]
    for (let component = 0; component < 4; component += 1) {
      let cursor = 0
      while (cursor < width) {
        const run = Math.min(128, width - cursor)
        body.push(Buffer.from([run]))
        body.push(Buffer.from(scanline.subarray(component * width + cursor, component * width + cursor + run)))
        cursor += run
      }
    }
    chunks.push(Buffer.concat(body))
  }

  return Buffer.concat(chunks)
}

for (const { input, output } of SOURCES) {
  process.stdout.write(`reading ${input} ... `)
  const exr = readExr(input)
  const channels = exr.data.length / (exr.width * exr.height)
  process.stdout.write(`${exr.width}x${exr.height} (${channels} ch) -> `)
  const resized = resample(
    exr.data,
    exr.width,
    exr.height,
    channels,
    TARGET_WIDTH,
    TARGET_HEIGHT,
  )
  const encoded = encodeHdr(resized, TARGET_WIDTH, TARGET_HEIGHT)
  writeFileSync(output, encoded)
  console.log(`${output} (${(encoded.length / 1024 / 1024).toFixed(1)} MB)`)
}
