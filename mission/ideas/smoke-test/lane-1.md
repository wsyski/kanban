## Idea 1: word-count CLI
<!-- integration-tests: false -->
Build a command-line word counter in `wordcount-cli/`: a Maven module producing
a fat jar that reads text from stdin and prints the number of words to stdout.
A word is a maximal run of non-whitespace characters. Empty input prints `0`.
Java 17, JUnit 5, no runtime dependencies beyond the JDK.
