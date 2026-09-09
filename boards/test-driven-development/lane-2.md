## Idea 2: word-count REST service

Build a spec-first Spring Boot REST API as a Maven module in
`wordcount-service/`, inside this board's work directory. `POST /count` takes `{"text": "..."}` and returns
`{"words": <n>}`, using exactly the counting rule from lane 1. A health
endpoint answers `GET /count/health`.

Spec-first is the point of this lane, not an implementation detail. An OpenAPI
document is the source of truth: the `openapi-generator-maven-plugin`
generates the API interface from it at build time, and the controller
implements that generated interface. Changing the contract means editing the
document, not the Java. A hand-written interface that happens to match the
document does not satisfy this.

Tests come in three layers and the split is deliberate: unit tests for the
counting service, contract tests holding the response shape to the OpenAPI
document, and integration tests running under failsafe against a live
application context on a real port. Surefire and failsafe stay separate so
`mvn test` remains fast and the slow layer runs on demand.

The two modules must not drift apart on a rule they are supposed to share.
Lane 1 was asked to make its counting rule callable from another module;
decide deliberately how this one consumes it — depending on lane 1's module,
or extracting a shared one — and say why. Reimplementing the rule here is the
option to argue against.

### Done means

- `POST /count` with `{"text": "one two three"}` returns `{"words": 3}`.
- `{"text": ""}` returns `{"words": 0}`; a malformed body returns 400, not
  500.
- `GET /count/health` answers 200.
- The API interface the controller implements is generated from the OpenAPI
  document at build time and is not hand-written.
- The CLI and the service agree on every counting case from lane 1,
  demonstrably — by sharing the rule, or by a test running the same cases
  against both.
- `mvn -pl wordcount-service verify` is green, with unit and contract tests
  under surefire and the integration tests under failsafe.
