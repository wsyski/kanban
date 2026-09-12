package com.example.roman;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;

/**
 * Reads one roman numeral from a stream and prints its value, or a message and a non-zero status.
 */
public final class RomanMain {

    private RomanMain() {
    }

    public static void main(String[] args) {
        System.exit(run(System.in, System.out, System.err));
    }

    public static int run(InputStream in, PrintStream out, PrintStream err) {
        String numeral;
        try {
            numeral = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8)).readLine();
        } catch (IOException e) {
            err.println("could not read standard input: " + e.getMessage());
            return 1;
        }
        if (numeral == null) {
            numeral = "";
        }
        try {
            out.println(RomanNumeral.parse(numeral));
            return 0;
        } catch (IllegalArgumentException e) {
            err.println(e.getMessage());
            return 1;
        }
    }
}
