// Auto | Type tabs on the dock's left edge (spec §6.2).
import type { JSX } from 'react'
import { DwellTarget, agent } from '../platform'
import { KeyboardIcon, SparkleIcon } from './icons'

export type Mode = 'auto' | 'type'

/**
 * Switching *to* Auto asks for suggestions once (spec §7, tasks A1); launching in Auto does not,
 * because nothing calls this at launch. Choosing the tab that is already active does nothing.
 */
export function switchMode(current: Mode, next: Mode): void {
  if (next === current) return
  agent.setMode(next)
  if (next === 'auto') agent.suggestNow()
}

export function ModeTabs({ mode, disabled }: { mode: Mode; disabled?: boolean }): JSX.Element {
  const tab = (value: Mode, label: string, hint: string, icon: JSX.Element) => (
    <DwellTarget id={`tab-${value}`} variant="card" disabled={disabled || mode === value}
      onSelect={() => switchMode(mode, value)}
      className={`target tab${mode === value ? ' is-active' : ''}`}>
      <span className="tab-icon">{icon}</span>
      <span className="tab-label">{label}</span>
      <span className="tab-hint">{hint}</span>
    </DwellTarget>
  )
  return (
    <div className="tabs">
      {tab('auto', 'Auto', 'Ideas', <SparkleIcon />)}
      {tab('type', 'Type', 'Ask', <KeyboardIcon />)}
    </div>
  )
}
