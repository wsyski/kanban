const CANONICAL = /^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$/;

const SIMPLE = { I: 1, V: 5, X: 10, L: 50, C: 100, D: 500, M: 1000 };
const SUBTRACTIVE = { IV: 4, IX: 9, XL: 40, XC: 90, CD: 400, CM: 900 };

export function parseRoman(text) {
  const trimmed = String(text).trim();
  if (trimmed === '') {
    throw new Error('Enter a roman numeral.');
  }
  const roman = trimmed.toUpperCase();
  if (!CANONICAL.test(roman)) {
    throw new Error(`Not a valid roman numeral: ${trimmed}`);
  }
  let value = 0;
  for (let index = 0; index < roman.length; index += 1) {
    const pair = roman.slice(index, index + 2);
    if (SUBTRACTIVE[pair] !== undefined) {
      value += SUBTRACTIVE[pair];
      index += 1;
    } else {
      value += SIMPLE[roman[index]];
    }
  }
  return value;
}
