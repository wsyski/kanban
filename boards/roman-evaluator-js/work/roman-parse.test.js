import { describe, expect, it } from '@jest/globals';
import { parseRoman } from './roman-parse.js';

describe('parseRoman', () => {
  it('converts XIV to 14 (covers SC1)', () => {
    expect(parseRoman('XIV')).toBe(14);
  });

  it('converts MMMCMXCIX to 3999 (covers SC1)', () => {
    expect(parseRoman('MMMCMXCIX')).toBe(3999);
  });

  it('rejects IIII (covers SC1)', () => {
    expect(() => parseRoman('IIII')).toThrow();
  });

  it('rejects VX (covers SC1)', () => {
    expect(() => parseRoman('VX')).toThrow();
  });

  it('rejects IXX (covers SC1)', () => {
    expect(() => parseRoman('IXX')).toThrow();
  });

  it('rejects empty input (covers SC1)', () => {
    expect(() => parseRoman('')).toThrow();
  });

  it('rejects a character outside MDCLXVI (covers SC1)', () => {
    expect(() => parseRoman('A')).toThrow();
  });

  it('rejects MMMM, above the 3999 upper bound (Review Focus 1)', () => {
    expect(() => parseRoman('MMMM')).toThrow();
  });

  it('accepts lowercase xiv as 14 (Review Focus 2)', () => {
    expect(parseRoman('xiv')).toBe(14);
  });

  it('rejects whitespace-only input as empty (Review Focus 3)', () => {
    expect(() => parseRoman('   ')).toThrow();
  });

  it('throws an error with a non-empty message for every rejection (Review Focus 4)', () => {
    for (const bad of ['IIII', 'VX', 'IXX', '', '   ', 'A', 'MMMM']) {
      let message = null;
      try {
        parseRoman(bad);
      } catch (err) {
        message = err.message;
      }
      expect(message).toBeTruthy();
    }
  });

  it('handles each subtractive pair (Review Focus 5)', () => {
    expect(parseRoman('IV')).toBe(4);
    expect(parseRoman('IX')).toBe(9);
    expect(parseRoman('XL')).toBe(40);
    expect(parseRoman('XC')).toBe(90);
    expect(parseRoman('CD')).toBe(400);
    expect(parseRoman('CM')).toBe(900);
  });
});
