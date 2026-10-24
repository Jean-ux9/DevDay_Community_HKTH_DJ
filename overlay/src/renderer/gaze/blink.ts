/** Blink selection is opt-in. Eyebrow selection is excluded by the spec's EAR-only rule. */
export interface Landmark { x: number; y: number }
const distance = (a: Landmark, b: Landmark) => Math.hypot(a.x - b.x, a.y - b.y)
export function eyeAspectRatio(points: readonly Landmark[], indices: readonly number[]): number {
  const eye = indices.map(index => points[index])
  if (eye.length !== 6 || eye.some(point => !point)) return 1
  const [a, b, c, d, e, f] = eye as [Landmark, Landmark, Landmark, Landmark, Landmark, Landmark]
  return (distance(b, f) + distance(c, e)) / Math.max(2 * distance(a, d), 1e-6)
}
export const LEFT_EYE = [33, 160, 158, 133, 153, 144]
export const RIGHT_EYE = [362, 385, 387, 263, 373, 380]
/** A long blink fires once on reopening; no selections while eyes remain closed. */
export class BlinkDetector {
  private closedAt: number | null = null
  private lastT = -Infinity
  constructor(private readonly select: (t: number) => void, private readonly pause: (value: boolean) => void,
    private readonly threshold = 0.2) {}
  update(ear: number | null, t: number): void {
    if (t - this.lastT > 250) this.closedAt = null
    this.lastT = t
    if (ear === null || !Number.isFinite(ear)) { this.closedAt = null; this.pause(false); return }
    if (ear < this.threshold) { this.closedAt ??= t; this.pause(true); return }
    const start = this.closedAt
    this.closedAt = null
    if (start !== null && t - start > 400) this.select(t)
    this.pause(false)
  }
  reset(): void { this.closedAt = null; this.lastT = -Infinity; this.pause(false) }
}
/** Shares WebGazer's camera element. No second getUserMedia stream. */
export async function startBlinkDetection(detector: BlinkDetector): Promise<() => void> {
  const { FaceLandmarker, FilesetResolver } = await import('@mediapipe/tasks-vision')
  const base = new URL('./gaze-assets/', location.href).href
  const landmarker = await FaceLandmarker.createFromOptions(await FilesetResolver.forVisionTasks(`${base}wasm`), {
    baseOptions: { modelAssetPath: `${base}face_landmarker.task` }, runningMode: 'VIDEO', numFaces: 1
  })
  let lastFrame = -1
  const timer = setInterval(() => {
    const video = document.getElementById('webgazerVideoFeed') as HTMLVideoElement | null
    if (!video || video.readyState < 2 || video.currentTime === lastFrame) return
    lastFrame = video.currentTime
    try {
      const face = landmarker.detectForVideo(video, performance.now()).faceLandmarks[0]
      detector.update(face ? (eyeAspectRatio(face, LEFT_EYE) + eyeAspectRatio(face, RIGHT_EYE)) / 2 : null, performance.now())
    } catch { detector.reset() }
  }, 1000 / 30)
  return () => { clearInterval(timer); landmarker.close(); detector.reset() }
}
