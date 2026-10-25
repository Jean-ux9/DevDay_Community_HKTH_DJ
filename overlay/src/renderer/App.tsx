// Screen routing from the session (spec §6.2, §11): confirm > running task > choice > (idle only:
// permissions checklist > calibration > settings) > result > dock.
import { useEffect, useState, type CSSProperties, type JSX } from 'react'
import { agent, isPointerTrained, useGaze, useSession } from './platform'
import { AutoDock } from './dock/AutoDock'
import { Card, InfoPanel, PlanCard } from './dock/Card'
import { ChoiceCards } from './dock/ChoiceCards'
import { CornerTarget } from './dock/CornerTarget'
import { AlertIcon, CheckIcon, EyeClosedIcon, EyeIcon } from './dock/icons'
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
import { QuitCorner, SettingsCorner, SettingsPanel } from './screens/Settings'
import { missingPermissions } from './screens/permissions'
import { StopTarget } from './stop/StopTarget'
import { GazeDot } from './styles/GazeDot'

type Screen = 'dock' | 'settings' | 'calibration' | 'recenter'

const DOCK_HIDDEN_KEY = 'gaze.dockHidden'

/**
 * How a task ended after the user approved its send/buy/delete/submit/post. The agent only learns that
 * the app accepted it, so there is no "Done" and no success glow; a failure or STOP after the approval
 * may still have gone through, so it is not "Not done" either. The summary is shown as the agent wrote it.
 */
export function ApprovedOutcome(): JSX.Element | null {
  const s = useSession()
  const result = s.result
  if (!result) return null
  const recovery = s.list?.source === 'recovery' ? s.list : null
  const [title, note, icon, tone] = result.ok
    ? ['Handed to the app', 'The app accepted it. Delivery is not confirmed.', <CheckIcon />, 'is-look']
    : ['Not confirmed', 'It may have gone through. Check before trying again.', <AlertIcon />, 'is-failed']
  return (
    <div className="card-row result-row" style={{ '--n': recovery?.items.length || 1 } as CSSProperties}>
      <InfoPanel className={`summary-panel is-approved ${tone}`}>
        <span className="info-title">{icon}{title}</span>
        <span className="info-text">{result.summary}</span>
        <span className="info-text">{note}</span>
      </InfoPanel>
      {recovery ? recovery.items.map(plan => (
        <PlanCard key={`${recovery.listId}:${plan.id}`} id={`recovery-${recovery.listId}-${plan.id}`} plan={plan}
          disabled={!!s.pendingSelect} onSelect={() => agent.selectPlan(recovery.listId, plan.id)} />
      )) : (
        <Card id={`result-ok-${result.taskId}`} label="OK" detail="Back to the dock" icon={<CheckIcon />}
          onSelect={() => agent.setMode(s.mode)} />
      )}
    </div>
  )
}

export function App(): JSX.Element {
  const s = useSession()
  const gaze = useGaze()
  const flow = useTypeFlow(s)
  const index = useT9Index(s.profile)
  const status = deriveStatus(s, s.mode === 'type' ? flow.awaiting : null)
  const [screen, setScreen] = useState<Screen>('dock')
  const [calibrationTarget, setCalibrationTarget] = useState<CalibrationTarget>('head')
  // The eye under Back hides the dock so the screen stays visible; remembered across launches.
  const [hidden, setHiddenState] = useState(() => { try { return localStorage.getItem(DOCK_HIDDEN_KEY) === '1' } catch { return false } })
  const setHidden = (value: boolean) => {
    setHiddenState(value)
    try { localStorage.setItem(DOCK_HIDDEN_KEY, value ? '1' : '0') } catch { /* session only */ }
  }
  // Open by itself when the agent has something for the user: a new list, a choice or a result.
  const listId = s.list?.listId ?? null
  useEffect(() => { if (listId || s.choice || s.result) setHiddenState(false) }, [listId, !!s.choice, !!s.result])
  // The task whose action the user approved on the confirm screen (not a demo no-op): its result is
  // told honestly by ApprovedOutcome instead of ResultCards' "Done" / "Not done".
  const [approvedTask, setApprovedTask] = useState<string | null>(null)
  // Eye tracking can't predict anything before training, so it is offered once per launch.
  const [calibrationOffered, setCalibrationOffered] = useState(false)

  const busy = !!s.task || !!s.confirm || !!s.choice || !!s.pendingSelect
  const onboarding = !busy && s.ready && missingPermissions(s, gaze.source).length > 0
  const calibrating = !busy && !onboarding
    && (screen === 'calibration' || (gaze.source !== 'mouse' && !calibrationOffered && !isPointerTrained(gaze.source)))
  const closeCalibration = () => { setCalibrationOffered(true); setScreen('dock') }
  // STOP with nothing running: back to the plain main menu (empty Auto dock) from anywhere; clears
  // suggestions and a pending "Thinking…". No new suggestion request: only the Auto tab does that.
  const backToDock = () => {
    closeCalibration()
    flow.backToKeys()
    agent.setMode('auto')
  }

  // Top of the right column: an open eye hides the dock; a closed eye (dock hidden) brings it back.
  const hideToggle = (
    <CornerTarget id="dock-hide" clickable onSelect={() => setHidden(!hidden)}
      className={`corner-hide${hidden ? ' is-hidden' : ''}`}
      icon={hidden ? <EyeClosedIcon /> : <EyeIcon />} label={hidden ? 'Show' : 'Hide'} />
  )

  // The corner column (top-right): which controls the current screen shows, set by the branch below.
  let corners = { hide: false, settings: false, quit: false }
  let body: JSX.Element
  if (s.confirm) {
    const { taskId, demo_noop } = s.confirm
    body = <ConfirmScreen confirm={s.confirm}
      onAnswer={(confirmed, sent) => { if (confirmed && sent && !demo_noop) setApprovedTask(taskId) }} />
  } else if (s.task && !s.choice) {
    // While the agent works, the dock collapses so the user can watch (§6.2).
    body = <div className="bottom"><StatusPill task={s.task} status={status} /></div>
  } else if (onboarding) {
    body = <Onboarding />
  } else if (!busy && screen === 'recenter') {
    body = <Recenter onDone={() => setScreen('dock')} />
  } else if (calibrating) {
    // From Settings: the chosen target. On launch: the camera source that still needs calibrating.
    const target: CalibrationTarget = screen === 'calibration' || gaze.source === 'mouse' ? calibrationTarget : gaze.source
    body = <Calibration key={target} target={target} onDone={closeCalibration} onCancel={closeCalibration} />
  } else if (hidden && s.ready && screen === 'dock' && flow.view === 'keys') {
    corners = { hide: true, settings: false, quit: false }
    body = <div className="bottom bottom-hidden"><StatusLine status={status} /></div>
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
        onRecenter={() => setScreen('recenter')} />
      tabs = false
    }
    else if (s.result) content = s.result.taskId === approvedTask ? <ApprovedOutcome /> : <ResultCards />
    else if (s.mode === 'auto') content = <AutoDock />
    else content = <TypePanel flow={flow} index={index} />
    const typing = tabs && s.ready && !s.result && s.mode === 'type' && flow.view === 'keys'
    // Demo mode: no Quit (⌃⌥⌘Q still quits); Settings stays faint until looked at (CSS).
    corners = { hide: s.ready && screen === 'dock', settings: !busy && s.ready && screen === 'dock', quit: !busy && !gaze.demoMode }
    body = (
      <>
        <div className={`bottom${typing ? ' is-typing' : ''}`}>
          <div className="above-dock">
            <StatusLine status={status} />
            {gaze.clickMode && <span className="mode-chip">{gaze.demoMode ? 'Click mode' : 'Click mode · ⌃⌥⌘D'}</span>}
            {typing && <ComposerField composer={flow.composer} index={index} />}
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
    <div className={`overlay density-${s.settings?.density ?? 'large'}${gaze.headPointer || gaze.source === 'head' ? ' head-pointer' : ''}${gaze.demoMode ? ' demo' : ''}`}>
      {body}
      {/* Quit alone top-left; Hide, Settings, Back in a compact column top-right, where a control that
          expands pushes the ones below it down (styles/glass.css). No Back during calibration. */}
      <div className="corner-stack is-left">
        {corners.quit && <QuitCorner />}
      </div>
      <div className="corner-stack">
        {corners.hide && hideToggle}
        {corners.settings && <SettingsCorner onSelect={() => setScreen('settings')} />}
        {/* While anything is running or asking (confirm included), Back/STOP is always there. */}
        {(busy || (!calibrating && screen !== 'recenter')) && <StopTarget onIdle={backToDock} />}
      </div>
      <GazeDot />
    </div>
  )
}
