# test-driven-development — before you start

Both lanes build from nothing, inside this board's own work directory,
`boards/test-driven-development/work/`. Nothing they generate lands anywhere
else in the repository — the modules, their POMs, their tests and the plan
files all live under that one path.

So a clean start is one line:

    rm -rf boards/test-driven-development/work
    mission/create-board.sh --board boards/test-driven-development
    mission/start-board.sh --slug test-driven-development

That matters here more than for most boards: a lane that finds its deliverable
already present reviews code instead of writing it, and the RED-first test card
has nothing to fail against. An earlier run of these ideas left `wordcount-cli/`
and `wordcount-service/` at the repository root; they were removed on
2026-09-09 and git holds them — `git log -- wordcount-cli`, last state of the
service at commit `479f8e7`.

Toolchain, needed by these two ideas and not by the board template: JDK 17 and
Maven 3.9. Workers have iteration budgets, so pre-warm `~/.m2` before starting
or the first build burns them on downloads:

    javac -version && mvn -version
    mvn -q dependency:get -Dartifact=org.springframework.boot:spring-boot-starter-web:3.5.10
    mvn -q dependency:get -Dartifact=org.openapitools:openapi-generator-maven-plugin:7.8.0
    mvn -q dependency:get -Dartifact=org.apache.maven.plugins:maven-failsafe-plugin:3.5.4
