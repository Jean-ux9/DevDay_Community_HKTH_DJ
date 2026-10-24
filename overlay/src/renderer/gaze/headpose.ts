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

const headFeatures = (face: FaceFrame): number[] | null => headAngles(face.matrix)

/** Blinks don't move the head, so unlike the eye tracker it keeps pointing with the eyes closed. */
export class HeadPoseProvider extends MediaPipeGazeProvider {
  constructor(createTracker: () => Promise<FaceTracker> = createMediaPipeTracker) {
    super(new GazeRegression(1e-3), createTracker, headFeatures)
  }
}
