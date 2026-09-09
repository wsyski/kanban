## Idea 1: word-count CLI

Build a command-line word counter as a Maven module in `wordcount-cli/`: it
reads text from standard input and prints the number of words to standard
output. A word is a maximal run of non-whitespace characters, so `"  a  b  "`
is 2 and empty input prints `0`. Java 17, JUnit 5, no runtime dependencies
beyond the JDK. The build produces a fat jar, so the result runs as
`java -jar` with nothing else installed.

Keep the counting rule in a class of its own, separate from the code that
reads the stream. The REST service in lane 2 implements the same rule and must
not have to reimplement it or copy it out of a `main` method — so the rule has
to be callable from another module without going through `main`.

Cover the rule properly, not just the happy path: empty input, whitespace
only, a single word, runs of spaces, tabs and newlines as separators, leading
and trailing whitespace. Test the stdin-to-stdout path separately from the
rule itself, so a failure tells you which of the two broke.

This lane exists to exercise the board end to end on a problem small enough
that a wrong answer is obvious. Prefer the boring solution: no framework, no
argument parser, no configurability nobody asked for.

### Done means

- `echo "one two three" | java -jar wordcount-cli/target/*.jar` prints `3`.
- Empty input prints `0` and exits 0.
- Tabs, newlines and runs of spaces all count as one separator.
- The counting rule is callable from another module without going through
  `main`.
- `mvn -pl wordcount-cli test` is green from the work directory, with the
  rule and the stream path
  covered by separate tests.
