// Where the overlay thinks you are looking: in debug / mouse = gaze mode, and always with eye tracking.
import type { CSSProperties, JSX } from 'react'
import { useGaze } from '../platform'

export function GazeDot(): JSX.Element | null {
  const gaze = useGaze()
  if (!gaze.point || (!gaze.debug && gaze.source === 'mouse')) return null
  const style = { transform: `translate(${gaze.point.x}px, ${gaze.point.y}px)` } as CSSProperties
  return <div className="gaze-dot" style={style} aria-hidden="true" />
}
