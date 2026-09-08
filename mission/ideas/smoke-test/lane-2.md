## Idea 2: word-count REST service
<!-- integration-tests: true -->
Build a spec-first Spring Boot REST API in `wordcount-service/`: `POST /count`
takes `{"text": "..."}` and returns `{"words": <n>}`, using the same counting
rule as the CLI. Generate the API interface from an OpenAPI document with the
openapi-generator Maven plugin; the controller implements the generated
interface. Integration tests run under failsafe against a live context.
