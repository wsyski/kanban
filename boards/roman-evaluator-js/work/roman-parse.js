const ROMAN_PATTERN = /^M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$/;

const TOKENS = {
  CM: 900, CD: 400, XC: 90, XL: 40, IX: 9, IV: 4,
  M: 1000, D: 500, C: 100, L: 50, X: 10, V: 5, I: 1,
};

export function parseRoman(input) {
  const numeral = input.trim().toUpperCase();

  if (numeral === '') {
    throw new Error('Input is empty — enter a Roman numeral, e.g. XIV.');
  }

  if (!ROMAN_PATTERN.test(numeral)) {
    throw new Error(`"${input.trim()}" is not a valid Roman numeral (valid range I–MMMCMXCIX, 1–3999).`);
  }

  let value = 0;
  let rest = numeral;
  while (rest !== '') {
    const pair = rest.slice(0, 2);
    if (Object.prototype.hasOwnProperty.call(TOKENS, pair)) {
      value += TOKENS[pair];
      rest = rest.slice(2);
    } else {
      const single = rest.slice(0, 1);
      value += TOKENS[single];
      rest = rest.slice(1);
    }
  }
  return value;
}
