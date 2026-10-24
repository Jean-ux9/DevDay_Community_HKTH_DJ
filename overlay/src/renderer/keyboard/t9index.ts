// Local T9 decoding: key sequence → ranked words, zero tokens per keystroke (spec §6.3).
import type { Profile } from '../ws/protocol.gen'

/** The letter keys, in keyboard order. The digit is the classic T9 digit for the key. */
export const LETTER_KEYS = [
  { group: 'ABC', digit: '2' },
  { group: 'DEF', digit: '3' },
  { group: 'GHI', digit: '4' },
  { group: 'JKL', digit: '5' },
  { group: 'MNO', digit: '6' },
  { group: 'PQRS', digit: '7' },
  { group: 'TUV', digit: '8' },
  { group: 'WXYZ', digit: '9' }
] as const

/** Profile phrases, aliases and favourites outrank common words with the same keys (spec §6.3). */
export const PROFILE_BOOST = 50

const DIGIT_BY_LETTER: Record<string, string> = {}
const DIGIT_BY_GROUP: Record<string, string> = {}
for (const { group, digit } of LETTER_KEYS) {
  DIGIT_BY_GROUP[group] = digit
  for (const ch of group) DIGIT_BY_LETTER[ch.toLowerCase()] = digit
}

/** Digits for the letters of `text`; apostrophes, spaces and other characters are skipped. */
export function keySequence(text: string): string {
  let seq = ''
  for (const ch of text.toLowerCase()) seq += DIGIT_BY_LETTER[ch] ?? ''
  return seq
}

/** Key groups as the keyboard names them (and `decode_request.raw_keys` uses them) → digits. */
export function sequenceFromGroups(groups: readonly string[]): string {
  return groups.map((g) => DIGIT_BY_GROUP[g] ?? '').join('')
}

export interface WeightedWord {
  word: string
  weight: number
}

/** Parses `word frequency` lines (data/wordlist_en.txt). Malformed lines are skipped. */
export function parseWordlist(text: string): WeightedWord[] {
  const out: WeightedWord[] = []
  for (const line of text.split('\n')) {
    const [word, freq] = line.trim().split(/\s+/)
    const weight = Number(freq)
    if (word && Number.isFinite(weight) && weight > 0) out.push({ word, weight })
  }
  return out
}

/** Texts worth boosting from a profile: favourites, contact aliases, style phrases (spec §6.3). */
export function profileEntries(profile: Partial<Profile> | null | undefined): string[] {
  if (!profile) return []
  const texts: string[] = []
  const add = (t: string | undefined) => {
    const trimmed = t?.trim()
    if (trimmed) texts.push(trimmed)
  }
  add(profile.name)
  add(profile.favorites?.artist)
  add(profile.favorites?.playlist)
  for (const site of profile.favorites?.sites ?? []) {
    // "https://www.ticketmaster.com/x" → "ticketmaster"
    const host = site.replace(/^[a-z]+:\/\//i, '').split('/')[0] ?? ''
    add(host.split('.').filter((l) => l.toLowerCase() !== 'www')[0])
  }
  for (const alias of Object.keys(profile.contacts ?? {})) add(alias)
  for (const phrase of profile.style?.phrases ?? []) add(phrase)
  return texts
}

interface Entry {
  text: string
  seq: string
  weight: number
}

const byRank = (a: Entry, b: Entry): number => b.weight - a.weight || (a.text < b.text ? -1 : a.text > b.text ? 1 : 0)

export class T9Index {
  private readonly exact = new Map<string, Entry[]>()
  private readonly seqs: string[]

  /**
   * @param base        common words with frequencies
   * @param profileTexts  words and phrases from the profile; each gets ×PROFILE_BOOST. A phrase is
   *                     offered whole (its key sequence has the spaces dropped) and word by word.
   */
  constructor(base: readonly WeightedWord[], profileTexts: readonly string[] = []) {
    const entries = new Map<string, Entry>() // keyed by lowercase text
    let ceiling = 0
    for (const { word, weight } of base) {
      const key = word.toLowerCase()
      const seq = keySequence(key)
      if (!seq) continue
      ceiling = Math.max(ceiling, weight)
      const prev = entries.get(key)
      if (!prev || weight > prev.weight) entries.set(key, { text: word, seq, weight })
    }
    if (ceiling === 0) ceiling = 1

    const boost = (text: string) => {
      const key = text.toLowerCase()
      const seq = keySequence(key)
      if (!seq) return
      // Known word: ×50 of its own frequency. Unknown word or phrase (no frequency): treat it as the
      // most common word, so it still outranks a common word that shares its key sequence.
      const known = entries.get(key)?.weight
      const weight = known === undefined ? ceiling : known * PROFILE_BOOST
      entries.set(key, { text, seq, weight })
    }
    for (const text of profileTexts) {
      boost(text)
      const words = text.split(/\s+/).filter(Boolean)
      if (words.length > 1) for (const w of words) boost(w)
    }

    for (const e of entries.values()) {
      const list = this.exact.get(e.seq)
      if (list) list.push(e)
      else this.exact.set(e.seq, [e])
    }
    for (const list of this.exact.values()) list.sort(byRank)
    this.seqs = [...this.exact.keys()].sort()
  }

  get size(): number {
    let n = 0
    for (const list of this.exact.values()) n += list.length
    return n
  }

  /**
   * Top `limit` words for a digit sequence: exact matches first, then longer words that start with
   * the sequence (the usual T9 completion), each group ranked by weight.
   */
  lookup(sequence: string, limit = 5): string[] {
    if (!sequence || limit <= 0) return []
    const out = (this.exact.get(sequence) ?? []).slice(0, limit)
    if (out.length >= limit) return out.map((e) => e.text)

    const completions: Entry[] = []
    for (let i = this.lowerBound(sequence); i < this.seqs.length; i++) {
      const seq = this.seqs[i]!
      if (!seq.startsWith(sequence)) break
      if (seq === sequence) continue
      completions.push(...this.exact.get(seq)!)
    }
    completions.sort(byRank)
    return [...out, ...completions.slice(0, limit - out.length)].map((e) => e.text)
  }

  private lowerBound(prefix: string): number {
    let lo = 0
    let hi = this.seqs.length
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (this.seqs[mid]! < prefix) lo = mid + 1
      else hi = mid
    }
    return lo
  }
}
