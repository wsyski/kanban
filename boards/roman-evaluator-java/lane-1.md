## Idea 1: roman-number CLI

Build a command-line roman-number evaluator as a Maven module in `roman-cli/`:
it reads one roman numeral from standard input and prints its value as a
decimal integer to standard output. `XIV` is 14 and `MMMCMXCIX` is 3999. Only
the seven roman digits `M D C L X V I` are accepted, and only in their
canonical spelling: `IIII`, `VX` and `IXX` are invalid, empty input is invalid,
and a numeral above 3999 has no value. Invalid input prints a message to
standard error and exits 1. Java 17, JUnit 5, no runtime dependencies beyond
the JDK. The build produces a fat jar, so the result runs as `java -jar` with
nothing else installed.

Keep the evaluation rule in a class of its own, separate from the code that
reads the stream. The REST service in lane 2 evaluates the same numerals and
must not have to reimplement the rule or copy it out of a `main` method — so
the rule has to be callable from another module without going through `main`.

Cover the rule properly, not just the happy path: `I`, `XIV`, `MMMCMXCIX`, the
six subtractive pairs (`IV`, `IX`, `XL`, `XC`, `CD`, `CM`), and the rejections
above — `IIII`, `VX`, `IXX`, empty input, a lowercase or non-roman character, a
numeral that would exceed 3999. Test the stdin-to-stdout path separately from
the rule itself, so a failure tells you which of the two broke.

### The work directory may not be empty

The driver never clears it, so `roman-cli/` may already be there from an earlier
run — **the previous version of this project**, and this idea's input. Read it
before planning: if the module exists, this idea is a request to improve or fix
it, and the smallest correct change to what is there beats a rewrite. If the
directory is empty, build it from nothing. Both are this idea.

A sibling `roman-service/` from lane 2 may also be present. It is not this
lane's, and it is not litter either — leave it alone. Nothing is deleted to
"start clean": clearing the work directory is a human decision
(`mission/reset.sh`), and a card that removes what it did not plan to replace
destroys the only copy of the last run's work.

This lane exists to exercise the board end to end on a problem small enough
that a wrong answer is obvious. Prefer the boring solution: no framework, no
argument parser, no configurability nobody asked for.

### Done means

- `echo "XIV" | java -jar roman-cli/target/*.jar` prints `14`.
- `echo "MMMCMXCIX" | java -jar roman-cli/target/*.jar` prints `3999`.
- `echo "IIII" | java -jar roman-cli/target/*.jar` prints nothing on stdout,
  writes a message to standard error and exits 1; the same for empty input.
- The evaluation rule is callable from another module without going through
  `main`.
- `mvn -pl roman-cli test` is green from the work directory, with the rule and
  the stream path covered by separate tests.
