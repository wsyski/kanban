# roman-evaluator-liferay-client-ext — a Liferay custom element client extension

One lane: a roman-number evaluator widget for Liferay Portal CE 7.4 GA129, built from
Liferay's Clay components (`@clayui/*`) on **the React and the Clay components the portal
already loads**, styled by the Clay CSS the portal's theme already provides (Bootstrap is
an optional fallback only). It is a `customElement` client extension built with webpack
as the portal's `liferay-sample-custom-element-5` is, inside a minimal Liferay workspace
in `work/`. The parsing module, the component and the custom element are unit-tested
with Vitest; the build produces the extension archive the portal loads.

**React and Clay come from Liferay, never bundled.** The page already has React (16.x on
GA129) and the Clay components for the portal's own UI, and shares them with client
extensions through its import map. The widget imports `react`, `react-dom` and
`@clayui/*` by bare specifier and declares them webpack externals, exactly as sample 5
does, so the page never loads a second React or a second Clay. The code is written to
the portal's React: React 16 API (`ReactDOM.render`), `React.createElement`, no JSX.

The target is the **Arena Liferay Portal**, Axiell's fork of Liferay Portal CE 7.4 GA129
(source `/opt/projects/liferay/portal/arena-7.4.3.129-ga129/portal`, bundle `../bundles`;
Axiell vault entity `Arena-Liferay-Portal`). The cards take the extension's shape from
the portal's `workspaces/liferay-sample-workspace`, chiefly `liferay-sample-custom-element-5`, and the
workspace root (`settings.gradle`, plugin 12.1.0) from
`/home/playground/liferay/workspaces/blade-workspace` — never its `gradle.properties`,
which holds repository credentials.

The idea's rule is **reuse Liferay first**: the workspace build and deploy, the sample
extension structure, Clay components, the theme's CSS and the portal's widget handling
all come from Liferay, and so do React and Clay at runtime. Only the roman parser, the
component wiring, the externals list in the copied webpack config and their tests are
written by hand.

Liferay decisions on this board are grounded in the hub's `liferay-expert` skill
(automatic in the researcher and coder profiles). The idea tells every card to load it
first and to cite sources rather than answer from memory: the GA129 portal checkout, the local docs corpus
(`~/.liferay-docs`) and the blade samples.

**Toolchain: the workstation's own.** Java 17, `gradle`, `node` and `yarn` (classic) are
used as installed on the workstation. The workspace has no Gradle wrapper, and the build
downloads no JDK, Gradle distribution or Node (the Liferay Node plugin's download is
switched off in `work/build.gradle`). Only Gradle plugins and npm/yarn packages are
fetched, so the first run needs network access. The researcher records `java -version`,
`gradle --version`, `node --version` and `yarn --version`; a missing or too-old tool
stops the lane at the researcher card with an install recommendation. Nothing is
installed.

Cards build and test only. **Deploying is the operator's step**, because it writes into
the portal bundle outside the work directory. The board is auto-gated, so no card waits
on a person. The in-portal check happens after the run, before the staged work is
committed; the driver commits nothing.

## Running it

    driver/create-board.sh --board boards/roman-evaluator-liferay-client-ext
    hermes kanban boards switch roman-evaluator-liferay-client-ext   # create files the board
                                                                    # but leaves it NON-current
    driver/start-board.sh --slug roman-evaluator-liferay-client-ext  # serve; then drop the
                                                                    # seeded Triage card in Todo
    driver/run-audit.py --runs boards/roman-evaluator-liferay-client-ext/runs   # 0/0 is the pass

Serving releases nothing. The go signal is the seeded Triage card dropped in the **Todo**
column; `driver/arm.sh roman-evaluator-liferay-client-ext 1` files the same thing from a
shell. A drop in **Ready** is the one that fails: `kanban.default_assignee` is `coder`,
so the dispatcher claims and spawns the card before the driver can read it as the idea.

## After the run: deploy and check

From the board's work directory, with the workstation's `gradle`:

    cd boards/roman-evaluator-liferay-client-ext/work
    gradle :client-extensions:roman-evaluator:deploy
    ls /opt/projects/liferay/portal/arena-7.4.3.129-ga129/bundles/osgi/client-extensions/

Start the portal the usual way for that bundle, then:

1. The Tomcat log shows the `roman-evaluator` client extension registered, with no
   deploy error.
2. In the page editor, **Roman Evaluator** is listed under Client Extensions. Add it to a
   page twice.
3. In one instance: `XIV` → one row `XIV = 14` there only; `IIII` → an alert and no row;
   Reset clears that instance only. The browser console shows no error from the widget.
4. The widget looks like the portal's own forms (theme/Clay styling) and the rest of the
   page looks unchanged.

To undeploy, delete the archive from `osgi/client-extensions/`.

`driver/reset.sh --board boards/roman-evaluator-liferay-client-ext` archives the cards and
unstages what a dead run left in the index. The work directory is never cleared, so a
re-run finds the last run's workspace and treats it as the previous version to improve;
delete it by hand for a blank start.
