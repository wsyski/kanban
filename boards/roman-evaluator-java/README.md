# roman-evaluator-java — before you start

Both lanes build from nothing, inside this board's own work directory,
`boards/roman-evaluator-java/work/`. Nothing they generate lands anywhere else
in the repository — the modules, their POMs, their tests and the plan files all
live under that one path. Nothing here deletes anything — a finished run's log,
timing and hand-offs stay readable under `runs/<run-id>/`, and the work directory
is never touched. To archive the cards and unstage what a dead run left pending:

    mission/reset.sh --board boards/roman-evaluator-java

The work directory is never touched by anything here, so a second run finds
`roman-cli/` and `roman-service/` from the last one and treats them as the previous
version to improve. Delete them by hand if you want a blank start.

Or just type a new idea into the Triage card and drag it to Todo, which archives
the previous run for you and leaves the product in place.

The two ideas are one problem in two shapes: lane 1 a CLI (`roman-cli/`) that
evaluates one roman numeral from stdin, lane 2 a spec-first Spring Boot REST API
(`roman-service/`) that consumes lane 1's rule.

Toolchain, needed by these two ideas and not by the board template: JDK 17 and
Maven 3.9. Workers have iteration budgets, so pre-warm `~/.m2` before starting
or the first build spends them on downloads:

    javac -version && mvn -version
    mvn -q dependency:get -Dartifact=org.springframework.boot:spring-boot-starter-web:3.5.10
    mvn -q dependency:get -Dartifact=org.openapitools:openapi-generator-maven-plugin:7.8.0
    mvn -q dependency:get -Dartifact=org.apache.maven.plugins:maven-failsafe-plugin:3.5.4
