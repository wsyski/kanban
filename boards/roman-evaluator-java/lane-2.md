## Idea 2: roman-number REST service

Build a spec-first Spring Boot REST API as a Maven module in `roman-service/`,
inside this board's work directory. `POST /evaluate` takes `{"roman": "XIV"}`
and returns `{"value": 14}`, using exactly the evaluation rule from lane 1. A
health endpoint answers `GET /evaluate/health`.

Spec-first is the point of this lane, not an implementation detail. An OpenAPI
document is the source of truth: the `openapi-generator-maven-plugin`
generates the API interface from it at build time, and the controller
implements that generated interface. Changing the contract means editing the
document, not the Java. A hand-written interface that happens to match the
document does not satisfy this.

Tests come in three layers and the split is deliberate: unit tests for the
evaluation service, contract tests holding the response shape to the OpenAPI
document, and integration tests running under failsafe against a live
application context on a real port. Surefire and failsafe stay separate so
`mvn test` remains fast and the slow layer runs on demand.

### The work directory may not be empty

`roman-cli/` is expected to be there — lane 1 built it, and this lane consumes its
rule. `roman-service/` may be there too, from an earlier run: that is **the
previous version of this module** and this idea's input. Read it before planning:
if the service exists, this idea is a request to improve or fix it, and the
smallest correct change beats a rewrite. Nothing is deleted to "start clean" —
least of all lane 1's module, which this lane depends on. Clearing the work
directory is a human decision (`mission/reset.sh`).

The two modules must not drift apart on a rule they are supposed to share.
Lane 1 was asked to make its evaluation rule callable from another module;
decide deliberately how this one consumes it — depending on lane 1's module,
or extracting a shared one — and say why. Reimplementing the rule here is the
option to argue against.

### Done means

- `POST /evaluate` with `{"roman": "XIV"}` returns `{"value": 14}`.
- `{"roman": "IIII"}` is rejected as a client error (400), not 500; a malformed
  body is a client error too.
- `GET /evaluate/health` answers 200.
- The API interface the controller implements is generated from the OpenAPI
  document at build time and is not hand-written.
- The CLI and the service agree on every roman case from lane 1,
  demonstrably — by sharing the rule, or by a test running the same cases
  against both.
- `mvn -pl roman-service verify` is green, with unit and contract tests under
  surefire and the integration tests under failsafe.
