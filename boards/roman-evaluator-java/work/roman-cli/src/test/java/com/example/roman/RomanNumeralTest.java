package com.example.roman;

import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.lang.reflect.Modifier;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RomanNumeralTest {

    @Test
    void acceptsEveryCanonicalSpelling() {
        String[] numerals = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
                "XIV", "XL", "XLII", "XC", "XCIX", "CD", "CDXLIV", "CM", "CMXCIX", "M", "MMMCMXCIX"};
        int[] values = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                14, 40, 42, 90, 99, 400, 444, 900, 999, 1000, 3999};
        assertEquals(numerals.length, values.length);
        for (int i = 0; i < numerals.length; i++) {
            assertEquals(values[i], RomanNumeral.parse(numerals[i]), "covers SC1/SC2 for " + numerals[i]);
        }
    }

    @Test
    void rejectsEveryNonCanonicalAndOutOfRangeSpelling() {
        String[] invalid = {"IIII", "VX", "IXX", "IIX", "VIV", "IC", "IL", "XM", "XMM", "MMMM", "XXXXXXXXXX"};
        for (String numeral : invalid) {
            IllegalArgumentException thrown = assertThrows(IllegalArgumentException.class,
                    () -> RomanNumeral.parse(numeral), "covers SC3 for " + numeral);
            assertFalse(thrown.getMessage() == null || thrown.getMessage().isEmpty(),
                    "covers SC3: a message for " + numeral);
        }
    }

    @Test
    void rejectsEmptyNullAndNonRomanText() {
        String[] invalid = {"", "xiv", "ABC", "XIV ", " 14", "M D"};
        for (String numeral : invalid) {
            IllegalArgumentException thrown = assertThrows(IllegalArgumentException.class,
                    () -> RomanNumeral.parse(numeral), "covers SC3 for <" + numeral + ">");
            assertFalse(thrown.getMessage() == null || thrown.getMessage().isEmpty(), "covers SC3");
        }
        assertThrows(IllegalArgumentException.class, () -> RomanNumeral.parse(null), "covers SC3");
    }

    @Test
    void exposesTheRuleAsAPublicStaticEntryPointThatIsNotMain() throws Exception {
        Method parse = RomanNumeral.class.getMethod("parse", String.class);
        assertTrue(Modifier.isPublic(parse.getModifiers()), "covers SC4");
        assertTrue(Modifier.isStatic(parse.getModifiers()), "covers SC4");
        assertEquals(int.class, parse.getReturnType(), "covers SC4");
        assertThrows(NoSuchMethodException.class,
                () -> RomanNumeral.class.getMethod("main", String[].class), "covers SC4");
    }
}
