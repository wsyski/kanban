# Toolchain facts — roman-evaluator-liferay-client-ext

What earlier runs on this board VERIFIED about the toolchain, each with its evidence. The
researcher re-checks what the lane depends on; the planner's probe re-derives every value
it takes from here. Edit a line that turned out wrong. The driver appends a section when a
run finishes: the DEVIATIONs its code reviews named in a PASS, for lanes whose code gate
passed.

Evidence paths are under `runs/`: `R1` is `run-20260926-213701` (halted in the plan
loop), `R2` is `run-20260928-092648` (finished). `R1 RVp1-r2 #3` is finding 3 of that
review's `scratch/<card>/review.md`.

## Seeded by hand, 2026-09-28, from R1's plan reviews and R2's code card

### Paths and tools
- The portal checkout is `/opt/liferay/portal/arena-7.4.3.129-ga129/portal`, its bundle
  `/opt/liferay/portal/arena-7.4.3.129-ga129/bundles`; blade-workspace is
  `/opt/playground/liferay/workspaces/blade-workspace` (R2 I1's result; the idea named
  `/opt/projects/liferay/…` and `/home/playground/…`, which do not exist).
- Gradle 8.5 is `/home/wos/.sdkman/candidates/gradle/current/bin/gradle` — sdkman, not on
  a card's PATH (R2 I1).
- `gradle --version` prints `JVM:          17.0.12 (Oracle Corporation 17.0.12+8-LTS-286)`:
  match it with `grep -c "JVM:.*17\.0\.12"`, never `grep -x "JVM: 17.0.12"` (R1 RVp1-r2 #8).

### Gradle workspace
- `settings.gradle` with `plugins { id 'com.liferay.workspace' version '12.1.0' }` fails:
  the marker `com.liferay.workspace:com.liferay.workspace.gradle.plugin:12.1.0` is a 404 on
  repository-cdn.liferay.com and not on plugins.gradle.org. The `buildscript` classpath
  `com.liferay:com.liferay.gradle.plugins.workspace:12.1.0` + `apply plugin` works
  (R1 RVp1-r2 #1; R2 C1 deviation 1).
- The Node download: `node { nodeDownload = false }` fails ("Could not set unknown property
  'nodeDownload' for extension 'node'" — `nodeDownload` is a PROJECT property);
  `node { download = false }` on the root alone still downloaded Node v20.12.2 into
  `work/build/node`. What worked: `-PnodeDownload=false` on the command (both
  `downloadNode` tasks SKIPPED, R1 RVp1-r2 #2 and #5) and
  `subprojects { node { download = false } }` in `work/build.gradle` (R2 C1).
- The node plugin (8.0.7 through workspace plugin 12.1.0) has no `node` task; a
  client-extension project builds through `packageRunBuild`. `build` = assemble + check,
  and check runs `packageRunTest` — so `build` fails while the TW suite is absent or red;
  `-x packageRunTest` builds without it (R1 RVp1 #6, RVp1-r2 #6).
- The workspace build writes `package.json` (yarn workspaces), `.yarnrc` and an npm
  `package-lock.json` at `work/`'s root by itself — by-products, not deliverables
  (R1 RVp1-r2 #7; R2 C1).

### client-extension.yaml
- The list form `extensions: - id: …` throws ArrayNode→ObjectNode at configuration time
  (ClientExtensionProjectConfigurator.java:218-220). The sample shape works: the extension
  id as a top-level key, a top-level `assemble` (R1 RVp1-r2 #3; R2 RVa1).

### webpack 5.90.1
- `output.library.type: 'module'` needs `experiments: { outputModule: true }`
  (R1 RVp1 #2).
- `LimitChunkCountPlugin` is `webpack.optimize.LimitChunkCountPlugin`, not a top-level
  export (R1 RVp1 #3).
- Object externals match keys exactly: `'@clayui/': '@clayui/'` is not a prefix and every
  Clay package gets bundled (479 KiB). List each package, or use the function form with
  `externalsType: 'module'`; a regex as an object key is invalid JS (R1 RVp1 #4; R2 C1
  deviation 2). The correct bundle is ~2.5 KB importing exactly react, react-dom,
  @clayui/button, @clayui/form, @clayui/list.
- `"type": "module"` in package.json makes a CommonJS `webpack.config.js` fail
  ("require is not defined in ES module scope") (R2 RVp1 F1).

### Tests (Vitest 1.6 / Testing Library 12)
- Vitest does not read test config from a `"vitest"` key in package.json:
  `vitest run --environment jsdom --globals`, or a `vitest.config.mjs` (R1 RVp1-r2 #4).
- `jsdom` is only an optional peer of Vitest, and yarn classic does not install it:
  pin it in devDependencies (R1 RVp1 #5).
- `@testing-library/react` 12 cleans up between tests only with a global `afterEach`
  (`--globals`); without it renders stack in `document.body` (R1 RVp1 #7).
- `Node.remove()` takes no arguments: `document.body.remove(a, b)` removes `<body>`
  itself (R2 C1 TEST FIX).

### Clay 3.x
- `@clayui/list` 3.120.0 has `ClayList.ItemText`, not `ClayList.Text` (R1 RVp1 #1).
- The Clay 3.x packages are default exports, with `ClayInput` a named export of
  `@clayui/form` (R2 C1 deviation 3).

### Shell
- `grep -lE <pattern> .` without `-r` reads `.` as a file: "Is a directory", exit 2
  (R1 RVp1-r3 #1).
- A secret scan over `work/` matches the lock files (`js-tokens`,
  `@csstools/css-tokenizer`): scope it to hand-written files (R1 RVp1-r2 #7, RVp1-r3 #1).

## run-20260929-211109 — accepted at the code gate 2026-09-29

- lane 1: Task 3 Step 2: the plan said build.gradle carries subprojects { node { download = false } } -> I wrote subprojects { ext { nodeDownload = false } }, because build 1 with the plan's form shows the extension's downloadNode RAN and the extension build ran on the downloaded Node v20.12.2 / yarn 1.13.0 (not the host's v22.22.2 / yarn 1.22.22) — the NodeExtension reads the project property nodeDownload (NodeExtension.java:31) and the node { download = false } closure configures a throwaway object created before NodePlugin.apply() (NodePlugin.java:90-91), so it is inert; the ext-property form is what the extension reads (after-run: extension downloadNode SKIPPED, packageRunBuild/packageRunTest via host node, T4S4 via host yarn v1.22.22) (accepted by RVa1)
