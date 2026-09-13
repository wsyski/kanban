package com.example.roman.service;

import com.example.roman.RomanNumeral;
import java.util.List;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class RomanEvaluationServiceTest {

    private final RomanEvaluationService service = new RomanEvaluationService();

    @Test
    void evaluatesCanonicalNumerals() {
        assertEquals(14, service.evaluate("XIV"));
        assertEquals(1, service.evaluate("I"));
        assertEquals(3999, service.evaluate("MMMCMXCIX"));
    }

    @Test
    void rejectsNonCanonicalNumerals() {
        assertThrows(IllegalArgumentException.class, () -> service.evaluate("IIII"));
        assertThrows(IllegalArgumentException.class, () -> service.evaluate(null));
        assertThrows(IllegalArgumentException.class, () -> service.evaluate(""));
    }

    @Test
    void agreesWithTheCliRuleOnEveryLaneOneCase() {
        for (String numeral : List.of(
                "I", "IV", "IX", "XIV", "XL", "XC", "CD", "CM", "MCMXCIV", "MMMCMXCIX")) {
            assertEquals(RomanNumeral.parse(numeral), service.evaluate(numeral), numeral);
        }
        for (String rejected : List.of("", "IIII", "VX", "IXX", "MMMM", "xiv", "ABC")) {
            assertThrows(IllegalArgumentException.class, () -> service.evaluate(rejected), rejected);
        }
    }
}
