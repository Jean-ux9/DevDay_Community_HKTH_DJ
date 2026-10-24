// What the user has typed on the T9 keyboard, as a pure value (spec §6.3). The keyboard component
// only renders this and applies the functions below, so every editing rule is unit-testable.

export type KeyPage = 'letters' | 'symbols'

export interface Composer {
  /** Committed words (from the prediction bar, ␣, or the symbols page). */
  words: string[]
  /** Key groups of the unfinished word, e.g. ['GHI', 'ABC']: `decode_request.raw_keys`. */
  groups: string[]
  /** Digits typed on the symbols page that are not committed yet. */
  literal: string
  page: KeyPage
}

export const emptyComposer = (): Composer => ({ words: [], groups: [], literal: '', page: 'letters' })

/** Digits go into the literal buffer; these attach to the previous word instead. */
export const PUNCTUATION = ['?', '.', ',', '!'] as const

const commitLiteral = (c: Composer): Composer =>
  c.literal ? { ...c, words: [...c.words, c.literal], literal: '' } : c

export function pressGroup(c: Composer, group: string): Composer {
  const base = commitLiteral(c)
  return { ...base, groups: [...base.groups, group] }
}

/** A prediction-bar word replaces the unfinished word. */
export function pickWord(c: Composer, word: string): Composer {
  const base = commitLiteral(c)
  return { ...base, words: [...base.words, word], groups: [] }
}

/** ␣ commits the top prediction; with no prediction the raw keys stay for the decoder. */
export function space(c: Composer, topPrediction: string | undefined): Composer {
  if (c.groups.length && topPrediction) return pickWord(c, topPrediction)
  return commitLiteral(c)
}

/** ⌫ deletes one key group, then one digit, then one whole word. */
export function backspace(c: Composer): Composer {
  if (c.groups.length) return { ...c, groups: c.groups.slice(0, -1) }
  if (c.literal) return { ...c, literal: c.literal.slice(0, -1) }
  return { ...c, words: c.words.slice(0, -1) }
}

export function typeChar(c: Composer, ch: string): Composer {
  if (/^\d$/.test(ch)) return { ...c, literal: c.literal + ch }
  const base = commitLiteral(c)
  const last = base.words.at(-1)
  if (last === undefined) return { ...base, words: [ch] }
  return { ...base, words: [...base.words.slice(0, -1), last + ch] }
}

export function setPage(c: Composer, page: KeyPage): Composer {
  return { ...commitLiteral(c), page }
}

export const isEmpty = (c: Composer): boolean => !c.words.length && !c.groups.length && !c.literal

/** Arguments for `agent.decode(words, rawKeys)` on DONE. */
export function decodeArgs(c: Composer): { words: string[]; rawKeys: string[] } {
  return { words: commitLiteral(c).words, rawKeys: c.groups }
}

/** The typed sentence when nothing is left undecoded (spec §6.3: "show the sentence as-is"). */
export function asIsSentence(c: Composer): string | null {
  if (c.groups.length) return null
  const text = commitLiteral(c).words.join(' ').trim()
  return text || null
}

/** Sentence cards: the as-is sentence first, then the decoder's variants, without repeats. */
export function sentenceOptions(asIs: string | null, decoded: readonly string[] | null, max = 4): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const s of [asIs, ...(decoded ?? [])]) {
    const text = s?.trim()
    if (!text) continue
    const key = text.toLowerCase().replace(/[.!?,]+$/, '')
    if (seen.has(key)) continue
    seen.add(key)
    out.push(text)
  }
  return out.slice(0, max)
}
