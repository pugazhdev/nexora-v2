import { describe, expect, it } from 'vitest'
import { formatInr, parseIndianNumber } from './format'

describe('formatInr', () => {
  it('uses Indian grouping', () => {
    expect(formatInr(100000, 0)).toBe('₹1,00,000')
    expect(formatInr(1234567.5)).toBe('₹12,34,567.50')
    expect(formatInr(1.85)).toBe('₹1.85')
  })
})

describe('parseIndianNumber', () => {
  it('parses grouped and plain numbers', () => {
    expect(parseIndianNumber('1,00,000')).toBe(100000)
    expect(parseIndianNumber('100000')).toBe(100000)
    expect(parseIndianNumber('1.5')).toBe(1.5)
    expect(parseIndianNumber(' 2,500 ')).toBe(2500)
  })
  it('returns null for empty or non-numeric', () => {
    expect(parseIndianNumber('')).toBeNull()
    expect(parseIndianNumber('   ')).toBeNull()
    expect(parseIndianNumber('abc')).toBeNull()
    expect(parseIndianNumber('1.2.3')).toBeNull()
  })
})
