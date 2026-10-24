import type { GazeProvider, GazeSample } from './GazeProvider'
import type { Landmark } from './blink'
import { GazeRegression, eyeOpenness, gazeFeatures, type Blendshapes } from './iris'

/** One analysed camera frame: 478 landmarks (normalized) and the head-pose matrix, or null without a face. */
export interface FaceFrame { landmarks: readonly Landmark[]; matrix: ArrayLike<number> | null; blendshapes?: Blendshapes | null }
/** detect(): undefined = no new camera frame yet, null = no face in the new frame. */
export interface FaceTracker { detect(t: number): FaceFrame | null | undefined; close(): void }

/** Below this eye openness the eyes count as closed: no gaze point (and no training sample). */
export const BLINK_OPENNESS = 0.12
const FRAME_MS = 1000 / 30

/**
 * Opens the camera once and runs MediaPipe Face Landmarker on it. The video element keeps WebGazer's
 * id so the optional blink detector (blink.ts) finds the same stream.
 */
export async function createMediaPipeTracker(): Promise<FaceTracker> {
  const { FaceLandmarker, FilesetResolver } = await import('@mediapipe/tasks-vision')
  const base = new URL('./gaze-assets/', location.href).href
  const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: 'user' }, audio: false })
  const video = document.createElement('video')
  video.id = 'webgazerVideoFeed'
  Object.assign(video, { muted: true, playsInline: true, autoplay: true, srcObject: stream })
  video.style.cssText = 'position:fixed;left:0;top:0;width:2px;height:2px;opacity:0;pointer-events:none'
  document.body.append(video)
  try {
    await video.play()
    const fileset = await FilesetResolver.forVisionTasks(`${base}wasm`)
    const create = (delegate: 'GPU' | 'CPU') => FaceLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: `${base}face_landmarker.task`, delegate }, runningMode: 'VIDEO', numFaces: 1,
      outputFacialTransformationMatrixes: true, outputFaceBlendshapes: true
    })
    const landmarker = await create('GPU').catch(() => create('CPU'))
    let lastFrame = -1
    return {
      detect: t => {
        if (video.readyState < 2 || video.currentTime === lastFrame) return undefined
        lastFrame = video.currentTime
        const result = landmarker.detectForVideo(video, t)
        const landmarks = result.faceLandmarks[0]
        if (!landmarks) return null
        const blendshapes: Blendshapes = {}
        for (const c of result.faceBlendshapes?.[0]?.categories ?? []) blendshapes[c.categoryName] = c.score
        return { landmarks, matrix: result.facialTransformationMatrixes?.[0]?.data ?? null, blendshapes }
      },
      close: () => { landmarker.close(); for (const track of stream.getTracks()) track.stop(); video.remove() }
    }
  } catch (error) {
    for (const track of stream.getTracks()) track.stop()
    video.remove()
    throw error
  }
}

/**
 * Eye tracking with MediaPipe iris landmarks + ridge regression (replaces WebGazer). Emits samples
 * with confidence 0 until calibration has trained it, and while the eyes are closed or no face is seen.
 */
export class MediaPipeGazeProvider implements GazeProvider {
  private tracker: FaceTracker | null = null
  private timer: ReturnType<typeof setInterval> | null = null
  private latest: number[] | null = null
  private readonly listeners = new Set<(sample: GazeSample) => void>()
  constructor(private readonly regression = new GazeRegression(),
    private readonly createTracker: () => Promise<FaceTracker> = createMediaPipeTracker) {}

  async start(): Promise<void> {
    if (this.tracker) return
    this.tracker = await this.createTracker()
    this.timer = setInterval(() => this.frame(performance.now()), FRAME_MS)
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer)
    this.timer = null
    this.tracker?.close()
    this.tracker = null
    this.latest = null
  }

  /** One frame (exposed for tests). */
  frame(t: number): void {
    const face = this.tracker?.detect(t)
    if (face === undefined) return
    if (face === null) { this.latest = null; this.emit({ x: 0, y: 0, t, confidence: 0 }); return }
    const open = eyeOpenness(face.landmarks) >= BLINK_OPENNESS
    const features = open ? gazeFeatures(face.landmarks, face.matrix, face.blendshapes) : null
    this.latest = features
    const point = features ? this.regression.predict(features) : null
    this.emit(point ? { ...point, t, confidence: 1 } : { x: 0, y: 0, t, confidence: 0 })
  }

  /** The user is looking at (x, y) now: a calibration dot or a completed dwell's centre. */
  train(x: number, y: number): void {
    if (this.latest) this.regression.add(this.latest, x, y)
  }

  get trained(): boolean { return this.regression.trained }

  onSample(callback: (sample: GazeSample) => void): () => void {
    this.listeners.add(callback)
    return () => { this.listeners.delete(callback) }
  }

  private emit(sample: GazeSample): void { for (const listener of this.listeners) listener(sample) }
}
