import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { PROFILE_BOOST, T9Index, keySequence, parseWordlist, profileEntries, sequenceFromGroups } from './t9index'

const wordlist = parseWordlist(
  readFileSync(new URL('../../../../data/wordlist_en.txt', import.meta.url), 'utf8')
)

describe('keySequence', () => {
  it('maps letters to T9 digits, ignoring case and non-letters', () => {
    expect(keySequence('tell')).toBe('8355')
    expect(keySequence('Mom')).toBe('666')
    expect(keySequence("I'll")).toBe('455')
    expect(keySequence('on my way')).toBe('6669929')
  })

  it('maps key groups from the keyboard / decode_request.raw_keys', () => {
    expect(sequenceFromGroups(['GHI', 'ABC'])).toBe('42')
    expect(sequenceFromGroups(['JKL', 'ABC', 'TUV', 'DEF'])).toBe('5283')
  })
})

describe('parseWordlist', () => {
  it('parses "word freq" lines and skips junk', () => {
    expect(parseWordlist('the 100\n\nbad\nx notanumber\nof 50\n')).toEqual([
      { word: 'the', weight: 100 },
      { word: 'of', weight: 50 }
    ])
  })

  it('the shipped list has ~20k words', () => {
    expect(wordlist.length).toBeGreaterThanOrEqual(19_000)
  })
})

describe('T9Index with the shipped word list', () => {
  const index = new T9Index(wordlist)

  it('"8355" includes "tell"', () => {
    expect(index.lookup('8355', 5)).toContain('tell')
  })

  it('"666" offers "mom"', () => {
    expect(index.lookup('666')).toContain('mom')
  })

  it('returns at most `limit` words, ranked by frequency', () => {
    const top = index.lookup('843', 5) // the, tie, ...
    expect(top.length).toBeLessThanOrEqual(5)
    expect(top[0]).toBe('the')
  })

  it('exact matches come before longer completions', () => {
    const top = index.lookup('8355', 5)
    const exact = top.filter((w) => keySequence(w) === '8355')
    expect(top.slice(0, exact.length)).toEqual(exact)
  })

  it('completes a prefix when there are few exact matches', () => {
    const top = index.lookup('835', 5)
    expect(top.some((w) => keySequence(w).length > 3)).toBe(true)
  })

  it('returns nothing for an empty or impossible sequence', () => {
    expect(index.lookup('')).toEqual([])
    expect(index.lookup('00000')).toEqual([])
  })
})

describe('profile boost', () => {
  const base = [
    { word: 'good', weight: 1000 },
    { word: 'home', weight: 900 },
    { word: 'gone', weight: 800 },
    { word: 'hood', weight: 100 }
  ]

  it('a profile word outranks a much more common word with the same keys', () => {
    const plain = new T9Index(base)
    expect(plain.lookup('4663')[0]).toBe('good')
    const boosted = new T9Index(base, ['hood'])
    expect(boosted.lookup('4663')[0]).toBe('hood')
  })

  it('a profile phrase outranks a common word with the same keys', () => {
    // "on my way" → 6669929; a common word colliding with it:
    const index = new T9Index([...base, { word: 'onnxwcy', weight: 1_000_000 }], ['on my way'])
    expect(keySequence('onnxwcy')).toBe(keySequence('on my way'))
    expect(new T9Index([{ word: 'onnxwcy', weight: 1_000_000 }]).lookup('6669929')[0]).toBe('onnxwcy')
    expect(index.lookup('6669929')[0]).toBe('on my way')
  })

  it('profile phrases are also indexed word by word', () => {
    const index = new T9Index(base, ['sounds good'])
    expect(index.lookup('768637')).toContain('sounds')
  })

  it('boosts by ×50 from the base frequency', () => {
    const index = new T9Index([{ word: 'good', weight: 1000 }, { word: 'gone', weight: 40_000 }], ['good'])
    // 1000 × 50 = 50 000 > 40 000
    expect(index.lookup('4663')[0]).toBe('good')
    expect(PROFILE_BOOST).toBe(50)
  })

  it('a profile word unknown to the list is still offered, with the profile spelling', () => {
    const index = new T9Index(base, ['Zendaya'])
    expect(index.lookup(keySequence('zendaya'))).toEqual(['Zendaya'])
  })

  it('works against the shipped list: "Mom" as an alias beats words sharing 666', () => {
    const index = new T9Index(wordlist, ['Mom'])
    expect(index.lookup('666')[0]).toBe('Mom')
  })
})

describe('profileEntries', () => {
  it('collects favourites, contact aliases and phrases', () => {
    const texts = profileEntries({
      name: 'Alex',
      favorites: { artist: 'Taylor Swift', playlist: 'Deep Focus', sites: ['https://www.ticketmaster.com/x'] },
      contacts: { Mom: ['+15550100'] },
      style: { tone: 'casual', signature: '', phrases: ['on my way', ''] }
    })
    expect(texts).toEqual(['Alex', 'Taylor Swift', 'Deep Focus', 'ticketmaster', 'Mom', 'on my way'])
  })

  it('copes with a missing profile', () => {
    expect(profileEntries(null)).toEqual([])
    expect(profileEntries({})).toEqual([])
  })
})
