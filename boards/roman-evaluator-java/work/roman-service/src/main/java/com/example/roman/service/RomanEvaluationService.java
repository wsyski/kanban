package com.example.roman.service;

import com.example.roman.RomanNumeral;
import org.springframework.stereotype.Service;

/**
 * The service's evaluation rule: lane 1's rule, consumed and never reimplemented.
 */
@Service
public class RomanEvaluationService {

    /**
     * Evaluates one roman numeral.
     *
     * @param roman the numeral, taken verbatim
     * @return its value, between 1 and 3999
     * @throws IllegalArgumentException if the numeral is null, empty, not roman, non-canonical,
     *         or greater than 3999
     */
    public int evaluate(String roman) {
        return RomanNumeral.parse(roman);
    }
}
