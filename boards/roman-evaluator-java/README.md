# roman-evaluator-java — before you start

Both lanes build from nothing, inside this board's own work directory,
`boards/roman-evaluator-java/work/`. Nothing they generate lands anywhere else
in the repository — the modules, their POMs, their tests and the plan files all
live under that one path, so a clean start is one line:

    rm -rf boards/roman-evaluator-java/work

Or just type a new idea into the Triage card and drag it to Todo, which archives
the previous run for you.

The two ideas are one problem in two shapes: lane 1 a CLI (`roman-cli/`) that
evaluates one roman numeral from stdin, lane 2 a spec-first Spring Boot REST API
(`roman-service/`) that consumes lane 1's rule. This board used to build a
word-count CLI and service (it was called `test-driven-development`); the
earlier run's modules were removed on 2026-09-09 and git holds them —
`git log -- wordcount-cli`, last state of the service at commit `479f8e7`.

Toolchain, needed by these two ideas and not by the board template: JDK 17 and
Maven 3.9. Workers have iteration budgets, so pre-warm `~/.m2` before starting
or the first build spends them on downloads:

    javac -version && mvn -version
    mvn -q dependency:get -Dartifact=org.springframework.boot:spring-boot-starter-web:3.5.10
    mvn -q dependency:get -Dartifact=org.openapitools:openapi-generator-maven-plugin:7.8.0
    mvn -q dependency:get -Dartifact=org.apache.maven.plugins:maven-failsafe-plugin:3.5.4
