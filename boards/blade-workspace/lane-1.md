<!-- unit-tests: false -->
## Idea 1: readme_says_what_is_here

The README at the root of the work directory is the stock Liferay Workspace
template text. It describes a folder tree called `my-project` that this project
does not have, and it says nothing about what this project actually contains.
Replace that boilerplate with a README that describes THIS workspace.

Survey the work directory first, and write only what you found. The tree is a
real project with history — the survey is the input to this idea, not a
formality, and anything the README claims has to be a thing you can point at in
the directory.

Keep the parts of the stock README that are still true (the upstream Liferay
Workspace documentation link, the local-run instructions if they match this
project's setup) and drop the parts that are not.

Do not build. No Gradle, no Docker, no bundle, no test run — this idea is a
documentation pass on an existing tree, and the toolchain is deliberately out of
scope. Do not touch any file other than the root README.

### Done means

- The root `README.md` describes this workspace's real contents: the module it
  actually ships and that module's sub-projects, the configuration environments
  under `configs/`, and the other top-level directories that carry content.
- The stock `my-project` folder-tree diagram is gone, or replaced by one that
  matches the directory it sits in.
- Every path the README names exists in the work directory.
- The README is the only file this idea changes. Nothing else is staged, and
  nothing is committed.
