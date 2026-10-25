// Calibration (spec §5.3): 9 training dots one at a time, then 4 held-out validation dots that
// report the mean error. Gaze-only: after the eyes settle, each dot records samples for 1.2 s, then
// moves on. The regression's early predictions are far off by nature, so they can't gate training.
// With a helper (caregiver mode), a mouse click on each dot records it.
import { useEffect, useRef, useState, type CSSProperties, type JSX } from 'react'
import { agent, calibration, setGazeSource, useCalibration, useSession, type ValidationResult } from '../platform'
import { Card } from '../dock/Card'
import { AlertIcon, CheckIcon, CloseIcon, EyeIcon, RetryIcon } from '../dock/icons'

type Mode = 'gaze' | 'caregiver'
type Phase =
  | { kind: 'intro' }
  | { kind: 'starting' }
  | { kind: 'training'; index: number }
  | { kind: 'validating' }
  | { kind: 'result'; meanErrorPx: number; detail: ValidationResult; savedTo?: string | null }
  | { kind: 'error'; message: string }

/** A 6×5 grid over the whole screen, edges included, minus the corner under STOP, plus the centre. */
const GRID_X = [0.05, 0.23, 0.41, 0.59, 0.77, 0.95]
const GRID_Y = [0.06, 0.28, 0.5, 0.72, 0.94]
const UNDER_STOP = (fx: number, fy: number) => fx > 0.85 && fy < 0.15
/** Each round asks for a different head pose: the regression then copes with a moving head. */
export const ROUND_CAPTIONS = [
  'Keep your head still',
  'Now turn your head a little left or right as you go',
  'Now tilt your head a little up or down as you go'
] as const
/** 30 dots in 3 rounds; each round is spread over the whole screen (cells interleaved by (col+row) % 3). */
export const TRAIN_POINTS: readonly (readonly [number, number])[] = (() => {
  const cells = GRID_Y.flatMap((fy, row) => GRID_X.map((fx, col) => ({ fx, fy, round: (col + row) % 3 })))
    .filter(c => !UNDER_STOP(c.fx, c.fy))
  cells.push({ fx: 0.5, fy: 0.4, round: cells.filter(c => c.round === 0).length < 10 ? 0 : 1 })
  return [0, 1, 2].flatMap(r => cells.filter(c => c.round === r)).map(c => [c.fx, c.fy] as const)
})()
export const ROUND_SIZE = Math.ceil(TRAIN_POINTS.length / ROUND_CAPTIONS.length)
/** Head pointing: a 3×3 grid is enough to fit head angle → screen (the right column clears STOP). */
/** Head pointing: 5×4 dots over most of the screen (STOP is hidden while calibrating). */
export const HEAD_POINTS: readonly (readonly [number, number])[] =
  [0.1, 0.37, 0.63, 0.9].flatMap(fy => [0.08, 0.29, 0.5, 0.71, 0.92].map(fx => [fx, fy] as const))
/** Turning the head takes longer than moving the eyes: more time to arrive, then hold still. */
export const HEAD_SETTLE_MS = 1200
export const HEAD_CAPTURE_MS = 1500
export type CalibrationTarget = 'webgazer' | 'head'
export const VALIDATE_POINTS = [[0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]] as const
export const FIXATION_MS = 1000
/** Eyes need a moment to land on a new dot before samples are useful. */
export const SETTLE_MS = 400
export const CAREGIVER_CAPTURE_MS = 500
export const REDO_ABOVE_PX = 200
export const AUTO_START_S = 5

/** The last measured mean error, shown in Settings after the result screen is gone. */
export let lastCalibrationErrorPx: number | null = null
export let lastCalibrationResult: ValidationResult | null = null

/** "left/right 80 px · up/down 170 px · steady offset 120 px" when the split is known. */
export function errorBreakdown(r: ValidationResult): string | null {
  if (r.meanXPx === undefined || r.meanYPx === undefined) return null
  const parts = [`left/right ${Math.round(r.meanXPx)} px`, `up/down ${Math.round(r.meanYPx)} px`]
  if (r.offsetPx !== undefined) parts.push(`steady offset ${Math.round(r.offsetPx)} px (the rest is jitter, which smoothing reduces)`)
  return parts.join(' · ')
}
const TICK_MS = 100

const toPx = ([fx, fy]: readonly [number, number]) => ({ x: Math.round(fx * innerWidth), y: Math.round(fy * innerHeight) })

function Dot({ at, label, onClick, capturing }: { at: { x: number; y: number }; label: string; onClick?: () => void; capturing?: boolean }): JSX.Element {
  const style = { left: at.x, top: at.y } as CSSProperties
  return onClick
    ? <button type="button" className="calib-dot is-clickable" data-caregiver-clickable="" style={style} aria-label={label} onClick={onClick} />
    : <div className={`calib-dot${capturing ? ' is-capturing' : ''}`} style={style} aria-label={label} role="img" />
}

export function Calibration({ onDone, onCancel, target = 'webgazer' }:
  { onDone: () => void; onCancel: () => void; target?: CalibrationTarget }): JSX.Element {
  const head = target === 'head'
  const points = head ? HEAD_POINTS : TRAIN_POINTS
  const settleMs = head ? HEAD_SETTLE_MS : SETTLE_MS
  const captureMs = head ? HEAD_CAPTURE_MS : FIXATION_MS
  const [capturing, setCapturing] = useState(false)
  const s = useSession()
  const check = useCalibration()
  // Check dots get the same "turn, then hold still" cue: measuring starts after the settle time.
  const [checkHolding, setCheckHolding] = useState(false)
  useEffect(() => {
    setCheckHolding(false)
    if (!check.validating || !check.validationPoint) return
    const timer = setTimeout(() => setCheckHolding(true), head ? HEAD_SETTLE_MS : SETTLE_MS)
    return () => clearTimeout(timer)
  }, [check.validating, check.pointIndex, check.validationPoint])
  const [mode, setMode] = useState<Mode>(s.settings?.calibrationMode ?? 'gaze')
  const [phase, setPhase] = useState<Phase>({ kind: 'intro' })
  const [countdown, setCountdown] = useState(AUTO_START_S)
  const capture = useRef<number | null>(null) // caregiver click: ms of capture left

  const start = async (chosen: Mode) => {
    setMode(chosen)
    setPhase({ kind: 'starting' })
    try {
      await calibration.start(target)
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
    const dot = toPx(points[index]!)
    let elapsed = 0
    let held = 0
    capture.current = null
    const next = () => {
      if (index + 1 < points.length) setPhase({ kind: 'training', index: index + 1 })
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
      if (elapsed < settleMs) return
      if (held === 0) setCapturing(true)
      calibration.train(dot.x, dot.y)
      held += TICK_MS
      if (held >= captureMs) next()
    }, TICK_MS)
    setCapturing(false)
    return () => clearInterval(timer)
  }, [index, mode, settleMs, captureMs])

  // validate() rejects a second concurrent run, so start it once per validating phase (StrictMode
  // runs effects twice) and drop the answer only if the screen itself is gone.
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const validationStarted = useRef(false)
  useEffect(() => {
    if (phase.kind !== 'validating') { validationStarted.current = false; return }
    if (validationStarted.current) return
    validationStarted.current = true
    calibration.validate(VALIDATE_POINTS.map(toPx), head ? { settleMs: HEAD_SETTLE_MS, measureMs: HEAD_CAPTURE_MS } : undefined)
      .then(result => {
        const { meanErrorPx } = result
        lastCalibrationErrorPx = meanErrorPx
        lastCalibrationResult = result
        console.info(`[calibration] mean error ${Math.round(meanErrorPx)} px`, result)
        if (alive.current) setPhase({ kind: 'result', meanErrorPx, detail: result })
        // Debug: keep the raw numbers so the mapping can be tuned offline on real head movements.
        void calibration.exportLog({ result, mode, trainDots: points.map(toPx), checkDotsPlanned: VALIDATE_POINTS.map(toPx),
          timing: { settleMs, captureMs } })
          .then(savedTo => { if (alive.current && savedTo) setPhase(p => p.kind === 'result' ? { ...p, savedTo } : p) })
          .catch(() => {})
      })
      .catch(error => { if (alive.current) setPhase({ kind: 'error', message: error instanceof Error ? error.message : String(error) }) })
  }, [phase.kind])

  const finish = () => {
    // The frozen schema's 'webgazer' means "camera pointer"; the overlay runs it as head tracking.
    agent.updateSettings({ gazeSource: 'webgazer', calibrationMode: mode })
    calibration.save()
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
          <h1 className="screen-title">{head ? 'Calibrate head pointing' : 'Calibrate eye tracking'}</h1>
          <p className="screen-lead">{head
            ? `${points.length} dots appear one at a time. Point your nose at each dot: a small, comfortable head turn is enough.`
            : `${points.length} dots appear one at a time, in 3 rounds (about 45 s). Look at each dot until it moves on.`}
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
      const at = toPx(points[phase.index]!)
      const instruction = head ? (capturing ? 'Hold still…' : 'Turn your nose to the dot (small turn)')
        : ROUND_CAPTIONS[Math.min(ROUND_CAPTIONS.length - 1, Math.floor(phase.index / ROUND_SIZE))]
      body = (
        <>
          <p className="calib-caption">
            {instruction}
            {mode === 'caregiver' ? ' · Helper: click the dot while they look at it' : head ? '' : ' · look at the dot'}
            {' '}· {phase.index + 1} of {points.length}</p>
          <Dot at={at} label={`Calibration dot ${phase.index + 1}`} capturing={capturing}
            onClick={mode === 'caregiver' ? () => { if (capture.current === null) capture.current = CAREGIVER_CAPTURE_MS } : undefined} />
        </>
      )
      break
    }
    case 'validating':
      body = (
        <>
          <p className="calib-caption">
            Checking: {checkHolding ? 'hold still…' : head ? 'turn your nose to the dot' : 'look at the dot'}
            {' '}· {check.pointIndex + 1} of {VALIDATE_POINTS.length}</p>
          {check.validationPoint && <Dot at={check.validationPoint} label="Check dot" capturing={checkHolding} />}
        </>
      )
      break
    case 'result': {
      const good = phase.meanErrorPx <= REDO_ABOVE_PX
      body = (
        <div className="calib-panel">
          <h1 className="screen-title">{good ? 'Calibration done' : 'Not accurate enough yet'}</h1>
          {errorBreakdown(phase.detail) && <p className="screen-lead">{errorBreakdown(phase.detail)}</p>}
          {phase.savedTo && <p className="screen-lead">Calibration data saved to {phase.savedTo.replace(/^.*\/(\.debug\/)/, '$1')}</p>}
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
          <h1 className="screen-title"><AlertIcon /> {head ? 'Head tracking' : 'Eye tracking'} could not start</h1>
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
