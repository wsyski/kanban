package com.example.roman;

/**
 * The evaluation rule for this board's roman numerals: canonical spellings of 1..3999 only.
 */
public final class RomanNumeral {

    private static final int[] VALUES = {
            1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1
    };

    private static final String[] SYMBOLS = {
            "M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"
    };

    private RomanNumeral() {
    }

    /**
     * Evaluates one roman numeral.
     *
     * @param numeral the numeral, taken verbatim
     * @return its value, always between 1 and 3999
     * @throws IllegalArgumentException if the numeral is null, empty, not roman, not in the
     *         canonical spelling, or greater than 3999
     */
    public static int parse(String numeral) {
        if (numeral == null) {
            throw new IllegalArgumentException("invalid roman numeral: null");
        }
        int value = 0;
        int i = 0;
        while (i < numeral.length()) {
            int matched = -1;
            for (int s = 0; s < SYMBOLS.length; s++) {
                if (numeral.startsWith(SYMBOLS[s], i)) {
                    matched = s;
                    break;
                }
            }
            if (matched < 0) {
                throw new IllegalArgumentException("invalid roman numeral: " + numeral);
            }
            value += VALUES[matched];
            i += SYMBOLS[matched].length();
        }
        if (value < 1 || value > 3999) {
            throw new IllegalArgumentException("invalid roman numeral: out of range: " + numeral);
        }
        if (!encode(value).equals(numeral)) {
            throw new IllegalArgumentException("invalid roman numeral: non-canonical: " + numeral);
        }
        return value;
    }

    private static String encode(int value) {
        StringBuilder roman = new StringBuilder();
        for (int s = 0; s < SYMBOLS.length; s++) {
            while (value >= VALUES[s]) {
                roman.append(SYMBOLS[s]);
                value -= VALUES[s];
            }
        }
        return roman.toString();
    }
}
