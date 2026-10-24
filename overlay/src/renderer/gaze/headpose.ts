// Head pointing from MediaPipe's head pose: where the nose points (yaw, pitch) maps to an absolute
// screen position. No pointer acceleration; calibration sets the gain, so small head turns can
// cover the whole screen. Same camera pipeline and regression as the eye tracker.
import { GazeRegression } from './iris'
import { MediaPipeGazeProvider, createMediaPipeTracker, type FaceFrame, type FaceTracker } from './mediapipe'

/** Yaw and pitch (radians) of the face's forward axis, from the 4×4 column-major transformation matrix. */
export function headAngles(matrix: ArrayLike<number> | null | undefined): [number, number] | null {
  if (!matrix || matrix.length < 16) return null
  const fx = matrix[8]!, fy = matrix[9]!, fz = matrix[10]!
  if (![fx, fy, fz].every(Number.isFinite)) return null
  return [Math.atan2(fx, fz), Math.atan2(fy, Math.hypot(fx, fz))]
}

/**
 * Head angles from the pose matrix are noisy; the nose tip's image position moves smoothly with a
 * head turn. Quadratic terms let the mapping bend toward the screen edges.
 */
export function headFeatures(face: FaceFrame): number[] | null {
  const angles = headAngles(face.matrix)
  const nose = face.landmarks[1]
  if (!angles && !nose) return null
  const [yaw, pitch] = angles ?? [0, 0]
  const [nx, ny] = nose ? [nose.x, nose.y] : [0, 0]
  return [yaw, pitch, nx, ny, yaw * yaw, pitch * pitch, yaw * pitch, nx * nx, ny * ny, nx * ny]
}

/** Blinks don't move the head, so unlike the eye tracker it keeps pointing with the eyes closed. */
export class HeadPoseProvider extends MediaPipeGazeProvider {
  constructor(createTracker: () => Promise<FaceTracker> = createMediaPipeTracker) {
    super(new GazeRegression(0.05), createTracker, headFeatures)
  }
}
