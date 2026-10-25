/// <reference types="vite/client" />
// The local T9 index: the shipped word list plus the user's profile words (spec §6.3), wrapped in
// the intent-aware predictor (whole commands, next words).
import { useMemo } from 'react'
import type { Profile } from '../platform'
import wordlistText from '../../../../data/wordlist_en.txt?raw'
import { T9Index, parseWordlist, profileEntries } from './t9index'
import { Predictor, buildPhrases } from './predict'

const BASE_WORDS = parseWordlist(wordlistText)

export function useT9Index(profile: Profile | null): Predictor {
  const entries = profileEntries(profile)
  const phrases = buildPhrases(profile)
  const key = entries.join('\n') + '\n\n' + phrases.map(p => p.text).join('\n')
  // Rebuild only when the profile words change, not on every new profile object.
  return useMemo(() => new Predictor(new T9Index(BASE_WORDS, entries), phrases), [key])
}
