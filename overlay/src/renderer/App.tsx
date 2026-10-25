// Screen routing from the session (spec §6.2, §11): confirm > running task > choice > (idle only:
// permissions checklist > calibration > settings) > result > dock.
import { useEffect, useLayoutEffect, useState, type JSX } from 'react'
import { DwellTarget, agent, useGaze, useSession } from './platform'
import { AutoDock } from './dock/AutoDock'
import { InfoPanel } from './dock/Card'
import { ChoiceCards } from './dock/ChoiceCards'
import { ModeTabs } from './dock/ModeTabs'
import { ResultCards } from './dock/ResultCards'
import { StatusLine, StatusPill } from './dock/StatusLine'
import { deriveStatus } from './dock/status'
import { ComposerField } from './keyboard/T9Keyboard'
import { TypePanel } from './keyboard/TypePanel'
import { useT9Index } from './keyboard/useT9Index'
import { useTypeFlow } from './keyboard/useTypeFlow'
import { Calibration, type CalibrationTarget } from './screens/Calibration'
import { ConfirmScreen } from './screens/ConfirmScreen'
import { Onboarding } from './screens/Onboarding'
import { Recenter } from './screens/Recenter'
import { QuitCorner, SettingsCorner, SettingsPanel, savedHeadPointer, toggleHeadPointer } from './screens/Settings'
import { missingPermissions } from './screens/permissions'
import { StopTarget } from './stop/StopTarget'
import { GazeDot } from './styles/GazeDot'

type Screen = 'dock' | 'settings' | 'calibration' | 'recenter'

const DOCK_HIDDEN_KEY = 'gaze.dockHidden'

export function App(): JSX.Element {
  const s = useSession()
  const gaze = useGaze()
  const flow = useTypeFlow(s)
  const index = useT9Index(s.profile)
  const status = deriveStatus(s, s.mode === 'type' ? flow.awaiting : null)
  const [screen, setScreen] = useState<Screen>('dock')
  const [calibrationTarget, setCalibrationTarget] = useState<CalibrationTarget>('webgazer')
  useEffect(() => { if (savedHeadPointer()) toggleHeadPointer(true) }, [])
  // The dock can shrink to one "Open" pill so the screen stays visible; remembered across launches.
  const [hidden, setHiddenState] = useState(() => { try { return localStorage.getItem(DOCK_HIDDEN_KEY) === '1' } catch { return false } })
  const setHidden = (value: boolean) => {
    setHiddenState(value)
    try { localStorage.setItem(DOCK_HIDDEN_KEY, value ? '1' : '0') } catch { /* session only */ }
  }
  // Open by itself when the agent has something for the user: a new list, a choice or a result.
  const listId = s.list?.listId ?? null
  useEffect(() => { if (listId || s.choice || s.result) setHiddenState(false) }, [listId, !!s.choice, !!s.result])
  // Hide matches the width of the dock's last card (e.g. "Something else"), whatever the grid gives it.
  useLayoutEffect(() => {
    const root = document.documentElement
    const update = () => {
      const cards = document.querySelectorAll<HTMLElement>('.dock-content .card-row > *')
      const last = cards[cards.length - 1]
      if (last) root.style.setProperty('--last-card-w', `${Math.round(last.getBoundingClientRect().width)}px`)
    }
    update()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update)
    const row = document.querySelector('.dock-content')
    if (row) observer?.observe(row)
    addEventListener('resize', update)
    return () => { observer?.disconnect(); removeEventListener('resize', update) }
  })
  // Eye tracking can't predict anything before training, so it is offered once per launch.
  const [calibrationOffered, setCalibrationOffered] = useState(false)

  const busy = !!s.task || !!s.confirm || !!s.choice || !!s.pendingSelect
  const onboarding = !busy && s.ready && missingPermissions(s, gaze.source).length > 0
  const calibrating = !busy && !onboarding
    && (screen === 'calibration' || (gaze.source === 'webgazer' && !calibrationOffered))
  const closeCalibration = () => { setCalibrationOffered(true); setScreen('dock') }
  // STOP with nothing running: back to the plain main menu (empty Auto dock) from anywhere; clears
  // suggestions and a pending "Thinking…". No new suggestion request: only the Auto tab does that.
  const backToDock = () => {
    closeCalibration()
    flow.backToKeys()
    agent.setMode('auto')
  }

  let body: JSX.Element
  if (s.confirm) {
    body = <ConfirmScreen confirm={s.confirm} />
  } else if (s.task && !s.choice) {
    // While the agent works, the dock collapses so the user can watch (§6.2).
    body = <div className="bottom"><StatusPill task={s.task} status={status} /></div>
  } else if (onboarding) {
    body = <Onboarding />
  } else if (!busy && screen === 'recenter') {
    body = <Recenter onDone={() => setScreen('dock')} />
  } else if (calibrating) {
    body = <Calibration key={calibrationTarget} target={calibrationTarget} onDone={closeCalibration} onCancel={closeCalibration} />
  } else if (hidden && s.ready && screen === 'dock' && flow.view === 'keys') {
    body = (
      <div className="bottom bottom-hidden">
        <StatusLine status={status} />
        <DwellTarget id="dock-open" variant="card" clickable onSelect={() => setHidden(false)} className="target open-pill">
          <span className="open-pill-label">Open copilot</span>
          <span className="open-pill-hint">Auto ideas · Type a request</span>
        </DwellTarget>
      </div>
    )
  } else {
    let content: JSX.Element
    let tabs = true
    if (s.choice) { content = <ChoiceCards choice={s.choice} />; tabs = false }
    else if (!s.ready) content = (
      <InfoPanel className="connection-panel">
        <span className="info-title">{status.text}</span>
        <span className="info-text">{status.kind === 'error'
          ? 'Check that the agent is running, then restart the overlay.'
          : 'The cards appear as soon as the agent answers.'}</span>
      </InfoPanel>
    )
    else if (screen === 'settings') {
      content = <SettingsPanel onRecalibrate={target => { setCalibrationTarget(target); setScreen('calibration') }}
        onRecenter={() => setScreen('recenter')} onClose={() => setScreen('dock')} />
      tabs = false
    }
    else if (s.result) content = <ResultCards />
    else if (s.mode === 'auto') content = <AutoDock />
    else content = <TypePanel flow={flow} index={index} />
    const typing = tabs && s.ready && !s.result && s.mode === 'type' && flow.view === 'keys'
    body = (
      <>
        {!busy && s.ready && screen === 'dock' && <SettingsCorner onSelect={() => setScreen('settings')} />}
        {!busy && <QuitCorner />}
        <div className={`bottom${typing ? ' is-typing' : ''}`}>
          <div className="above-dock">
            <StatusLine status={status} />
            {gaze.clickMode && <span className="mode-chip">Click mode · ⌃⌥⌘D</span>}
            {typing && <ComposerField composer={flow.composer} index={index} />}
            {/* Auto / main menu: right above the last card, same width. Typing: under STOP (CSS). */}
            {s.ready && screen === 'dock' && (
              <DwellTarget id="dock-hide" variant="card" clickable onSelect={() => setHidden(true)}
                className={`target dock-hide${typing ? ' is-floating' : ''}`}>
                <span className="dock-hide-label">Hide</span>
                <span className="dock-hide-hint">Free the screen</span>
              </DwellTarget>
            )}
          </div>
          <section className={`dock${typing ? ' dock-typing' : ''}`}>
            {tabs && <ModeTabs mode={s.mode} disabled={!s.ready || !!s.pendingSelect} />}
            <div className="dock-content">{content}</div>
          </section>
        </div>
      </>
    )
  }

  return (
    <div className={`overlay density-${s.settings?.density ?? 'large'}${gaze.headPointer || gaze.source === 'head' ? ' head-pointer' : ''}`}>
      {body}
      {/* Not during calibration: it sits on the dots' corner and distracts. No task can run then. */}
      {!calibrating && screen !== 'recenter' && <StopTarget onIdle={backToDock} />}
      <GazeDot />
    </div>
  )
}
