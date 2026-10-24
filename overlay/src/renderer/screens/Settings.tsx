// Settings (spec §5.2, §5.3, §10): dwell time, gaze source, text size, blink select, calibration
// helper, and "Recalibrate". Values shown come only from settings_result (the session), never
// from local guesses.
import type { JSX } from 'react'
import { DwellTarget, agent, quitApp, setClickMode, setGazeSource, useGaze, useSession, type Settings as SettingsValue } from '../platform'
import { Card, InfoPanel } from '../dock/Card'
import { CheckIcon, CloseIcon, RetryIcon, SlidersIcon } from '../dock/icons'

export const DWELL_MIN_MS = 500
export const DWELL_MAX_MS = 2000
export const DWELL_STEP_MS = 100
/** Rarely needed and top-left, where people read: a slower dwell avoids opening it by accident. */
export const SETTINGS_DWELL_MS = 1500

const clamp = (ms: number) => Math.min(DWELL_MAX_MS, Math.max(DWELL_MIN_MS, ms))

export function SettingsPanel({ onRecalibrate, onClose }: { onRecalibrate: () => void; onClose: () => void }): JSX.Element {
  const s = useSession()
  const gaze = useGaze()
  const settings = s.settings
  if (!settings) {
    return <InfoPanel><span className="info-title">Waiting for the agent…</span></InfoPanel>
  }
  const update = (patch: Partial<SettingsValue>) => agent.updateSettings(patch)
  const source = gaze.source
  return (
    <div className="dock-section">
      <h2 className="dock-question">Settings</h2>
      <div className="card-row settings-grid">
        <InfoPanel className="value-panel">
          <span className="info-title">Dwell time</span>
          <span className="value-big">{settings.dwellMs} ms</span>
        </InfoPanel>
        <Card id="set-dwell-faster" label="Faster" detail={`−${DWELL_STEP_MS} ms`} clickable
          disabled={settings.dwellMs <= DWELL_MIN_MS} onSelect={() => update({ dwellMs: clamp(settings.dwellMs - DWELL_STEP_MS) })} />
        <Card id="set-dwell-slower" label="Slower" detail={`+${DWELL_STEP_MS} ms`} clickable
          disabled={settings.dwellMs >= DWELL_MAX_MS} onSelect={() => update({ dwellMs: clamp(settings.dwellMs + DWELL_STEP_MS) })} />
        <Card id="set-source" label={source === 'mouse' ? 'Gaze: mouse' : 'Gaze: eye tracking'}
          detail={source === 'mouse' ? 'Switch to eye tracking' : 'Switch to mouse'} clickable
          onSelect={() => {
            const next = source === 'mouse' ? 'webgazer' : 'mouse'
            if (next === 'webgazer') onRecalibrate() // the tracker needs training before it can be used
            else { setGazeSource('mouse'); update({ gazeSource: 'mouse' }) }
          }} />
        <Card id="set-click-mode" label={gaze.clickMode ? 'Select: by click' : 'Select: by looking'}
          detail={gaze.clickMode ? 'Dwell off, STOP still dwells (⌃⌥⌘D)' : 'Switch to mouse clicks (⌃⌥⌘D)'} clickable
          onSelect={() => setClickMode(!gaze.clickMode)} />
        <Card id="set-density" label={settings.density === 'large' ? 'Text: large' : 'Text: compact'}
          detail={settings.density === 'large' ? 'Switch to compact' : 'Switch to large'} clickable
          onSelect={() => update({ density: settings.density === 'large' ? 'compact' : 'large' })} />
        <Card id="set-blink" label={settings.blinkSelect ? 'Blink select: on' : 'Blink select: off'}
          detail="A long blink selects" clickable onSelect={() => update({ blinkSelect: !settings.blinkSelect })} />
        <Card id="set-calib-mode" label={settings.calibrationMode === 'caregiver' ? 'Calibrate: with helper' : 'Calibrate: gaze only'}
          detail="How the dots are recorded" clickable
          onSelect={() => update({ calibrationMode: settings.calibrationMode === 'caregiver' ? 'gaze' : 'caregiver' })} />
        <Card id="set-recalibrate" label="Recalibrate" detail="Run the dots again" icon={<RetryIcon />} clickable onSelect={onRecalibrate} />
        <Card id="set-close" label="Done" detail="Back to the dock" icon={<CheckIcon />} clickable onSelect={onClose} />
      </div>
    </div>
  )
}

/** Quitting is final: a real click, or a deliberately long dwell. */
export const QUIT_DWELL_MS = 2000

export function QuitCorner(): JSX.Element {
  return (
    <DwellTarget id="quit-app" variant="card" dwellMs={QUIT_DWELL_MS} clickable onSelect={quitApp}
      className="target settings-corner quit-corner">
      <span className="card-icon"><CloseIcon /></span>
      <span className="settings-corner-label">Quit</span>
    </DwellTarget>
  )
}

/** The way into Settings: top-left corner, mirroring STOP, only while idle. */
export function SettingsCorner({ onSelect }: { onSelect: () => void }): JSX.Element {
  return (
    <DwellTarget id="settings-open" variant="card" dwellMs={SETTINGS_DWELL_MS} clickable onSelect={onSelect}
      className="target settings-corner">
      <span className="card-icon"><SlidersIcon /></span>
      <span className="settings-corner-label">Settings</span>
    </DwellTarget>
  )
}
