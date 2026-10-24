// Calibration (spec §5.3): 9 training dots one at a time, then 4 held-out validation dots that
// report the mean error. Gaze-only dots advance after 1.2 s of fixation within 120 px; with a
// helper (caregiver mode), a mouse click on each dot records it.
import { useEffect, useRef, useState, type CSSProperties, type JSX } from 'react'
import { agent, calibration, setGazeSource, useCalibration, useGaze, useSession } from '../platform'
import { Card } from '../dock/Card'
import { AlertIcon, CheckIcon, CloseIcon, EyeIcon, RetryIcon } from '../dock/icons'

type Mode = 'gaze' | 'caregiver'
type Phase =
  | { kind: 'intro' }
  | { kind: 'starting' }
  | { kind: 'training'; index: number }
  | { kind: 'validating' }
  | { kind: 'result'; meanErrorPx: number }
  | { kind: 'error'; message: string }

/** Fractions of the viewport; the right column stays clear of STOP. Validation uses held-out positions. */
export const TRAIN_POINTS = [[0.08, 0.1], [0.5, 0.1], [0.8, 0.1], [0.08, 0.5], [0.5, 0.5], [0.8, 0.5],
  [0.08, 0.9], [0.5, 0.9], [0.8, 0.9]] as const
export const VALIDATE_POINTS = [[0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]] as const
export const FIXATION_MS = 1200
export const FIXATION_PX = 120
/** Eyes need a moment to land on a new dot before samples are useful. */
export const SETTLE_MS = 400
/** Before any training there is no prediction to check fixation with, so a dot also advances on time. */
export const MAX_DOT_MS = 4000
export const CAREGIVER_CAPTURE_MS = 500
export const REDO_ABOVE_PX = 200
export const AUTO_START_S = 5
const TICK_MS = 100

const toPx = ([fx, fy]: readonly [number, number]) => ({ x: Math.round(fx * innerWidth), y: Math.round(fy * innerHeight) })

function Dot({ at, label, onClick }: { at: { x: number; y: number }; label: string; onClick?: () => void }): JSX.Element {
  const style = { left: at.x, top: at.y } as CSSProperties
  return onClick
    ? <button type="button" className="calib-dot is-clickable" data-caregiver-clickable="" style={style} aria-label={label} onClick={onClick} />
    : <div className="calib-dot" style={style} aria-label={label} role="img" />
}

export function Calibration({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }): JSX.Element {
  const s = useSession()
  const gaze = useGaze()
  const check = useCalibration()
  const [mode, setMode] = useState<Mode>(s.settings?.calibrationMode ?? 'gaze')
  const [phase, setPhase] = useState<Phase>({ kind: 'intro' })
  const [countdown, setCountdown] = useState(AUTO_START_S)
  const gazePoint = useRef(gaze.point)
  gazePoint.current = gaze.point
  const capture = useRef<number | null>(null) // caregiver click: ms of capture left

  const start = async (chosen: Mode) => {
    setMode(chosen)
    setPhase({ kind: 'starting' })
    try {
      await calibration.start()
      setPhase({ kind: 'training', index: 0 })
    } catch (error) {
      setPhase({ kind: 'error', message: error instanceof Error ? error.message : String(error) })
    }
  }

  // A user alone can't dwell before the tracker knows their eyes: start by itself after a countdown.
  useEffect(() => {
    if (phase.kind !== 'intro') return
    if (countdown <= 0) { void start(mode); return }
    const timer = setTimeout(() => setCountdown(c => c - 1), 1000)
    return () => clearTimeout(timer)
  }, [phase.kind, countdown])

  const index = phase.kind === 'training' ? phase.index : -1
  useEffect(() => {
    if (index < 0) return
    const dot = toPx(TRAIN_POINTS[index]!)
    let elapsed = 0
    let held = 0
    capture.current = null
    const next = () => {
      if (index + 1 < TRAIN_POINTS.length) setPhase({ kind: 'training', index: index + 1 })
      else setPhase({ kind: 'validating' })
    }
    const timer = setInterval(() => {
      elapsed += TICK_MS
      if (mode === 'caregiver') {
        if (capture.current === null) return
        calibration.train(dot.x, dot.y)
        capture.current -= TICK_MS
        if (capture.current <= 0) next()
        return
      }
      if (elapsed < SETTLE_MS) return
      const p = gazePoint.current
      const near = !p || Math.hypot(p.x - dot.x, p.y - dot.y) <= FIXATION_PX
      if (near) { calibration.train(dot.x, dot.y); held += TICK_MS } else held = 0
      if (held >= FIXATION_MS || elapsed >= MAX_DOT_MS) next()
    }, TICK_MS)
    return () => clearInterval(timer)
  }, [index, mode])

  // validate() rejects a second concurrent run, so start it once per validating phase (StrictMode
  // runs effects twice) and drop the answer only if the screen itself is gone.
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const validationStarted = useRef(false)
  useEffect(() => {
    if (phase.kind !== 'validating') { validationStarted.current = false; return }
    if (validationStarted.current) return
    validationStarted.current = true
    calibration.validate(VALIDATE_POINTS.map(toPx))
      .then(({ meanErrorPx }) => { if (alive.current) setPhase({ kind: 'result', meanErrorPx }) })
      .catch(error => { if (alive.current) setPhase({ kind: 'error', message: error instanceof Error ? error.message : String(error) }) })
  }, [phase.kind])

  const finish = () => {
    agent.updateSettings({ gazeSource: 'webgazer', calibrationMode: mode })
    onDone()
  }
  const useMouse = () => {
    setGazeSource('mouse')
    agent.updateSettings({ gazeSource: 'mouse' })
    onCancel()
  }

  let body: JSX.Element
  switch (phase.kind) {
    case 'intro':
      body = (
        <div className="calib-panel">
          <h1 className="screen-title">Calibrate eye tracking</h1>
          <p className="screen-lead">Nine dots appear one at a time. Look at each dot until it moves on.
            {' '}Starts by itself in {countdown} s{mode === 'caregiver' ? ', with a helper clicking each dot' : ''}.</p>
          <div className="card-row">
            <Card id="calib-start-gaze" label="Start" detail="I will look at each dot" icon={<EyeIcon />} clickable
              onSelect={() => void start('gaze')} />
            <Card id="calib-start-caregiver" label="Start with a helper" detail="A helper clicks each dot" clickable
              onSelect={() => void start('caregiver')} />
            <Card id="calib-cancel" label="Not now" detail="Back to the dock" icon={<CloseIcon />} clickable
              className="back-card" onSelect={onCancel} />
          </div>
        </div>
      )
      break
    case 'starting':
      body = <div className="calib-panel"><h1 className="screen-title">Starting the camera…</h1></div>
      break
    case 'training': {
      const at = toPx(TRAIN_POINTS[phase.index]!)
      body = (
        <>
          <p className="calib-caption">{mode === 'caregiver' ? 'Helper: click the dot while they look at it' : 'Look at the dot'}
            {' '}· {phase.index + 1} of {TRAIN_POINTS.length}</p>
          <Dot at={at} label={`Calibration dot ${phase.index + 1}`}
            onClick={mode === 'caregiver' ? () => { if (capture.current === null) capture.current = CAREGIVER_CAPTURE_MS } : undefined} />
        </>
      )
      break
    }
    case 'validating':
      body = (
        <>
          <p className="calib-caption">Checking: look at the dot · {check.pointIndex + 1} of {VALIDATE_POINTS.length}</p>
          {check.validationPoint && <Dot at={check.validationPoint} label="Check dot" />}
        </>
      )
      break
    case 'result': {
      const good = phase.meanErrorPx <= REDO_ABOVE_PX
      body = (
        <div className="calib-panel">
          <h1 className="screen-title">{good ? 'Calibration done' : 'Not accurate enough yet'}</h1>
          <p className="screen-lead">Average error: {Math.round(phase.meanErrorPx)} px.
            {' '}{good ? 'You can recalibrate any time from Settings.' : 'Redo it, keeping your head still.'}</p>
          <div className="card-row">
            {!good && <Card id="calib-redo" label="Redo" detail="Run the dots again" icon={<RetryIcon />} clickable
              onSelect={() => void start(mode)} />}
            <Card id="calib-done" label={good ? 'Done' : 'Keep it anyway'} icon={<CheckIcon />} clickable onSelect={finish} />
            {good && <Card id="calib-redo" label="Redo" detail="Run the dots again" icon={<RetryIcon />} clickable
              className="back-card" onSelect={() => void start(mode)} />}
          </div>
        </div>
      )
      break
    }
    case 'error':
      body = (
        <div className="calib-panel">
          <h1 className="screen-title"><AlertIcon /> Eye tracking could not start</h1>
          <p className="screen-lead">{phase.message}</p>
          <div className="card-row">
            <Card id="calib-retry" label="Try again" icon={<RetryIcon />} clickable onSelect={() => void start(mode)} />
            <Card id="calib-mouse" label="Use the mouse instead" detail="Mouse = gaze" clickable onSelect={useMouse} />
            <Card id="calib-close" label="Close" icon={<CloseIcon />} clickable className="back-card" onSelect={onCancel} />
          </div>
        </div>
      )
  }
  // Opaque only while dots are shown; otherwise the desktop stays visible (e.g. the camera prompt).
  const dots = phase.kind === 'training' || phase.kind === 'validating'
  return <section className={`calibration-screen${dots ? ' is-dots' : ''}`} aria-label="Calibration">{body}</section>
}
