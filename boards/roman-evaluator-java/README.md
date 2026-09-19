# roman-evaluator-java — before you start

The two ideas are one problem in two shapes: lane 1 a CLI (`roman-cli/`) that evaluates
one roman numeral from stdin, lane 2 a spec-first Spring Boot REST API
(`roman-service/`) that consumes lane 1's rule. It is the one shipped two-lane board, so
it is where lane chaining (`Gc1 → I2`) is exercised; lane 2 alone has integration tests
(`"integration-tests": [false, true]`).

Both lanes build inside this board's work directory, `boards/roman-evaluator-java/work/`;
the modules, their POMs and their tests all live under that one path. `max-runtime` is
20 minutes per card and `max-reworks` is 3.

The work directory is never cleared, so a second run finds `roman-cli/` and
`roman-service/` from the last one and treats them as the previous version to improve.
Delete them by hand for a blank start. A new idea typed into the Triage card and dragged
to Todo archives the previous run's cards and leaves the product in place; to archive
the cards and unstage what a dead run left pending without a new idea:

    driver/reset.sh --board boards/roman-evaluator-java

## Running it

See §3 of the root README; the board-specific commands are:

    driver/create-board.sh --board boards/roman-evaluator-java
    hermes kanban boards switch roman-evaluator-java      # create files the board
                                                          # but leaves it NON-current
    driver/start-board.sh --slug roman-evaluator-java    # serve; releases nothing
    driver/run-audit.py --runs boards/roman-evaluator-java/runs    # 0/0 is the pass

The go signal is the seeded Triage card dropped in the **Todo** column, or
`driver/arm.sh roman-evaluator-java 1` from a shell. Never **Ready**: with
`kanban.default_assignee` set to `coder` the dispatcher assigns and spawns the card before
the driver can read it as the idea, and the lane then sits parked. Lane 2 opens on lane 1's
`Gc1` rather than on an arm, so one gesture starts both lanes.

## Toolchain

JDK 17 and Maven 3.9 — needed by these ideas, not by the template. Workers have
iteration budgets, so pre-warm `~/.m2` before starting, or the first build spends them
on downloads:

    javac -version && mvn -version
    mvn -q dependency:get -Dartifact=org.springframework.boot:spring-boot-starter-web:3.5.10
    mvn -q dependency:get -Dartifact=org.openapitools:openapi-generator-maven-plugin:7.8.0
    mvn -q dependency:get -Dartifact=org.apache.maven.plugins:maven-failsafe-plugin:3.5.4
