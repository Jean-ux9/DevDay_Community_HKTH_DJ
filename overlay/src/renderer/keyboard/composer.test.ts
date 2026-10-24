import { describe, expect, it } from 'vitest'
import {
  asIsSentence, backspace, decodeArgs, emptyComposer, isEmpty, pickWord, pressGroup, sentenceOptions, setPage, space,
  typeChar, type Composer
} from './composer'

const press = (c: Composer, ...groups: string[]) => groups.reduce(pressGroup, c)

describe('T9 composer', () => {
  it('collects key groups for the unfinished word and replaces them with a picked word', () => {
    let c = press(emptyComposer(), 'TUV', 'DEF', 'JKL', 'JKL')
    expect(c.groups).toEqual(['TUV', 'DEF', 'JKL', 'JKL'])
    c = pickWord(c, 'tell')
    expect(c).toMatchObject({ words: ['tell'], groups: [] })
  })

  it('␣ commits the top prediction, and keeps raw keys when there is none', () => {
    expect(space(press(emptyComposer(), 'MNO', 'MNO', 'MNO'), 'mom')).toMatchObject({ words: ['mom'], groups: [] })
    expect(space(press(emptyComposer(), 'WXYZ', 'WXYZ'), undefined).groups).toEqual(['WXYZ', 'WXYZ'])
  })

  it('⌫ removes a key group, then a digit, then a whole word', () => {
    let c = press(pickWord(emptyComposer(), 'tell'), 'MNO', 'MNO')
    c = backspace(c)
    expect(c.groups).toEqual(['MNO'])
    c = backspace(backspace(c))
    expect(c.words).toEqual([])
    c = typeChar(emptyComposer(), '4')
    expect(backspace(c).literal).toBe('')
  })

  it('digits build one token; punctuation attaches to the previous word', () => {
    let c = setPage(emptyComposer(), 'symbols')
    c = typeChar(typeChar(c, '2'), '5')
    expect(c.literal).toBe('25')
    c = setPage(c, 'letters')
    expect(c).toMatchObject({ words: ['25'], literal: '', page: 'letters' })
    c = typeChar(pickWord(c, 'tickets'), '?')
    expect(c.words).toEqual(['25', 'tickets?'])
  })

  it('a letter key after digits commits the digits first', () => {
    const c = pressGroup(typeChar(emptyComposer(), '2'), 'TUV')
    expect(c).toMatchObject({ words: ['2'], groups: ['TUV'], literal: '' })
  })

  it('DONE sends the words plus the unfinished word as raw key groups (§4.2)', () => {
    const c = press(pickWord(pickWord(emptyComposer(), 'tell'), 'mom'), 'JKL', 'ABC', 'TUV', 'DEF')
    expect(decodeArgs(c)).toEqual({ words: ['tell', 'mom'], rawKeys: ['JKL', 'ABC', 'TUV', 'DEF'] })
    expect(decodeArgs(typeChar(emptyComposer(), '7'))).toEqual({ words: ['7'], rawKeys: [] })
  })

  it('offers the sentence as-is only when nothing is left undecoded (§6.3)', () => {
    const words = pickWord(pickWord(emptyComposer(), 'sounds'), 'good')
    expect(asIsSentence(words)).toBe('sounds good')
    expect(asIsSentence(pressGroup(words, 'ABC'))).toBeNull()
    expect(asIsSentence(emptyComposer())).toBeNull()
    expect(isEmpty(emptyComposer())).toBe(true)
    expect(isEmpty(pressGroup(emptyComposer(), 'ABC'))).toBe(false)
  })

  it('sentence cards: as-is first, then decoder variants, no repeats, at most 4', () => {
    expect(sentenceOptions('sounds good', ['Sounds good.', 'Sounds good!', 'Sounds good to me.'])).toEqual(
      ['sounds good', 'Sounds good to me.'])
    expect(sentenceOptions(null, ['A', 'B', 'C', 'D', 'E'])).toEqual(['A', 'B', 'C', 'D'])
    expect(sentenceOptions(null, null)).toEqual([])
  })
})
