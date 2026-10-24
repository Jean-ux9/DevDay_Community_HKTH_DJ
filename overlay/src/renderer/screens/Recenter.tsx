// Recenter (about 3 s): one centre dot re-zeros camera-tracking drift. Posture changes slide the
// whole mapping; this fixes that without a full calibration.
import { useEffect, useRef, useState, type CSSProperties, type JSX } from 'react'
import { calibration } from '../platform'
import { HEAD_CAPTURE_MS, HEAD_SETTLE_MS } from './Calibration'

export function Recenter({ onDone }: { onDone: () => void }): JSX.Element {
  const [phase, setPhase] = useState<'turn' | 'hold' | 'done' | 'error'>('turn')
  const [message, setMessage] = useState('')
  const started = useRef(false)
  const at = { x: Math.round(innerWidth / 2), y: Math.round(innerHeight / 2) }

  useEffect(() => {
    if (started.current) return // StrictMode runs effects twice; recenter once
    started.current = true
    const hold = setTimeout(() => setPhase(p => (p === 'turn' ? 'hold' : p)), HEAD_SETTLE_MS)
    calibration.recenter(at.x, at.y, HEAD_SETTLE_MS, HEAD_CAPTURE_MS)
      .then(() => { setPhase('done'); setTimeout(onDone, 700) })
      .catch(error => { setPhase('error'); setMessage(error instanceof Error ? error.message : String(error)); setTimeout(onDone, 2500) })
    return () => clearTimeout(hold)
  }, [])

  const style = { left: at.x, top: at.y } as CSSProperties
  const caption = phase === 'turn' ? 'Recenter: turn your nose to the dot' : phase === 'hold' ? 'Hold still…'
    : phase === 'done' ? 'Recentered' : `Could not recenter: ${message}`
  return (
    <section className="calibration-screen is-dots" aria-label="Recenter">
      <p className="calib-caption">{caption}</p>
      <div className={`calib-dot${phase === 'hold' ? ' is-capturing' : ''}`} style={style} role="img" aria-label="Recenter dot" />
    </section>
  )
}
