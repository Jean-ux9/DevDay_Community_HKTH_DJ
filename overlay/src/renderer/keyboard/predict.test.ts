// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { agent, dwell, resetPlatform, setSession, targetIds } from '../dock/test-platform'
import { emptyComposer, type Composer } from './composer'
import { Predictor, STARTERS, buildPhrases } from './predict'
import { T9Index } from './t9index'

vi.mock('../platform', async () => (await import('../dock/test-platform')).platformMock)

const PROFILE = {
  contacts: { Mom: ['+1 555 0100'], TeamMail: ['team@example.invalid'] },
  style: { phrases: ['sounds good'] },
  favorites: { playlist: 'Deep Focus', artist: 'Taylor Swift', sites: ['https://www.ticketmaster.com/'] }
} as never
const BASE = [{ word: 'tell', weight: 900 }, { word: 'open', weight: 800 }, { word: 'me', weight: 700 },
  { word: 'of', weight: 950 }, { word: 'need', weight: 400 }, { word: 'email', weight: 100 }]
const predictor = () => new Predictor(new T9Index(BASE, ['Mom', 'TeamMail']), buildPhrases(PROFILE))
const at = (patch: Partial<Composer>): Composer => ({ ...emptyComposer(), ...patch })
const texts = (c: Composer) => predictor().predict(c).phrases.map(p => p.text)

describe('intent predictions: fewer selections per request', () => {
  it('offers starter verbs on an empty keyboard, and no phrases yet', () => {
    expect(predictor().predict(emptyComposer())).toEqual({ phrases: [], words: [...STARTERS] })
  })

  it('one key is enough to offer whole commands', () => {
    // MNO → "open …" commands; the word slots still list ordinary words for that key.
    expect(texts(at({ groups: ['MNO'] }))).toEqual(['open Safari', 'open Mail'])
    // DEF → "email <alias>": incomplete, it needs a message.
    const email = predictor().predict(at({ groups: ['DEF'] })).phrases
    expect(email.map(p => [p.text, p.complete])).toEqual([['email Mom', false], ['email TeamMail', false]])
  })

  it('ranks the word the chosen words lead to above more frequent words', () => {
    // "of" (950) shares keys 6-3 with "me" (700) and "of" is more common, but after "tell" the
    // contact alias wins: TUV-DEF-JKL-JKL then MNO → Mom first.
    expect(predictor().predict(at({ words: ['tell'], groups: ['MNO'] })).words[0]).toBe('Mom')
    expect(predictor().top(at({ groups: ['MNO', 'DEF'] }))).toBe('of')
  })

  it('after a contact, one key offers a complete message', () => {
    const { phrases } = predictor().predict(at({ words: ['tell', 'Mom'], groups: ['PQRS'] }))
    expect(phrases[0]).toMatchObject({ text: 'tell Mom sounds good', complete: true })
    expect(texts(at({ words: ['tell', 'Mom'], groups: ['GHI'] }))).toEqual(["tell Mom I'll be late"])
  })

  it('suggests the next word with no key pressed', () => {
    const { phrases, words } = predictor().predict(at({ words: ['play'] }))
    expect(phrases.map(p => p.text)).toEqual(['play Deep Focus', 'play Taylor Swift'])
    expect(words).toEqual(['Deep'])
  })

  it('builds sites, apps and favourites into commands without duplicates', () => {
    const all = buildPhrases(PROFILE).map(p => p.text)
    expect(all).toContain('open ticketmaster.com')
    expect(all).toContain('search Taylor Swift')
    expect(new Set(all).size).toBe(all.length)
    expect(buildPhrases(null).map(p => p.text)).toEqual(
      ['open Safari', 'open Mail', 'open Messages', 'open TextEdit', 'open Notes', 'open Calendar'])
  })
})

describe('Type mode: a complete command skips the decoder', () => {
  beforeEach(() => resetPlatform({ mode: 'type' }))
  afterEach(cleanup)

  it('MNO then "open Safari" submits the intent in two selections', () => {
    render(createElement(App))
    act(() => { dwell('key-MNO') })
    act(() => { dwell('phrase-open Safari') })
    expect(agent.submitIntent).toHaveBeenCalledWith('open Safari')
    expect(agent.decode).not.toHaveBeenCalled()
    expect(document.querySelector('.dock-quote')?.textContent).toContain('open Safari')
  })

  it('an incomplete command fills the text and keeps the keyboard', () => {
    resetPlatform({ mode: 'type', profile: PROFILE })
    render(createElement(App))
    act(() => { dwell('key-DEF') })
    act(() => { dwell('phrase-email Mom') })
    expect(agent.submitIntent).not.toHaveBeenCalled()
    expect(document.querySelector('.kbd-field')!.textContent).toContain('email Mom')
    expect(targetIds()).toContain('phrase-email Mom sounds good')
    act(() => setSession({}))
  })
})
