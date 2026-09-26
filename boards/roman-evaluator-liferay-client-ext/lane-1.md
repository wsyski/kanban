## Idea 1: Roman number evaluator - Liferay client extension (React + Clay components)

Build a Liferay **custom element client extension** — a widget an administrator can place
on any Liferay page — implementing a roman number evaluator with **the React and the Clay components the portal
already loads**, styled by the CSS the portal already provides, deployable to the local
Liferay Portal CE 7.4 GA129 bundle:

    /opt/projects/liferay/portal/arena-7.4.3.129-ga129/bundles

### Target portal: Arena Liferay Portal

The portal is the **Arena Liferay Portal**, Axiell's fork of Liferay Portal CE 7.4.3.129
GA129:

- Source: `/opt/projects/liferay/portal/arena-7.4.3.129-ga129/portal`, branch
  `arena-7.4.3.129-ga129`, base tag `7.4.3.129-ga129`. Read its `AGENTS.md` and
  `DESIGN.md` first. The Axiell vault describes it in
  `/home/wos/Documents/Obsidian/Axiell/wiki/entities/Arena-Liferay-Portal.md` and
  `.../wiki/analyses/project-summary-arena-liferay-portal.md`. Both are read-only for
  every card.
- Most code is upstream Liferay. Arena changes are narrow and tagged `PLCB-*`: treat
  behaviour as upstream unless
  `git -C <portal> log --oneline --grep PLCB -- <path>` shows an Arena change.
  Client extensions (`modules/apps/client-extension/`) are upstream code here.
- Runtime bundle: `/opt/projects/liferay/portal/arena-7.4.3.129-ga129/bundles`,
  with Tomcat in `tomcat-9.0.90/`, client extensions loaded from `osgi/client-extensions/`,
  logs in `tomcat-9.0.90/logs/catalina.out` and `logs/liferay.*.log`, and the OSGi shell
  on `telnet localhost 11611`.
- This idea changes nothing in the portal source or its bundle configuration. Cards
  read the checkout; they do not build it (Ant/Gradle there is the portal's own build) and
  do not write to it.

### Use the `liferay` skill

Every card that researches, plans, writes or reviews a Liferay-specific part of this
idea — the workspace, `client-extension.yaml`, the build, the deploy path, anything the
portal reads — first reads the hub's `liferay` skill and follows it:

    /home/wos/.agents/manual-skills/liferay/SKILL.md

It is a manual skill, so it is not in any skill index and no card force-loads it: read
it by that path (in Hermes, `skill_view liferay` shows the same file). It routes Liferay
questions to local sources — the GA129 portal checkout, the scraped docs in
`~/.liferay-docs` when present, and `/home/playground/liferay/liferay-blade-samples` —
and requires citing what was read (`file:line` or the doc's `url:`). A card answers a
Liferay question from those sources, not from memory. The skill is read-only for every
card: never edit, copy or patch it.

### Reference trees and what to take from each

Both trees are read-only. Copy files out of them into `work/`; never edit them in place.

**`portal/workspaces/liferay-sample-workspace/`** (in the portal checkout) — the shape
of a client extension. Nothing of its toolchain (wrapper, Node pin) is taken:

- `client-extensions/liferay-sample-custom-element-5/` is **the template**. It renders a
  Clay component (`@clayui/badge`) with the portal's React, builds one ES module with
  webpack into `build/static`, lists it with a glob (`urls: - index.*.js`), and bundles
  neither React nor Clay: its `webpack.config.js` declares them external, with the
  comment "Add all @clayui dependencies of your project below here (as done for
  `@clayui/badge`)":

      externals: {
          '@clayui/badge': '@clayui/badge',
          'react': 'react',
          'react-dom': 'react-dom',
      },

  With `useESM: true` those bare imports are resolved by the portal's import map to the
  modules the page already has. Copy its `package.json` build script, its
  `webpack.config.js` and its registration pattern (`ReactDOM.render` on connect,
  `ReactDOM.unmountComponentAtNode` on disconnect, `customElements.get` guard).
- `-4` is the same build with `react`/`react-dom` external and a CSS loader; it shows the
  React 16 API with `React.createElement`.
- `-2` uses React 18 (`createRoot`) bundled by `react-scripts`: the one sample **not** to
  follow, because it loads a second React onto the page.
- Every sample's `client-extension.yaml` has `assemble: - from: build/static, into:
  static`. Follow it: the bundler writes to `build/static`.
- Its root files are **not** portable: `settings.gradle` resolves the workspace plugin
  from `mavenLocal()` and `../../.m2-tmp` (a path inside the portal checkout),
  `gradle.properties` declares `dxp-2023.q4.5`, and `build.gradle` pins
  `node { nodeVersion = "16.15.1" }`. None of the three is copied as is.

**`/home/playground/liferay/workspaces/blade-workspace`** — the root files, on the GA129
line:

- `settings.gradle` applies `com.liferay.workspace` from `mavenLocal()`,
  `repository-cdn.liferay.com`, `mavenCentral()` and `gradlePluginPortal()`, with the
  plugin version from a property (`12.1.0`). `work/settings.gradle` copies this shape
  and writes the version **literally** (`12.1.0`), since `work/gradle.properties`
  does not carry that property.
- Its Gradle wrapper is **not** copied: the workspace runs on the workstation's own
  Gradle (see Toolchain).
- **Its `gradle.properties` is never copied.** It holds repository credentials and
  Axiell-internal settings that must not enter `work/`, which is tracked and committed.
  `work/gradle.properties` is written from scratch with exactly the lines under
  "What to build".

GA129 supports the `customElement` type with `urls`, `cssURLs`, `htmlElementName`,
`friendlyURLMapping`, `portletCategoryName`, `instanceable` and `useESM`:
`portal/modules/apps/client-extension/client-extension-type-api/src/main/java/com/liferay/client/extension/type/CustomElementCET.java`.
The researcher confirms these facts against the sources, not re-derives them.

### Reuse Liferay first

Reuse as much as possible from Liferay and write only what Liferay does not provide. At
every layer, the first question a card asks is "what does Liferay already ship for
this?", answered from the `liferay` skill's sources, before writing anything:

- **Build and packaging:** the Liferay workspace plugin, its client-extension build
  (which runs the extension's `package.json` `build` script) and its `deploy` task. No
  custom packaging scripts and no hand-assembled archives.
- **Extension shape:** `client-extension.yaml`, the `customElement` type and its
  properties, laid out as the samples lay them out.
- **Runtime: React and Clay from the portal.** `react`, `react-dom` and every
  `@clayui/*` component come from the portal's import map, the same copies the portal's
  own UI uses. The extension bundles **none** of them: the page never loads a second
  React or a second Clay.
- **UI:** Clay React components (`@clayui/*`) for every control. No hand-written
  equivalent of something Clay provides.
- **Styling:** the theme's Clay CSS already on the page. No bundled CSS framework.
- **Placement and configuration:** the portal's own widget handling (the page editor's
  Client Extensions category, `instanceable`, `friendlyURLMapping`). No custom portlet
  or OSGi module.

What remains hand-written is small: the roman-numeral parser, the component that wires
Clay controls to it, the custom-element registration, the externals list in the copied
webpack config, and their tests.
When a card writes something Liferay might already provide, its report names the source
it checked (`file:line` or doc `url:`) that shows Liferay does not.

### What to build

The board's work directory becomes a minimal **Liferay workspace** holding one client
extension:

    work/
      settings.gradle                  # blade-workspace shape, plugin 12.1.0 literal
      build.gradle                     # only what makes the build use the host's Node (see Toolchain)
      gradle.properties                # exactly the lines below
      .gitignore                       # node_modules/, build/, dist/, .gradle/, bundles/
      client-extensions/roman-evaluator/
        client-extension.yaml
        package.json                   # webpack (from sample 5); react, react-dom, @clayui/* as
                                       #   devDependencies for tests only; vitest + testing libs
        yarn.lock                      # committed: the build is reproducible
        webpack.config.js              # copied from sample 5, externals extended
        src/roman.js                   # parsing module, no DOM, no React
        src/RomanEvaluator.js          # the React component, React.createElement, no JSX
        src/index.js                   # defines the <roman-evaluator> custom element
        src/*.test.js                  # unit tests

`gradle.properties` is exactly:

    liferay.workspace.product=portal-7.4-ga129
    liferay.workspace.home.dir=/opt/projects/liferay/portal/arena-7.4.3.129-ga129/bundles
    liferay.workspace.node.package.manager=yarn

so `gradle deploy` in the workspace copies the built extension into that bundle's
`osgi/client-extensions/`. No credentials, no repository settings, no Axiell properties.

`client-extension.yaml` declares one extension of `type: customElement`:

- extension id and `htmlElementName`: `roman-evaluator`
- `name`: `Roman Evaluator`
- `portletCategoryName: category.client-extensions`
- `friendlyURLMapping: roman-evaluator`
- `instanceable: true`
- `useESM: true`
- `urls: - index.*.js`, the glob sample 5 uses for its content-hashed output, and no
  `cssURLs` unless the widget needs its own rules (see Styling)
- `assemble: - from: build/static, into: static`, as in the samples

`package.json` scripts:

- `"build": "webpack"` — as in sample 5; what the workspace build runs.
- `"test": "vitest run"` — never bare `vitest`, which watches in a terminal and never
  exits.

`webpack.config.js` is sample 5's, changed only where this widget differs:

- `externals` lists `react`, `react-dom` and every `@clayui/*` package the source imports
  (`@clayui/button`, `@clayui/form`, `@clayui/list`, and any other one it ends up
  using). A regex or function covering `^@clayui/` is acceptable so that no Clay
  package, direct or transitive, can slip into the bundle.
- `entry` points at `src/index.js`; output stays `build/static/index.[contenthash].js`,
  one chunk, `library.type: 'module'`.
- No loaders: there is no JSX and no CSS import to transform.

### Toolchain: the workstation's own

Java, Gradle and Node come from the workstation (`zeus`), as installed. The workspace
downloads no JDK, no Gradle distribution and no Node distribution:

- **Java:** the JDK on `PATH` / `JAVA_HOME`, 17 (the GA129 line's
  `javaSourceCompatibility`).
- **Gradle:** the `gradle` on `PATH`. No wrapper in `work/` (`gradlew`, `gradlew.bat`,
  `gradle/wrapper/` are neither copied nor generated), so every command here is
  `gradle ...` run from `work/`. The installed version must be one workspace plugin
  12.1.x runs on; the researcher records `gradle --version` and cites what the plugin
  requires.
- **Node and yarn:** the `node` and `yarn` (classic) on `PATH`, for both `yarn test` and
  the workspace build's `yarn build`. The Liferay Node plugin downloads its own Node by
  default (the sample workspace pins 16.15.1 through `node { nodeVersion = ... }`). The
  plan turns that off in `work/build.gradle` with the Node plugin's own switch for using
  the Node on `PATH`. The switch is defined in
  `portal/modules/sdk/gradle-plugins-node/src/main/java/com/liferay/gradle/plugins/node/NodeExtension.java`,
  and the workspace applies the Node plugin in
  `portal/modules/sdk/gradle-plugins-workspace/src/main/java/com/liferay/gradle/plugins/workspace/LiferayWorkspaceNodePlugin.java`;
  the plan cites both `file:line`. The build log is the evidence: no Node download, and the
  build's `node --version` equals the host's. Likewise no yarn download if the workspace's
  yarn setup (`task/SetUpYarnTask.java` there) would fetch one.
- webpack (sample 5's version) and Vitest versions must run on the host Node (their
  `engines` accept it), not the other way round.

The researcher records `java -version`, `gradle --version`, `node --version` and
`yarn --version`. A missing tool, or a version the chosen stack cannot run on, stops the
lane at the researcher card with an install recommendation; nothing is installed.

### Behaviour

The widget shows:

- a text input for a roman number, with a visible label,
- two buttons in one row below the input: **Evaluate** and **Reset**,
- a result list below the buttons.

Rules:

- **Evaluate** reads the input as a roman number, trimmed and upper-cased, and appends
  a row `ROMAN = ARABIC` using the upper-cased form (`xiv` → `XIV = 14`). Every
  evaluation adds a row; earlier rows stay.
- An invalid roman number shows an `alert()` with an error message and appends no row.
  Invalid means: empty (or whitespace-only) input, characters outside `MDCLXVI`
  (case-insensitive), or a malformed numeral (for example `IIII`, `VX`, `IXX`, `MMMM`).
  Subtractive notation (`IV`, `IX`, `XL`, `XC`, `CD`, `CM`) is handled; `MMMCMXCIX`
  (3999) is the valid upper bound. The simplest correct rule: a numeral is valid iff
  converting its value back to canonical roman yields the same string.
- **Reset** clears the input and the result list.
- Enter in the input triggers Evaluate.
- Two instances of the widget on one page work independently: each custom element has
  its own React root and state, and nothing is kept in module-level variables.
- Removing the element from the page unmounts its root; re-inserting it (the page editor
  moves elements this way) mounts a fresh one without errors.

### Technology

- **React and Clay are the portal's, never bundled.** The page already loads React
  and the Clay components for the portal's own UI, and shares them with client
  extensions through its import map. The widget uses those copies. Loading a second React
  or a second copy of any Clay component is exactly what this idea rules out: no bundled
  `react`, `react-dom` or `@clayui/*`, and no React 18 alongside the portal's React.
- **The researcher establishes, citing `file:line`:**
  - the React version the GA129 page provides (expected 16.12, from the `package.json`
    files under `portal/modules/apps/frontend-js/`, e.g. `frontend-js-react-web`);
  - the `@clayui/*` versions it provides (expected 3.116–3.120, under
    `portal/modules/apps/frontend-js/` and `portal/modules/apps/frontend-taglib/`);
  - that `react`, `react-dom` and each `@clayui/*` package the widget imports are
    resolvable through the page's import map (sample 5's externals are the first
    evidence; the portal's import-map registration is the proof).

  A Clay component the import map does not provide is not bundled instead: the widget
  uses a Clay component that is provided, or plain Clay markup (`list-group`,
  `form-control`) styled by the theme.
- **Code to that React.** React 16 API, as samples 4 and 5 use it: `ReactDOM.render`
  and `ReactDOM.unmountComponentAtNode`, not `createRoot`. Hooks are fine (16.8+).
  **No JSX:** write `React.createElement` as the samples do. React 16.12 has no
  `react/jsx-runtime`, which modern JSX transforms import by default, so JSX would add
  a transpiler and risk an import the page cannot resolve.
- **Clay components**, imported by bare specifier from the portal:
  - `@clayui/form` (`ClayForm.Group`, `ClayInput`, a `<label>` tied to it) for the input;
  - `@clayui/button` (`displayType="primary"` Evaluate, `displayType="secondary"`
    Reset, in `ClayButton.Group` or one row);
  - `@clayui/list` (or plain Clay list markup) for the rows;
  - Clay layout and spacing utility classes for the rest.

  No Clay icons: they need the theme's spritemap path and nothing here needs one.
- **The Liferay global is not used.** The widget calls no Liferay API, so `src/` never
  references `Liferay` (it does not exist in jsdom, and nothing needs it).
- `src/index.js` follows sample 5: `customElements.get` guard, light DOM (**no shadow
  root**, so the theme's CSS reaches it), `ReactDOM.render(..., this)` on connect,
  `ReactDOM.unmountComponentAtNode(this)` on disconnect.
- **Styling: reuse what Liferay provides.** Every GA129 theme already ships Clay CSS
  (`@clayui/css` 3.x, built into `frontend-theme-unstyled`), so the widget is styled by
  the page it sits on. The extension bundles **no CSS**: no `@clayui/css` import, no
  Bootstrap, no CDN. A handful of widget-specific rules, if any are needed, go in one
  small CSS file listed in `cssURLs`, every rule scoped under the `roman-evaluator`
  selector. Bootstrap is a fallback only, if Clay demonstrably cannot style the widget,
  scoped to the element and served locally; the plan records that decision and its
  reason.
- **Tests:** Vitest in `jsdom`, against the **same versions the portal provides**:
  `react`, `react-dom` and the `@clayui/*` packages pinned in `devDependencies` to the
  researcher's versions, so the tests exercise what the page runs. They are test-only and
  never reach the bundle. `@testing-library/react` 12 (13+ requires React 18).
  `roman.js` is unit-tested on its own. The component is tested with
  `@testing-library/react`, `window.alert` mocked with `vi.spyOn`. The
  custom element is tested too: define it, append two `<roman-evaluator>` elements to
  `document.body`, drive both, remove one.

Nothing else: no persistence, no server calls, no arabic-to-roman direction, no Liferay
Objects, no OSGi module, no theme changes, no localisation.

### What the cards do and do not do

- Cards build and test inside the work directory only. They may download dependencies
  (Gradle plugins, npm/yarn packages); the first build needs network access. They never
  download a JDK, a Gradle distribution or a Node distribution.
- Cards do **not** deploy. `gradle deploy` writes into the portal bundle, which is
  outside the work directory, and the portal's state belongs to the operator. Cards do
  not start, stop or reconfigure the portal either.
- Toolchain: the workstation's Java 17, Gradle, Node and yarn classic (see Toolchain),
  and `blade` (optional).

### The work directory may not be empty

The driver never clears it, so whatever is already there is **the previous version of
this project**: this idea's input, not litter. Read it before planning. A run that finds
the deliverable already present is a request to improve or fix it, and the smallest
correct change to what exists beats rebuilding it. A run that finds the directory empty
builds it from nothing. Both are this idea.

Nothing is deleted to "start clean". Clearing the directory is a human decision
(`driver/reset.sh`), and a card that wipes what it did not plan to replace destroys the
only copy of the last run's work.

If a card finds itself with a decision to make, the answer is the smallest thing that
satisfies the lines above, checked against the `liferay` skill's sources.

### Done means

Each item is evidence a card records in its report (command and output).

1. **Layout.** `work/` holds the workspace and extension as in "What to build", including
   `yarn.lock`. `node_modules/`, `build/`, `dist/` and `.gradle/` are ignored, not
   deliverables. No scratch files are left behind.
2. **No secrets.** `work/gradle.properties` contains exactly the three lines above, and
   `grep -rinE "password|secret|token|artifactory" work --exclude-dir=node_modules
   --exclude-dir=.gradle` finds nothing.
3. **Unit tests.** `yarn test` in `client-extensions/roman-evaluator/` exits 0 and covers
   at least:
   - parser: `XIV` → 14, `xiv` → 14, `MMMCMXCIX` → 3999; rejection of `IIII`, `VX`,
     `IXX`, `MMMM`, empty input, whitespace-only input and a character outside `MDCLXVI`;
   - component: Evaluate on `XIV` appends one row `XIV = 14`; Enter does the same;
     `IIII` calls `alert` and appends nothing; Reset clears input and rows; the input has
     `form-control`, the buttons `btn btn-primary` and `btn btn-secondary` (Clay's
     classes);
   - custom element: two elements evaluate independently (a row in one does not appear
     in the other); removing one unmounts it without an error.
4. **Build.** `gradle :client-extensions:roman-evaluator:build` from `work/` exits 0
   and produces the archive under `client-extensions/roman-evaluator/dist/` (for example
   `roman-evaluator.zip`). `unzip -l` of it is recorded. Its
   `*.client-extension-config.json` declares type `customElement`, element name
   `roman-evaluator`, and a `urls` entry that resolves to a JavaScript file present in
   the archive.
5. **Bundle hygiene**, over the built files in the archive:
   - no CSS framework copied in (no Bootstrap, no Clay CSS), and `grep -ci "cdn"` is 0;
   - **no second React or Clay:** the built JavaScript is one ES module whose only bare
     imports are `react`, `react-dom` and `@clayui/*` (listed from the file as evidence),
     and it contains none of their code: `grep -c "__SECRET_INTERNALS"` is 0 (a
     bundled React would contain it) and the file is a few KB, not hundreds (its size
     is recorded);
   - it does not import `react/jsx-runtime`.
6. **Checked by the operator after the run, not by a card:**
   1. `gradle :client-extensions:roman-evaluator:deploy` from `work/` places the
      archive in `.../bundles/osgi/client-extensions/`.
   2. With the portal running, `catalina.out` (or `bundles/logs/liferay.*.log`) shows
      the extension registered with no deploy error, and **Roman Evaluator** appears in
      the page editor under Client Extensions.
   3. On a page with two instances, evaluating `XIV` in one appends exactly one row
      `XIV = 14` there only; `IIII` shows an alert and appends nothing; Reset clears
      that instance only. The browser console shows no error from the widget.
   4. The widget looks like the portal's own forms (theme and Clay styling apply) and the
      rest of the page is unchanged.
