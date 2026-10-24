// The agent is unsure and asks (spec §8.3): one card per option, plus Cancel.
import type { JSX } from 'react'
import { agent, type SessionState } from '../platform'
import { Card } from './Card'
import { CloseIcon } from './icons'

export function ChoiceCards({ choice }: { choice: NonNullable<SessionState['choice']> }): JSX.Element {
  return (
    <div className="dock-section">
      <h2 className="dock-question">{choice.question}</h2>
      <div className="card-row">
        {choice.options.map(option => (
          <Card key={option.id} id={`choice-${choice.requestId}-${option.id}`} label={option.label}
            detail={option.detail} onSelect={() => agent.respondChoice(option.id)} />
        ))}
        <Card id={`choice-${choice.requestId}-cancel`} label="Cancel" detail="Stop this task"
          icon={<CloseIcon />} className="cancel-card" onSelect={() => agent.respondChoice(null)} />
      </div>
    </div>
  )
}
