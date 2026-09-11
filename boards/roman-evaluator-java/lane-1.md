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
