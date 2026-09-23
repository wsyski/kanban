# roman-evaluator-liferay-client-ext — a Liferay custom element client extension

One lane: a roman-number evaluator widget for Liferay Portal CE 7.4 GA129, written in
React from Liferay's Clay components (`@clayui/*`), styled by the Clay CSS the portal's
theme already provides (Bootstrap is an optional fallback only), built as a `customElement` client extension inside
a minimal Liferay workspace in `work/`. The parsing module and the component are
unit-tested; the build produces the extension archive the portal loads.

The target is the **Arena Liferay Portal**, Axiell's fork of Liferay Portal CE 7.4 GA129
(source `/opt/projects/liferay/portal/arena-7.4.3.129-ga129/portal`, bundle `../bundles`;
Axiell vault entity `Arena-Liferay-Portal`). Its demo workspaces in `portal/workspaces/`,
chiefly `liferay-sample-workspace` with its React custom element samples, are the
reference the cards copy the workspace shape from.

The idea's rule is **reuse Liferay first**: the workspace build and deploy, the sample
extension structure, Clay components, the theme's CSS and the portal's widget handling
all come from Liferay. Only the roman parser, the component wiring and their tests are
written by hand.

Liferay decisions on this board are grounded in the hub's manual `liferay` skill
(`/home/wos/.agents/manual-skills/liferay/SKILL.md`). The idea tells every card to read
it by path and to cite sources rather than answer from memory: the GA129 portal
checkout, the local docs corpus (`~/.liferay-docs`) and the blade samples.

Toolchain the idea implies: Java 17, Node.js with yarn (classic), network access for the
first Gradle and yarn run. The researcher records what is present; a missing runtime
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

From the board's work directory:

    cd boards/roman-evaluator-liferay-client-ext/work
    ./gradlew :client-extensions:roman-evaluator:deploy
    ls /opt/projects/liferay/portal/arena-7.4.3.129-ga129/bundles/osgi/client-extensions/

Start the portal the usual way for that bundle, then:

1. The Tomcat log shows the `roman-evaluator` client extension registered.
2. In the page editor, **Roman Evaluator** is listed under Client Extensions. Add it to a
   page (twice, to check that instances are independent).
3. `XIV` → one row `XIV = 14`; `IIII` → an alert and no row; Reset clears everything.
4. The widget looks like the portal's own forms (theme/Clay styling) and the rest of the
   page looks unchanged.

To undeploy, delete the archive from `osgi/client-extensions/`.

`driver/reset.sh --board boards/roman-evaluator-liferay-client-ext` archives the cards and
unstages what a dead run left in the index. The work directory is never cleared, so a
re-run finds the last run's workspace and treats it as the previous version to improve;
delete it by hand for a blank start.
