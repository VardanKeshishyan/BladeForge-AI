/** Decode a generated .hdr with three's own loader and report its luminance range. */

import { readFileSync } from 'node:fs'
import { RGBELoader } from 'three/examples/jsm/loaders/RGBELoader.js'
import { FloatType, HalfFloatType, DataUtils } from 'three'

for (const path of ['public/assets/hdri/desert.hdr', 'public/assets/hdri/moon-light.hdr']) {
  const file = readFileSync(path)
  const buffer = file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength)

  for (const type of [HalfFloatType, FloatType]) {
    const loader = new RGBELoader().setDataType(type)
    const result = loader.parse(buffer)
    const data = result.data
    const isHalf = !(data instanceof Float32Array)
    const read = (i) => (isHalf ? DataUtils.fromHalfFloat(data[i]) : data[i])

    let logSum = 0
    let samples = 0
    let peak = 0
    for (let i = 0; i < data.length; i += 4 * 97) {
      const luminance = read(i) * 0.2126 + read(i + 1) * 0.7152 + read(i + 2) * 0.0722
      if (!Number.isFinite(luminance) || luminance < 0) continue
      logSum += Math.log(1e-4 + luminance)
      peak = Math.max(peak, luminance)
      samples += 1
    }
    const logAverage = Math.exp(logSum / samples)
    console.log(
      `${path} [${isHalf ? 'half' : 'float'}] ${result.width}x${result.height} ` +
        `ctor=${data.constructor.name} logAvg=${logAverage.toFixed(4)} peak=${peak.toFixed(1)} ` +
        `gain=${(0.16 / logAverage).toFixed(3)}`,
    )
  }
}
