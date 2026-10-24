// Type mode as a small state machine: keys → (DONE) sentences → (pick) plans → task (spec §6.3, §8.5).
// The session carries the agent's answers; this hook remembers which answer we are waiting for.
import { useEffect, useRef, useState } from 'react'
import { agent, type SessionState } from '../platform'
import { isQuietError } from '../dock/status'
import { asIsSentence, decodeArgs, emptyComposer, isEmpty, sentenceOptions, type Composer } from './composer'

export type TypeView = 'keys' | 'sentences' | 'plans'

interface Baseline {
  sentences: SessionState['sentences']
  error: SessionState['lastError']
}

export interface TypeFlow {
  composer: Composer
  setComposer: (next: Composer) => void
  view: TypeView
  /** The text sent with intent_submit, shown above the plan cards. */
  intent: string | null
  /** Sentence cards: the typed sentence as-is first, then the decoder's variants. */
  sentences: string[]
  plans: SessionState['list']
  awaiting: 'decode' | 'plans' | null
  failure: string | null
  done: () => void
  chooseSentence: (text: string) => void
  /** "Something else" on a plan list: back to the keyboard with the text kept (§4.2). */
  backToKeys: () => void
}

export function useTypeFlow(s: SessionState): TypeFlow {
  const [composer, setComposer] = useState<Composer>(emptyComposer)
  const [view, setView] = useState<TypeView>('keys')
  const [asIs, setAsIs] = useState<string | null>(null)
  const [intent, setIntent] = useState<string | null>(null)
  const baseline = useRef<Baseline>({ sentences: null, error: null })

  // A started task consumes the request; a mode switch abandons the half-finished view.
  const taskId = s.task?.taskId ?? null
  useEffect(() => {
    if (taskId) { setComposer(emptyComposer()); setView('keys'); setIntent(null) }
  }, [taskId])
  useEffect(() => { setView('keys') }, [s.mode])

  const fresh = s.sentences !== baseline.current.sentences ? s.sentences : null
  const plans = view === 'plans' && s.list?.source === 'plans' ? s.list : null
  const error = view !== 'keys' && s.lastError && s.lastError !== baseline.current.error && !isQuietError(s.lastError.code)
    ? s.lastError.message : null
  const awaiting = error ? null
    : view === 'sentences' && !fresh ? 'decode'
    : view === 'plans' && !plans ? 'plans' : null

  const mark = () => { baseline.current = { sentences: s.sentences, error: s.lastError } }

  return {
    composer, setComposer, view, intent, plans, awaiting, failure: error,
    sentences: view === 'sentences' ? sentenceOptions(asIs, fresh) : [],
    done: () => {
      if (isEmpty(composer)) return
      const { words, rawKeys } = decodeArgs(composer)
      mark()
      setAsIs(asIsSentence(composer))
      setView('sentences')
      agent.decode(words, rawKeys)
    },
    chooseSentence: (text: string) => {
      mark()
      setIntent(text)
      setView('plans')
      agent.submitIntent(text)
    },
    backToKeys: () => setView('keys')
  }
}
