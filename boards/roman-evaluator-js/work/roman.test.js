import { parseRoman } from './roman.js';

describe('parseRoman', () => {
  test('XIV is 14', () => {
    expect(parseRoman('XIV')).toBe(14);
  });

  test('MMMCMXCIX is 3999, the valid upper bound', () => {
    expect(parseRoman('MMMCMXCIX')).toBe(3999);
  });

  test('xiv is 14, input is case-insensitive', () => {
    expect(parseRoman('xiv')).toBe(14);
  });

  test('IIII is rejected', () => {
    expect(() => parseRoman('IIII')).toThrow();
  });

  test('VX is rejected', () => {
    expect(() => parseRoman('VX')).toThrow();
  });

  test('IXX is rejected', () => {
    expect(() => parseRoman('IXX')).toThrow();
  });

  test('empty input is rejected', () => {
    expect(() => parseRoman("")).toThrow('Enter a roman numeral.');
  });

  test('a character outside MDCLXVI is rejected', () => {
    expect(() => parseRoman('A')).toThrow();
  });
});
