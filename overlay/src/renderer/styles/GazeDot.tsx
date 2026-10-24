// Where the overlay thinks you are looking; shown only in debug (and mouse = gaze) mode.
import type { CSSProperties, JSX } from 'react'
import { useGaze } from '../platform'

export function GazeDot(): JSX.Element | null {
  const gaze = useGaze()
  if (!gaze.debug || !gaze.point) return null
  const style = { transform: `translate(${gaze.point.x}px, ${gaze.point.y}px)` } as CSSProperties
  return <div className="gaze-dot" style={style} aria-hidden="true" />
}
