// Serve local, pinned camera-model assets in dev and copy them into the production bundle.
import { cp, mkdir, access, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
const require = createRequire(import.meta.url)
const overlay = resolve(import.meta.dirname, '..')
const target = resolve(overlay, 'node_modules/.gaze-assets/gaze-assets')
await mkdir(target, { recursive: true })
await cp(require.resolve('webgazer'), resolve(target, 'webgazer.js'))
await cp(`${require.resolve('webgazer')}.map`, resolve(target, 'webgazer.js.map'))
await cp(resolve(dirname(require.resolve('webgazer')), 'mediapipe/face_mesh'), resolve(target, 'face_mesh'), { recursive: true })
await cp(dirname(require.resolve('@mediapipe/tasks-vision/vision_wasm_internal.js')), resolve(target, 'wasm'), { recursive: true })
const model = resolve(target, 'face_landmarker.task')
try { await access(model) } catch {
  const response = await fetch('https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task')
  if (!response.ok) throw new Error(`Face Landmarker download failed: ${response.status}`)
  await writeFile(model, new Uint8Array(await response.arrayBuffer()))
}
console.log('Local gaze assets ready')
