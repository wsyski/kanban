## Idea 1: Roman number evaluator - Liferay client extension (React + Clay components)

Build a Liferay **custom element client extension** — a widget an administrator can place
on any Liferay page — implementing a roman number evaluator in React with Liferay's
Clay components, styled by the CSS the portal already provides, deployable to the local Liferay Portal CE 7.4 GA129
bundle:

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
questions to local sources — the GA129 portal checkout
`/opt/projects/liferay/portal/arena-7.4.3.129-ga129/portal`, the scraped docs in
`~/.liferay-docs` when present, and `/home/playground/liferay/liferay-blade-samples` —
and requires citing what was read (`file:line` or the doc's `url:`). A card answers a
Liferay question from those sources, not from memory. The skill is read-only for every
card: never edit, copy or patch it.

Facts already established from those sources, for the researcher to confirm, not to
re-derive:

- GA129 supports the `customElement` client-extension type with the properties
  `urls`, `cssURLs`, `htmlElementName`, `friendlyURLMapping`, `portletCategoryName`,
  `instanceable` and `useESM`:
  `portal/modules/apps/client-extension/client-extension-type-api/src/main/java/com/liferay/client/extension/type/CustomElementCET.java`.
- The portal checkout ships demo workspaces in
  `/opt/projects/liferay/portal/arena-7.4.3.129-ga129/portal/workspaces/`. The primary
  reference is `liferay-sample-workspace/` there: its `settings.gradle`, `build.gradle`,
  Gradle wrapper and `gradle.properties` show the workspace shape, and its
  `client-extensions/liferay-sample-custom-element-{1..5}/` are working custom elements.
  `liferay-sample-custom-element-2` is a React one (`react`/`react-dom` `^18.2.0`,
  `type: customElement`, `useESM: true`, `assemble` from the build output into `static`),
  and `-4`/`-5` show ESM custom elements built without react-scripts. The workspace
  declares `liferay.workspace.product=dxp-2023.q4.5`; this board's workspace declares
  `portal-7.4-ga129` instead. Copy its structure, not its product line.
- A workspace already on the GA129 product line, for the product value and plugin
  resolution: `/home/playground/liferay/workspaces/blade-workspace`
  (`liferay.workspace.product=portal-7.4-ga129`, Gradle 8.5 wrapper,
  `liferay.workspace.node.package.manager=yarn`).
- Both reference trees are read-only. Copy files out of them into `work/`; never edit
  them in place.

### Reuse Liferay first

Reuse as much as possible from Liferay and write only what Liferay does not provide. At
every layer, the first question a card asks is "what does Liferay already ship for
this?", answered from the `liferay` skill's sources, before writing anything:

- **Build and packaging:** the Liferay workspace plugin, its client-extension build and
  its `deploy` task, plus the Gradle wrapper and workspace files copied from the portal's
  demo workspaces. No custom packaging scripts and no hand-assembled archives.
- **Extension shape:** `client-extension.yaml`, the `customElement` type and its
  properties, laid out as the portal's `liferay-sample-custom-element-*` samples lay them
  out. Copy and adapt a sample rather than inventing a structure.
- **UI:** Clay React components (`@clayui/*`) for every control. No hand-written
  equivalent of something Clay provides.
- **Styling:** the theme's Clay CSS already on the page. No bundled CSS framework.
- **Placement and configuration:** the portal's own widget handling (the page editor's
  Client Extensions category, `instanceable`, `friendlyURLMapping`). No custom portlet
  or OSGi module.

What remains hand-written is small: the roman-numeral parser, the component that wires
Clay controls to it, the custom-element registration, and their tests. When a card
writes something Liferay might already provide, its report names the source it checked
(`file:line` or doc `url:`) that shows Liferay does not.

### What to build

The board's work directory becomes a minimal **Liferay workspace** holding one client
extension:

    work/
      settings.gradle                  # applies com.liferay.workspace (as the GA129 workspace does)
      gradle.properties                # see below
      gradlew, gradlew.bat, gradle/wrapper/...   # Gradle 8.5 wrapper, copied, not downloaded by hand
      .gitignore                       # node_modules/, build/, dist/, .gradle/, bundles/
      client-extensions/roman-evaluator/
        client-extension.yaml
        package.json                   # react, react-dom, @clayui/* components; vite; vitest + testing libs
        vite.config.js
        src/roman.js                   # parsing module, no DOM, no React
        src/RomanEvaluator.jsx         # the React component
        src/index.js                   # defines the <roman-evaluator> custom element
        src/*.test.js(x)               # unit tests

`gradle.properties` carries at least:

    liferay.workspace.product=portal-7.4-ga129
    liferay.workspace.home.dir=/opt/projects/liferay/portal/arena-7.4.3.129-ga129/bundles
    liferay.workspace.node.package.manager=yarn

so `./gradlew deploy` in the workspace copies the built extension into that bundle's
`osgi/client-extensions/`.

`client-extension.yaml` declares one extension of `type: customElement`:

- extension id and `htmlElementName`: `roman-evaluator`
- `name`: `Roman Evaluator`
- `portletCategoryName: category.client-extensions`
- `friendlyURLMapping: roman-evaluator`
- `instanceable: true`
- `useESM: true`
- `urls` pointing at the one built JavaScript file, and no `cssURLs` unless the widget
  needs its own rules (see Styling)
- an `assemble` block copying the Vite output directory into `static`

### Behaviour

The widget shows:

- a text input for a roman number,
- two buttons in one row below the input: **Evaluate** and **Reset**,
- a result list below the buttons.

- **Evaluate** reads the input as a roman number and appends a row `ROMAN = ARABIC`
  (for example `XIV = 14`). Every evaluation adds a row; earlier rows stay.
- An invalid roman number shows an `alert()` with an error message and appends no row.
  Invalid means: empty input, characters outside `MDCLXVI` (case-insensitive), or a
  malformed numeral (for example `IIII`, `VX`, `IXX`). Subtractive notation (`IV`, `IX`,
  `XL`, `XC`, `CD`, `CM`) is handled; `MMMCMXCIX` (3999) is the valid upper bound.
- **Reset** clears the input and the result list.
- Enter in the input triggers Evaluate.
- Two instances of the widget on one page work independently.

### Technology

- **React** (`react` and `react-dom`) is bundled into the extension's own JavaScript.
  Nothing relies on a React the portal provides: no externals, no import-map sharing.
  The React version is free to choose; the plan records it, and the Clay component
  versions follow from it (below).
- `src/index.js` defines the custom element `roman-evaluator` with
  `customElements.define`, guarded so a second load does not throw. On connect it mounts
  the component into the element itself (light DOM, **no shadow root**, so the portal
  theme's CSS reaches it) with `createRoot`; on disconnect it unmounts.
- **Vite** builds one ES module file with a fixed name, for example `roman-evaluator.js`
  (no content hash, so `client-extension.yaml` names it exactly).
- **UI: reuse Clay components.** Build the widget from Liferay's Clay React components,
  not hand-written markup. For example:
  - `@clayui/form` (`ClayInput`, `ClayForm.Group`) for the input;
  - `@clayui/button` (`ClayButton` with `displayType="primary"` for Evaluate and
    `displayType="secondary"` for Reset, in a `ClayButton.Group` or one row);
  - `@clayui/list` (or plain Clay list markup) for the result rows;
  - Clay layout and spacing utilities for the rest.

  The GA129 portal itself uses `@clayui/*` 3.116–3.120 with React 16.12 (see the
  `package.json` files under `portal/modules/apps/frontend-js/` and
  `portal/modules/apps/frontend-taglib/`). That is a reference, not a requirement: pick
  `@clayui/*` versions whose `peerDependencies` accept the React version chosen.
- **Styling: reuse what Liferay provides.** Clay components render Clay markup, and
  every GA129 theme already ships Clay CSS (`@clayui/css` 3.x, built into the base theme
  `portal/modules/apps/frontend-theme/frontend-theme-unstyled`), so the widget is styled
  by the page it sits on. The extension bundles **no CSS**: no `@clayui/css` import, no
  Bootstrap, no CDN. A handful of widget-specific rules, if any are needed at all, go in
  one small CSS file listed in `cssURLs`, scoped under the `roman-evaluator` element
  selector so they cannot restyle the rest of the page. Bootstrap is **optional** and
  only a fallback: it may be used only if Clay demonstrably cannot style the widget, and
  then it has to be scoped to the element and served locally. Record that decision and
  its reason in the plan.
- **Tests:** Vitest. `roman.js` is unit-tested on its own. The component is tested with
  `@testing-library/react` in `jsdom`, with `window.alert` mocked.

Nothing else: no persistence, no server calls, no arabic-to-roman direction, no Liferay
Objects, no OSGi module, no theme changes.

### What the cards do and do not do

- Cards build and test inside the work directory only. They may download dependencies
  (Gradle plugins and wrapper distribution, npm/yarn packages); the first build needs
  network access.
- Cards do **not** deploy. `./gradlew deploy` writes into the portal bundle, which is
  outside the work directory, and the portal's state belongs to the operator. Cards do
  not start, stop or reconfigure the portal either.
- Toolchain the idea implies: Java 17, Node.js with yarn (classic), and `blade`
  (optional). The researcher records what is present. A missing runtime stops the lane at
  the researcher card with an install recommendation; nothing is installed.

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

- The work directory holds the workspace and the extension laid out as in "What to
  build": the Gradle wrapper, `settings.gradle`, `gradle.properties` with the three
  properties above, and the extension's `client-extension.yaml`, `package.json`, Vite
  config, sources and tests. `node_modules/`, `build/`, `dist/` and `.gradle/` are
  ignored, not deliverables.
- `yarn test` in `client-extensions/roman-evaluator/` passes, covering at least:
  `XIV` → 14 and `MMMCMXCIX` → 3999; rejection of `IIII`, `VX`, `IXX`, empty input and a
  character outside `MDCLXVI`; and, in the component test, Evaluate appending one row
  `XIV = 14`, `IIII` calling `alert` and appending nothing, and Reset clearing input and
  rows.
- `./gradlew :client-extensions:roman-evaluator:build` (run from `work/`) succeeds and
  produces the extension archive under `client-extensions/roman-evaluator/dist/`, for
  example `roman-evaluator.zip`. The archive contains a `*.client-extension-config.json`
  declaring type `customElement`, element name `roman-evaluator`, and a `urls` entry that
  matches a JavaScript file present in the archive. The card lists the archive's contents
  (`unzip -l`) as evidence.
- The built JavaScript and CSS bundle no CSS framework and reference no CDN: no
  Bootstrap or Clay CSS copied into the archive, and `grep -ci "cdn"` over the built files
  is 0. The widget is built from `@clayui/*` components, and the component test asserts
  the markup they render carries Clay's classes (`form-control` on the input,
  `btn btn-primary` and `btn btn-secondary` on the buttons).
- Checked by the operator after the run, not by a card:
  1. `./gradlew :client-extensions:roman-evaluator:deploy` from `work/` places the archive
     in `/opt/projects/liferay/portal/arena-7.4.3.129-ga129/bundles/osgi/client-extensions/`.
  2. With the portal running, `bundles/tomcat-9.0.90/logs/catalina.out` (or
     `bundles/logs/liferay.*.log`) shows the extension registered, with no deploy error,
     and **Roman Evaluator** appears in the page editor's widget list under Client
     Extensions.
  3. On a page with the widget, evaluating `XIV` appends exactly one row `XIV = 14`,
     `IIII` shows an alert and appends nothing, and Reset clears everything.
  4. The widget looks like the portal's own forms (theme and Clay styling apply) and the
     rest of the page is unchanged.
