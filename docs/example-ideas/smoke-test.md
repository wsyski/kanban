# Example ideas — smoke test

The two deliverables the original smoke-test run built. Documentation, and
directly runnable:

    mission/create-board.sh --slug smoke-test --title "Kanban Smoke Test" \
        --lanes 2 --integration-tests false,true --ideas docs/example-ideas/smoke-test.md

`--integration-tests false,true` is the board default per lane: lane 1 without
integration cards, lane 2 with. The per-idea headers below say the same thing
for a reader of the idea itself; where the two ever disagree, the header wins
and the triage card says so.

Per-idea header syntax, shown here rather than in a lane below (a header
inside a `## ` section is read as real configuration, not illustration):

    <!-- integration-tests: false -->
    <!-- auto-gates: true -->

Booleans are `true`/`false` only.

## Idea 1: word-count CLI
<!-- integration-tests: false -->

Build a command-line word counter in `wordcount-cli/`: a Maven module producing
a fat jar that reads text from stdin and prints the number of words to stdout.
A word is a maximal run of non-whitespace characters. Empty input prints `0`.
Java 17, JUnit 5, no runtime dependencies beyond the JDK.

## Idea 2: word-count REST service
<!-- integration-tests: true -->

Build a spec-first Spring Boot REST API in `wordcount-service/`: `POST /count`
takes `{"text": "..."}` and returns `{"words": <n>}`, using the same counting
rule as the CLI. Generate the API interface from an OpenAPI document with the
openapi-generator Maven plugin; the controller implements the generated
interface. Integration tests run under failsafe against a live context.
