import type { GazeProvider, GazeSample } from './GazeProvider'
import type { Landmark } from './blink'
import { GazeRegression, eyeOpenness, gazeFeatures, type Blendshapes } from './iris'

/** One analysed camera frame: 478 landmarks (normalized) and the head-pose matrix, or null without a face. */
export interface FaceFrame { landmarks: readonly Landmark[]; matrix: ArrayLike<number> | null; blendshapes?: Blendshapes | null }
/** detect(): undefined = no new camera frame yet, null = no face in the new frame. */
export interface FaceTracker { detect(t: number): FaceFrame | null | undefined; close(): void }

/** Landmarks worth keeping for offline tuning: nose tip, eye corners and lids, iris centres. */
const RECORDED_LANDMARKS = [1, 33, 133, 159, 145, 263, 362, 386, 374, 468, 473, 10, 152] as const
const round = (v: number) => Math.round(v * 1e5) / 1e5

/** One camera frame's raw signals, compact (performance.now() time, normalized image coordinates). */
export interface RecordedFrame {
  t: number
  face: boolean
  matrix?: number[]
  landmarks?: Record<number, [number, number, number]>
  blendshapes?: Record<string, number>
}

function recordFrame(t: number, face: FaceFrame): RecordedFrame {
  const landmarks: Record<number, [number, number, number]> = {}
  for (const i of RECORDED_LANDMARKS) {
    const p = face.landmarks[i] as (Landmark & { z?: number }) | undefined
    if (p) landmarks[i] = [round(p.x), round(p.y), round(p.z ?? 0)]
  }
  const blendshapes: Record<string, number> = {}
  for (const [k, v] of Object.entries(face.blendshapes ?? {})) if (k.startsWith('eyeLook') && v !== undefined) blendshapes[k] = round(v)
  return { t: Math.round(t), face: true, matrix: face.matrix ? Array.from(face.matrix, round) : undefined, landmarks, blendshapes }
}

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
  private recording: RecordedFrame[] | null = null
  private readonly listeners = new Set<(sample: GazeSample) => void>()
  constructor(private readonly regression = new GazeRegression(),
    private readonly createTracker: () => Promise<FaceTracker> = createMediaPipeTracker,
    /** Frame → features; eye features by default. Closed eyes give none. */
    private readonly features: (face: FaceFrame) => number[] | null = face =>
      eyeOpenness(face.landmarks) >= BLINK_OPENNESS ? gazeFeatures(face.landmarks, face.matrix, face.blendshapes) : null) {}

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
    if (face === null) { this.latest = null; this.recording?.push({ t, face: false }); this.emit({ x: 0, y: 0, t, confidence: 0 }); return }
    if (this.recording) this.recording.push(recordFrame(t, face))
    const features = this.features(face)
    this.latest = features
    const point = features ? this.regression.predict(features) : null
    this.emit(point ? { ...point, t, confidence: 1 } : { x: 0, y: 0, t, confidence: 0 })
  }

  /** The user is looking at (x, y) now: a calibration dot or a completed dwell's centre. */
  train(x: number, y: number): void {
    if (this.latest) this.regression.add(this.latest, x, y)
  }

  get trained(): boolean { return this.regression.trained }
  /** Calibration samples, saved across launches by the runtime. */
  get training(): { f: number[]; x: number; y: number }[] { return this.regression.snapshot() }
  restoreTraining(samples: readonly { f: readonly number[]; x: number; y: number }[]): void { this.regression.restore(samples) }

  /** Debug: keep the raw per-frame signals from now on (see recordFrame). */
  startRecording(): void { this.recording = [] }
  /** Debug: the frames recorded since startRecording; recording stops. */
  takeRecording(): RecordedFrame[] { const frames = this.recording ?? []; this.recording = null; return frames }

  onSample(callback: (sample: GazeSample) => void): () => void {
    this.listeners.add(callback)
    return () => { this.listeners.delete(callback) }
  }

  private emit(sample: GazeSample): void { for (const listener of this.listeners) listener(sample) }
}
