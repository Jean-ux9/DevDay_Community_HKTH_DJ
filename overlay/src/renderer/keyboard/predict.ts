// Intent-aware prediction on top of the T9 index: whole commands from a key or two, next-word
// suggestions with no key pressed, and word ranking that follows the words already chosen.
// Local and synchronous: still zero tokens per keystroke (spec §6.3).
import type { Profile } from '../ws/protocol.gen'
import { keySequence, sequenceFromGroups, type T9Index } from './t9index'
import type { Composer } from './composer'

/** Apps the launcher can open (agent/gaze_agent/tools/launch.py APP_BUNDLES). */
export const APPS = ['Safari', 'Mail', 'Messages', 'TextEdit', 'Notes', 'Calendar'] as const
/** First words offered on an empty keyboard. */
export const STARTERS = ['open', 'email', 'text', 'find', 'play'] as const
/** Short messages offered after "tell Mom", "email Alex", ... Profile style phrases come first. */
export const MESSAGES = ["I'll be late", 'on my way', 'sounds good', 'running late', 'see you soon', 'call me when you can'] as const
const MESSAGE_VERBS = ['tell', 'email', 'text'] as const
/** Popular artists for ticket searches and music, after the profile's favourite. */
export const ARTISTS = ['Billie Eilish', 'Coldplay', 'Beyoncé', 'Ed Sheeran', 'Olivia Rodrigo', 'Bad Bunny',
  'The Weeknd', 'Dua Lipa', 'Drake', 'Harry Styles'] as const
/** Whole commands need this many keys on the first word, so a request is typed, not guessed. */
export const FIRST_WORD_KEYS = 3

export interface Phrase {
  text: string
  words: string[]
  /** A complete request: picking it submits the intent. Otherwise it fills the text to continue. */
  complete: boolean
}

const words = (text: string) => text.split(/\s+/).filter(Boolean)
const phrase = (text: string, complete: boolean): Phrase => ({ text, words: words(text), complete })
const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase()

/** Commands built from the supported actions and the profile, most useful first. */
export function buildPhrases(profile: Partial<Profile> | null | undefined): Phrase[] {
  const out: Phrase[] = []
  const aliases = Object.keys(profile?.contacts ?? {})
  const messages = [...(profile?.style?.phrases ?? []), ...MESSAGES]
  for (const verb of MESSAGE_VERBS) {
    for (const alias of aliases) {
      out.push(phrase(`${verb} ${alias}`, false))
      for (const m of messages) out.push(phrase(`${verb} ${alias} ${m}`, true))
    }
  }
  for (const app of APPS) out.push(phrase(`open ${app}`, true))
  for (const site of profile?.favorites?.sites ?? []) {
    const host = site.replace(/^[a-z]+:\/\//i, '').split('/')[0]?.replace(/^www\./i, '')
    if (host) out.push(phrase(`open ${host}`, true))
  }
  const fav = profile?.favorites
  if (fav?.playlist) out.push(phrase(`play ${fav.playlist}`, true))
  for (const artist of [fav?.artist, ...ARTISTS].filter((a): a is string => !!a)) {
    out.push(phrase(`find ${artist} tickets`, true), phrase(`play ${artist}`, true), phrase(`search ${artist}`, true))
  }
  const seen = new Set<string>()
  return out.filter(p => !seen.has(p.text.toLowerCase()) && seen.add(p.text.toLowerCase()))
}

export interface Prediction {
  phrases: Phrase[]
  words: string[]
}

export class Predictor {
  constructor(readonly index: T9Index, readonly phraseList: readonly Phrase[]) {}

  /** Phrases that continue the chosen words and whose next word fits the pending keys. */
  private continuing(c: Composer): Phrase[] {
    const n = c.words.length
    const seq = sequenceFromGroups(c.groups)
    return this.phraseList.filter(p => p.words.length > n
      && c.words.every((w, i) => same(w, p.words[i]!))
      && (!seq || keySequence(p.words[n]!).startsWith(seq)))
      // Shortest first (stable), so one key offers different contacts before their messages.
      .sort((a, b) => a.words.length - b.words.length)
  }

  predict(c: Composer, wordSlots = 5, phraseSlots = 2): Prediction {
    if (c.page !== 'letters' || c.literal) return { phrases: [], words: [] }
    const next = this.continuing(c)
    const n = c.words.length
    // Whole commands only after real typing: a few keys of the first word, or a key of a later one.
    const typed = n === 0 ? c.groups.length >= FIRST_WORD_KEYS : c.groups.length >= 1
    const phrases = typed ? next.slice(0, phraseSlots) : []
    const limit = Math.max(0, wordSlots - 2 * phrases.length)
    const followers = next.map(p => p.words[n]!)
    let candidates: string[]
    if (c.groups.length) candidates = [...followers, ...this.index.lookup(sequenceFromGroups(c.groups), limit + 10)]
    else if (n) candidates = followers
    else candidates = [...STARTERS]
    const seen = new Set<string>()
    const out = candidates.filter(w => !seen.has(w.toLowerCase()) && seen.add(w.toLowerCase()))
    return { phrases, words: out.slice(0, limit) }
  }

  /** The word the pending keys most likely spell, for the text field and ␣. */
  top(c: Composer): string | undefined {
    return c.groups.length ? this.predict(c, 1, 0).words[0] : undefined
  }
}
