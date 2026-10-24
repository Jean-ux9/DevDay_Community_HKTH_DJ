// Where the overlay thinks you are looking: in debug / mouse = gaze mode, and with camera tracking.
// In head pointer mode the drawn dot is pulled toward the centre of the card being dwelled, and a
// line shows a magnetic pull. Drawing only: dwell still uses the real position, so leaving a card
// takes no extra head movement.
import type { CSSProperties, JSX } from 'react'
import { useGaze } from '../platform'

/** How far (0..1) the drawn dot moves toward the active card's centre in head pointer mode. */
export const CENTER_PULL = 0.35

function activeRect(): DOMRect | null {
  const el = document.querySelector('[data-dwell="active"], [data-dwell="armed"]')
  return el ? el.getBoundingClientRect() : null
}

export function GazeDot(): JSX.Element | null {
  const gaze = useGaze()
  if (!gaze.point || (!gaze.debug && gaze.source === 'mouse')) return null
  const head = gaze.headPointer || gaze.source === 'head'
  const rect = head ? activeRect() : null
  let { x, y } = gaze.point
  let line: { x2: number; y2: number } | null = null
  if (rect && rect.width > 0) {
    const cx = rect.x + rect.width / 2, cy = rect.y + rect.height / 2
    const outside = x < rect.x || x > rect.right || y < rect.y || y > rect.bottom
    if (outside) line = { x2: Math.min(Math.max(x, rect.x), rect.right), y2: Math.min(Math.max(y, rect.y), rect.bottom) }
    x += (cx - x) * CENTER_PULL
    y += (cy - y) * CENTER_PULL
  }
  const style = { transform: `translate(${x}px, ${y}px)` } as CSSProperties
  return (
    <>
      {line && (
        <svg className="magnet-line" aria-hidden="true">
          <line x1={gaze.point.x} y1={gaze.point.y} x2={line.x2} y2={line.y2} />
        </svg>
      )}
      <div className={`gaze-dot${rect ? ' is-snapped' : ''}`} style={style} aria-hidden="true" />
    </>
  )
}
