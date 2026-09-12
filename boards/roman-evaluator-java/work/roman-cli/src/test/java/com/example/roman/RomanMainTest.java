package com.example.roman;

import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

class RomanMainTest {

    private static final class Outcome {
        private final int status;
        private final String out;
        private final String err;

        private Outcome(int status, String out, String err) {
            this.status = status;
            this.out = out;
            this.err = err;
        }
    }

    private static Outcome run(String stdin) {
        InputStream in = new ByteArrayInputStream(stdin.getBytes(StandardCharsets.UTF_8));
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        ByteArrayOutputStream err = new ByteArrayOutputStream();
        int status = RomanMain.run(in,
                new PrintStream(out, true, StandardCharsets.UTF_8),
                new PrintStream(err, true, StandardCharsets.UTF_8));
        return new Outcome(status, out.toString(StandardCharsets.UTF_8), err.toString(StandardCharsets.UTF_8));
    }

    @Test
    void printsTheValueOfTheFirstLine() {
        Outcome xiv = run("XIV\n");
        assertEquals(0, xiv.status, "covers SC1");
        assertEquals("14", xiv.out.trim(), "covers SC1");
        assertEquals("", xiv.err.trim(), "covers SC1");

        Outcome long_ = run("MMMCMXCIX\n");
        assertEquals(0, long_.status, "covers SC2");
        assertEquals("3999", long_.out.trim(), "covers SC2");
        assertEquals("", long_.err.trim(), "covers SC2");
    }

    @Test
    void rejectsInvalidInputWithAnEmptyStdoutAndANonEmptyStderr() {
        String[] stdin = {"IIII\n", "VX\n", "IXX\n", "xiv\n", "ABC\n", "", "\n", "MMMM\n"};
        for (String input : stdin) {
            Outcome rejected = run(input);
            assertEquals(1, rejected.status, "covers SC3/SC7 for input <" + input + ">");
            assertEquals("", rejected.out.trim(), "covers SC3/SC7: stdout stays empty for <" + input + ">");
            assertFalse(rejected.err.trim().isEmpty(), "covers SC3/SC7: a message on stderr for <" + input + ">");
        }
    }

    @Test
    void readsOnlyTheFirstLine() {
        Outcome first = run("XIV\nMMMCMXCIX\n");
        assertEquals(0, first.status);
        assertEquals("14", first.out.trim());
    }

    @Test
    void keepsTheNumeralVerbatim() {
        Outcome padded = run("XIV \n");
        assertEquals(1, padded.status, "covers SC3: no trimming");
        assertEquals("", padded.out.trim(), "covers SC3");
        assertFalse(padded.err.trim().isEmpty(), "covers SC3");
    }
}
