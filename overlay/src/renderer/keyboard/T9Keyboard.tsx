// T9 gaze keyboard (spec §6.3): prediction bar, 3×3 letter keys and a control column.
import type { JSX, ReactNode } from 'react'
import { DwellTarget } from '../platform'
import { ArrowRightIcon, DeleteIcon, KeyboardIcon, SparkleIcon, SpaceIcon } from '../dock/icons'
import { LETTER_KEYS } from './t9index'
import type { Phrase, Predictor } from './predict'
import {
  PUNCTUATION, backspace, isEmpty, pickWord, pressGroup, setPage, space, typeChar, type Composer
} from './composer'

const SLOTS = 5

function Key(props: { id: string; className?: string; disabled?: boolean; onSelect: () => void; children: ReactNode }): JSX.Element {
  return (
    <DwellTarget id={props.id} variant="key" disabled={props.disabled} onSelect={props.onSelect}
      className={['target', 'key', props.className].filter(Boolean).join(' ')}>
      {props.children}
    </DwellTarget>
  )
}

export interface T9KeyboardProps {
  composer: Composer
  index: Predictor
  onChange: (next: Composer) => void
  onDone: () => void
  /** A suggested command: complete ones go straight to the plans, others fill the text. */
  onPhrase: (phrase: Phrase) => void
}

/** A whole suggested command, two slots wide. The part already chosen is dimmed. */
function PhraseKey({ phrase, chosen, onSelect }: { phrase: Phrase; chosen: number; onSelect: () => void }): JSX.Element {
  const done = phrase.words.slice(0, chosen).join(' ')
  const rest = phrase.words.slice(chosen).join(' ')
  return (
    <Key id={`phrase-${phrase.text}`} className={`prediction phrase${phrase.complete ? ' is-complete' : ''}`} onSelect={onSelect}>
      <span className="phrase-icon">{phrase.complete ? <ArrowRightIcon /> : <SparkleIcon />}</span>
      <span className="phrase-text">{done && <span className="phrase-done">{done} </span>}<span className="phrase-rest">{rest}</span></span>
      <span className="key-sub">{phrase.complete ? 'Do this' : 'Then add a message'}</span>
    </Key>
  )
}

/** The typed text, shown above the dock. The unfinished word shows its top prediction, underlined. */
export function ComposerField({ composer: c, index }: { composer: Composer; index: Predictor }): JSX.Element {
  const pending = c.groups.length ? index.top(c) ?? '·'.repeat(c.groups.length) : c.literal
  return (
    <div className="kbd-field" aria-live="polite">
      {isEmpty(c)
        ? <span className="kbd-placeholder">Look at a letter key to start typing</span>
        : <span className="kbd-text">
          {c.words.join(' ')}{c.words.length && pending ? ' ' : ''}
          {pending && <span className="kbd-pending">{pending}</span>}
        </span>}
    </div>
  )
}

export function T9Keyboard({ composer: c, index, onChange, onDone, onPhrase }: T9KeyboardProps): JSX.Element {
  const { phrases, words: predictions } = index.predict(c, SLOTS)
  const top = index.top(c)
  const wordSlots = SLOTS - 2 * phrases.length

  const slots: ReactNode[] = c.page === 'symbols'
    ? ['0', ...PUNCTUATION].map(ch => (
      <Key key={ch} id={`key-sym-${ch}`} className="prediction symbol" onSelect={() => onChange(typeChar(c, ch))}>
        <span className="key-label">{ch}</span>
      </Key>))
    : [...phrases.map(p => <PhraseKey key={p.text} phrase={p} chosen={c.words.length} onSelect={() => onPhrase(p)} />),
      ...Array.from({ length: wordSlots }, (_, i) => {
      const word = predictions[i]
      return word
        ? <Key key={`${i}-${word}`} id={`pred-${i}-${word}`} className="prediction" onSelect={() => onChange(pickWord(c, word))}>
          <span className="key-word">{word}</span>
        </Key>
        : <div key={`empty-${i}`} className="prediction-empty" aria-hidden="true" />
    })]

  const letterKeys = c.page === 'symbols'
    ? ['1', '2', '3', '4', '5', '6', '7', '8', '9'].map(d => (
      <Key key={d} id={`key-sym-${d}`} onSelect={() => onChange(typeChar(c, d))}><span className="key-label">{d}</span></Key>))
    : [
      ...LETTER_KEYS.map(({ group }) => (
        <Key key={group} id={`key-${group}`} onSelect={() => onChange(pressGroup(c, group))}>
          <span className="key-label">{group}</span>
        </Key>)),
      <Key key="space" id="key-space" className="key-space" onSelect={() => onChange(space(c, top))}>
        <SpaceIcon /><span className="key-sub">Space</span>
      </Key>
    ]

  return (
    <div className="kbd">
      <div className="kbd-predictions">{slots}</div>
      <div className="kbd-grid">
        <div className="kbd-letters">{letterKeys}</div>
        <div className="kbd-controls">
          <Key id="key-delete" className="key-control" disabled={isEmpty(c)} onSelect={() => onChange(backspace(c))}>
            <DeleteIcon /><span className="key-sub">Delete</span>
          </Key>
          <Key id="key-done" className="key-control key-done" disabled={isEmpty(c)} onSelect={onDone}>
            <span className="key-label">DONE</span>
          </Key>
          <Key id="key-page" className="key-control"
            onSelect={() => onChange(setPage(c, c.page === 'letters' ? 'symbols' : 'letters'))}>
            {c.page === 'letters'
              ? <><span className="key-label">123?</span><span className="key-sub">Numbers</span></>
              : <><KeyboardIcon /><span className="key-sub">Letters</span></>}
          </Key>
        </div>
      </div>
    </div>
  )
}
