"""template/probe.py — the one-call probe the plan and plan-review cards run.

The Liferay board's plan loop (2026-09-26/28) rejected a planner three rounds running
for values it was forbidden to measure, and passed, in the next run, a plan whose build
could never succeed because its reviewer read instead of ran. These tests pin what the
probe promises the cards: the plan's own text in, a log out, and nothing it runs can
touch the work directory a human receives.
"""
import os
import re
import signal
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
import probe


def _plan(w, r):
    return f"""# Plan
### Task 1: module
- [ ] **Step 1 [C]: Write the module**

```js file=src/mod.js
export const x = 1;
```

```sh file={r}/scratch/<this card's id>/check.sh
test -f src/mod.js && echo MODULE-PRESENT
```

Run: `cd {w} && ls src`

- [ ] **Step 2 [TW]: Write the test** (prose naming Task 1 Step 1 [C] changes nothing)

```js file=src/mod.test.js
import {{ x }} from './mod.js';
```

```run
bash {r}/scratch/<this card's id>/check.sh
touch made-by-a-command.txt
```

- [ ] **Step 3 [C]: Package**

Run: `gradle deploy`
Run: `unzip -l <archive>`
Run: `ls /srv/target-root`
"""


_HEADER = ("# P\n\n**Goal:** g\n\n**Architecture:** a\n\n**Tech Stack:** t\n\n"
           "**Spec:** the raw idea\n\n## Global Constraints\n\n- none\n\n")


def _clean(plan):
    """A plan the linter passes: the header, and a Tick sentence under every step — for
    tests about something else."""
    return _HEADER + re.sub(r"^(- \[ \] \*\*Step[^\n]*)$", r"\1\n\nTick: on its output.",
                            plan, flags=re.M)


def _setup(tmp_path):
    w, r = tmp_path / "work", tmp_path / "runs"
    (w / "src").mkdir(parents=True)
    (w / "src" / "keep.txt").write_text("already here\n")
    (w / "node_modules" / "x").mkdir(parents=True)
    (w / "node_modules" / "x" / "a.js").write_text("dependency\n")
    r.mkdir()
    plan = tmp_path / "plan.md"
    plan.write_text(_plan(w, r))
    out = r / "scratch" / "t_rev" / "probe"
    return w, r, plan, out


def _run(w, r, plan, out, *extra):
    return probe.main(["--plan", str(plan), "--out", str(out), "--workdir", str(w),
                       "--runs", str(r), "--targets", "/srv/target-root", *extra])


def test_the_plan_is_read_by_its_conventions(tmp_path):
    w, r, plan, _ = _setup(tmp_path)
    files, commands = probe.parse_plan(plan.read_text())
    assert [(f["path"].split("/")[-1], f["tag"]) for f in files] == [
        ("mod.js", "C"), ("check.sh", "C"), ("mod.test.js", "TW")]
    assert files[1]["path"].endswith("<this card's id>/check.sh"), "a path with spaces survives"
    assert [c["tag"] for c in commands] == ["C", "TW", "TW", "C", "C", "C"]
    assert commands[0]["where"] == "Task 1 Step 1"


def test_the_probe_builds_and_runs_in_its_own_tree_only(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    assert _run(w, r, plan, out) == 1, "the `<archive>` placeholder is a defect of the plan"
    log = (out / "probe-log.md").read_text()
    tree = out / "tree"
    assert (tree / "src" / "mod.js").is_file() and (tree / "src" / "keep.txt").is_file()
    assert not (tree / "node_modules").exists(), "dependency directories are not copied"
    assert (tree / "made-by-a-command.txt").is_file()
    assert sorted(os.listdir(w)) == ["node_modules", "src"] and \
        sorted(os.listdir(w / "src")) == ["keep.txt"], "the work directory is untouched"
    assert "MODULE-PRESENT" in log, "a card-scratch helper is written and runs"
    assert "writes outside the work directory (deploy" in log
    assert "placeholder <archive>" in log
    assert "names the declared target root /srv/target-root" in log
    assert f"plan-sha256: {probe.hashlib.sha256(plan.read_bytes()).hexdigest()}" in log
    assert probe.recorded_plan_sha(str(out / "probe-log.md")) == \
        probe.hashlib.sha256(plan.read_bytes()).hexdigest()


def test_the_without_pass_leaves_out_that_cards_product_but_not_its_helpers(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    _run(w, r, plan, out, "--also-without", "C")
    tree = out / "tree-without-C"
    assert not (tree / "src" / "mod.js").exists()
    assert (tree / "src" / "mod.test.js").is_file()
    log = (out / "probe-log.md").read_text()
    assert "## Pass: without-C" in log
    section = log.split("## Pass: without-C", 1)[1]
    assert "Step 3" not in section, "the without pass runs only the remaining tags' steps"


def test_a_failing_command_is_exit_1_and_an_out_dir_inside_the_workdir_is_refused(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    plan.write_text("- [ ] **Step 1 [C]: fail**\n\nRun: `false`\n")
    assert _run(w, r, plan, out) == 1
    assert _run(w, r, plan, w / "probe") == 2


def test_a_file_outside_the_work_directory_is_not_written(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    plan.write_text("- [ ] **Step 1 [C]: x**\n\n```txt file=/etc/escape.txt\nno\n```\n"
                    "\n```txt file=../escape.txt\nno\n```\n")
    _run(w, r, plan, out, "--files-only")
    log = (out / "probe-log.md").read_text()
    assert log.count("NOT WRITTEN") == 2
    assert not (tmp_path / "escape.txt").exists()


def _log(out):
    return probe.read_log(str(out / "probe-log.md"))


def test_the_log_records_mode_start_and_the_full_pass_tally(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    _run(w, r, plan, out)
    info = _log(out)
    assert info["complete"] is True and info["mode"] == "full"
    assert info["started"] > 0
    assert (info["commands"], info["ran"], info["failed"], info["skipped"]) == (6, 3, 0, 3)
    assert info["skipped-defect"] == 1 and info["files-failed"] == 0 and info["files"] == 3
    assert info["out"] == str(out)
    _run(w, r, plan, out, "--files-only")
    info = _log(out)
    assert info["mode"] == "files-only" and info.get("ran", 0) == 0


def test_a_cut_short_probe_says_it_is_incomplete(tmp_path, monkeypatch):
    w, r, plan, out = _setup(tmp_path)
    seen = []

    def boom(*a, **k):
        seen.append(_log(out))
        raise KeyboardInterrupt

    monkeypatch.setattr(probe, "_run_one", boom)
    try:
        _run(w, r, plan, out)
    except KeyboardInterrupt:
        pass
    assert seen and seen[0]["complete"] is False
    assert _log(out)["complete"] is False, "the log on disk still says the probe did not finish"


def test_the_sha_is_of_the_plan_bytes_crlf_included(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    plan.write_bytes(plan.read_text().replace("\n", "\r\n").encode())
    _run(w, r, plan, out, "--files-only")
    assert _log(out)["sha"] == probe.hashlib.sha256(plan.read_bytes()).hexdigest()
    assert (out / "tree" / "src" / "mod.js").is_file(), "a CRLF plan parses the same"


def test_a_patch_applies_inside_the_tree_even_under_a_git_repository(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    w, r, plan, out = _setup(tmp_path)
    plan.write_text(_clean("- [ ] **Step 1 [C]: patch**\n\n"
                    "```diff patch=src/keep.txt\n"
                    "diff --git a/src/keep.txt b/src/keep.txt\n"
                    "--- a/src/keep.txt\n+++ b/src/keep.txt\n"
                    "@@ -1 +1 @@\n-already here\n+patched\n```\n"))
    assert _run(w, r, plan, out, "--files-only") == 0
    assert (out / "tree" / "src" / "keep.txt").read_text() == "patched\n"
    assert (w / "src" / "keep.txt").read_text() == "already here\n"
    assert "patch applied" in (out / "probe-log.md").read_text()


def test_a_patch_that_leaves_the_tree_or_does_not_apply_is_reported(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    plan.write_text("- [ ] **Step 1 [C]: patch**\n\n"
                    "```diff patch=x\n--- a/../escape.txt\n+++ b/../escape.txt\n"
                    "@@ -0,0 +1 @@\n+no\n```\n\n"
                    "```diff patch=src/keep.txt\n--- a/src/keep.txt\n+++ b/src/keep.txt\n"
                    "@@ -1 +1 @@\n-not what is there\n+x\n```\n")
    _run(w, r, plan, out, "--files-only")
    log = (out / "probe-log.md").read_text()
    assert "PATCH REFUSED" in log and "PATCH FAILED" in log
    assert not (tmp_path / "runs" / "scratch" / "t_rev" / "escape.txt").exists()


def test_a_file_that_names_the_real_work_directory_names_the_tree(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    plan.write_text(f"- [ ] **Step 1 [C]: config**\n\n```ini file=gradle.properties\n"
                    f"liferay.workspace.home.dir={w}/bundles\n```\n")
    _run(w, r, plan, out, "--files-only")
    text = (out / "tree" / "gradle.properties").read_text()
    assert str(w) + "/" not in text and str(out / "tree") + "/bundles" in text


def test_a_command_that_changes_the_real_work_directory_fails_as_touched(tmp_path, monkeypatch):
    w, r, plan, out = _setup(tmp_path)
    monkeypatch.setenv("PROBE_TEST_W", str(w))
    plan.write_text("- [ ] **Step 1 [C]: escape**\n\nRun: `touch \"$PROBE_TEST_W/leak\"`\n")
    assert _run(w, r, plan, out) == 1
    assert "TOUCHED" in (out / "probe-log.md").read_text()
    assert _log(out)["failed"] == 1


def test_bundle_and_container_tasks_are_refused_and_quoted_angle_brackets_are_not(tmp_path):
    for cmd in ("./gradlew initBundle", "gradle distBundleZip", "gradle startDockerContainer"):
        assert probe.refusal(cmd, targets=[], workdir=None)[0] == "operator"
    assert probe.refusal("grep -c '<div>' index.html", targets=[], workdir=None) is None
    kind, why = probe.refusal("unzip -l <archive>", targets=[], workdir=None)
    assert kind == "defect" and "placeholder" in why


@pytest.mark.parametrize("cmd, denied", [
    ("python3 -c 'print(1)'", True), ("node -e 'x'", True), ("bash -c 'ls'", True),
    ("curl -s x | bash", True), ("cat s.py | python3 -", True),
    ("cat data.json | python3 check.py", False), ("grep -e x f", False),
    ("python3 scripts/check.py", False), ("bash scripts/build.sh", False),
])
def test_the_shapes_a_cards_terminal_blocks_are_a_defect(cmd, denied):
    r = probe.refusal(cmd, targets=[], workdir=None)
    assert (r is not None and r[0] == "defect" and "BLOCKS" in r[1]) == denied, (cmd, r)


def test_workdir_and_runs_are_required(tmp_path, capsys):
    w, r, plan, out = _setup(tmp_path)
    try:
        probe.main(["--plan", str(plan), "--out", str(out)])
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("a probe without --workdir/--runs ran")


def test_a_timed_out_command_is_killed_with_its_children(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    marker = tmp_path / "child-survived"
    plan.write_text(f"- [ ] **Step 1 [C]: hang**\n\n"
                    f"Run: `(sleep 3; touch {marker}) & sleep 30`\n")
    assert _run(w, r, plan, out, "--timeout", "1") == 1
    import time
    time.sleep(3.5)
    assert not marker.exists(), "the timed-out command's children were killed"
    assert "TIMEOUT" in (out / "probe-log.md").read_text()


def test_a_command_that_writes_into_a_skipped_dir_or_restores_a_file_is_touched(tmp_path, monkeypatch):
    w, r, plan, out = _setup(tmp_path)
    monkeypatch.setenv("PROBE_TEST_W", str(w))
    plan.write_text("- [ ] **Step 1 [C]: sneaky**\n\n"
                    "Run: `touch \"$PROBE_TEST_W/node_modules/new\"`\n"
                    "Run: `cp -p \"$PROBE_TEST_W/src/keep.txt\" ../bak && echo x > "
                    "\"$PROBE_TEST_W/src/keep.txt\" && cp -p ../bak \"$PROBE_TEST_W/src/keep.txt\"`\n")
    assert _run(w, r, plan, out) == 1
    log = (out / "probe-log.md").read_text()
    assert log.count("TOUCHED") == 2
    assert "node_modules/new" in log and "src/keep.txt" in log, "the log names what changed"


def test_every_spelling_of_the_work_directory_is_the_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    w, r, plan, out = _setup(tmp_path)
    tree = str(out / "tree")
    for spelled in ("~/work/src", "$HOME/work/src", "${HOME}/work/src", f"{w}/src"):
        assert probe.rewrite(f"ls {spelled}", workdir=str(w), tree=tree, runs=str(r),
                             scratch="/s") == f"ls {tree}/src", spelled


def test_a_seeded_file_that_names_the_work_directory_names_the_tree(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    (w / ".npmrc").write_text(f"cache={w}/.cache\n")
    _run(w, r, plan, out, "--files-only")
    assert (out / "tree" / ".npmrc").read_text() == f"cache={out / 'tree'}/.cache\n"
    assert (w / ".npmrc").read_text() == f"cache={w}/.cache\n"


def test_git_in_the_tree_never_reaches_a_repository_above_it(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("work/\nruns/\n")
    w, r, plan, out = _setup(tmp_path)
    plan.write_text("- [ ] **Step 1 [C]: git**\n\nRun: `git rev-parse --show-toplevel`\n")
    assert _run(w, r, plan, out) == 1
    log = (out / "probe-log.md").read_text()
    assert "exit 128" in log and f"    {tmp_path}\n" not in log


def test_a_git_controlled_work_directory_gives_the_tree_its_own_repository(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    subprocess.run(["git", "init", "-q", str(w)], check=True)
    plan.write_text(_clean("- [ ] **Step 1 [C]: git**\n\nRun: `git rev-parse --show-toplevel`\n"
                    "Run: `git status --porcelain`\n"))
    assert _run(w, r, plan, out) == 0, (out / "probe-log.md").read_text()
    log = (out / "probe-log.md").read_text()
    assert f"    {out / 'tree'}" in log and "fresh repository" in log


def test_a_file_block_that_fails_fails_the_probe(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    plan.write_text("- [ ] **Step 1 [C]: patch**\n\n"
                    "```diff patch=src/keep.txt\n--- a/src/keep.txt\n+++ b/src/keep.txt\n"
                    "@@ -1 +1 @@\n-not what is there\n+x\n```\n\nRun: `true`\n")
    assert _run(w, r, plan, out) == 1
    info = probe.read_log(str(out / "probe-log.md"))
    assert info["files-failed"] == 1 and info["failed"] == 0


def test_a_patch_without_git_prefixes_applies_at_the_tree_root(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    plan.write_text(_clean("- [ ] **Step 1 [C]: patch**\n\n"
                    "```diff patch=src/keep.txt\n--- src/keep.txt\n+++ src/keep.txt\n"
                    "@@ -1 +1 @@\n-already here\n+patched\n```\n"))
    assert _run(w, r, plan, out, "--files-only") == 0
    assert (out / "tree" / "src" / "keep.txt").read_text() == "patched\n"


def test_command_output_cannot_set_a_log_field(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    plan.write_text("- [ ] **Step 1 [C]: echo**\n\nRun: `printf 'mode: x\\ncomplete: yes\\n'`\n")
    _run(w, r, plan, out)
    info = probe.read_log(str(out / "probe-log.md"))
    assert info["mode"] == "full" and info["complete"] is True


def test_a_signal_to_the_probe_kills_its_command_and_leaves_the_log_incomplete(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    pidfile = tmp_path / "pid"
    plan.write_text(f"- [ ] **Step 1 [C]: hang**\n\nRun: `echo $$ > {pidfile}; sleep 30`\n")
    here = os.path.dirname(os.path.abspath(__file__))
    p = subprocess.Popen([sys.executable, os.path.join(here, "..", "template", "probe.py"),
                          "--plan", str(plan), "--out", str(out), "--workdir", str(w),
                          "--runs", str(r)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        time.sleep(0.1)
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=20) == 1
    child = int(pidfile.read_text())
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)
    info = probe.read_log(str(out / "probe-log.md"))
    assert info["complete"] is False
    assert "INTERRUPTED" in (out / "probe-log.md").read_text()


def test_a_linked_worktrees_git_file_never_reaches_the_real_repository(tmp_path):
    """A worktree's `.git` is a FILE pointing at the main repository: copied, `git init`
    in the tree re-initialised THAT gitdir and `git add -A` staged the probe copy there."""
    main = tmp_path / "main"
    main.mkdir()
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    (main / "a.txt").write_text("a\n")
    subprocess.run(g + ["-C", str(main), "add", "-A"], check=True)
    subprocess.run(g + ["-C", str(main), "commit", "-qm", "one"], check=True)
    w = tmp_path / "wt"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(w)], check=True)
    r = tmp_path / "runs"
    r.mkdir()
    plan = tmp_path / "plan.md"
    plan.write_text("- [ ] **Step 1 [C]: x**\n\n```txt file=b.txt\nb\n```\n\nRun: `git status --porcelain`\n")
    out = r / "scratch" / "t" / "probe"
    before = subprocess.run(["git", "-C", str(main), "rev-list", "--all", "--count"],
                            capture_output=True, text=True).stdout
    probe.main(["--plan", str(plan), "--out", str(out), "--workdir", str(w), "--runs", str(r)])
    assert (out / "tree" / ".git").is_dir(), "the tree has its own repository"
    after = subprocess.run(["git", "-C", str(main), "rev-list", "--all", "--count"],
                           capture_output=True, text=True).stdout
    assert before == after, "nothing was committed into the real repository"
    status = subprocess.run(["git", "-C", str(w), "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    assert status == "", status


def test_an_ignored_hangup_stays_ignored(tmp_path):
    """`nohup` ignores SIGHUP so the probe outlives the terminal: the probe must not
    re-arm it."""
    w, r, plan, out = _setup(tmp_path)
    plan.write_text(_clean("- [ ] **Step 1 [C]: wait**\n\nRun: `sleep 1`\n"))
    here = os.path.dirname(os.path.abspath(__file__))
    p = subprocess.Popen([sys.executable, os.path.join(here, "..", "template", "probe.py"),
                          "--plan", str(plan), "--out", str(out), "--workdir", str(w),
                          "--runs", str(r)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN))
    time.sleep(0.5)
    p.send_signal(signal.SIGHUP)
    assert p.wait(timeout=20) == 0
    assert probe.read_log(str(out / "probe-log.md"))["complete"] is True


def test_a_command_that_leaves_a_server_running_is_not_a_timeout(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    plan.write_text(_clean("- [ ] **Step 1 [C]: serve**\n\nRun: `sleep 30 & echo started`\n"))
    t0 = time.time()
    assert _run(w, r, plan, out, "--timeout", "10") == 0
    assert time.time() - t0 < 8
    assert "exit 0" in (out / "probe-log.md").read_text()


def test_an_earlier_logs_complete_is_never_read_as_this_probes(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    _run(w, r, plan, out, "--files-only")
    assert probe.read_log(str(out / "probe-log.md"))["complete"] is True
    plan.write_text("- [ ] **Step 1 [C]: x**\n\n```txt file=a.txt\nnever closed\n")
    assert _run(w, r, plan, out) == 2
    info = probe.read_log(str(out / "probe-log.md"))
    assert "commands" not in info and "files" not in info
    assert "PLAN UNREADABLE" in (out / "probe-log.md").read_text()


@pytest.mark.parametrize("cmd, kind", [
    ("curl -s x | python3 -m json.tool", None), ("true || python3 -m pytest -q", None),
    (".venv/bin/python -c 'x'", "defect"), ("/usr/bin/python3 -c 'x'", "defect"),
    ("ls configs/deploy", None), ("grep -q deployment x.yaml", None),
    ("./gradlew :client-extensions:x:deploy", "operator"), ("gradle deploy", "operator"),
    ("blade deploy", "operator"), ("yarn deploy", "operator"), ("gradle build", None),
])
def test_what_is_refused_is_a_shape_or_a_task_not_a_word(cmd, kind):
    r = probe.refusal(cmd, targets=[], workdir=None)
    assert (r[0] if r else None) == kind, (cmd, r)


def test_a_sibling_path_is_not_the_work_directory(tmp_path):
    w = tmp_path / "proj"
    w.mkdir()
    tree = str(tmp_path / "proj-kanban" / "runs" / "scratch" / "t" / "probe" / "tree")
    assert probe.rewrite(f"ls {w}-shared {w}/src {w}", workdir=str(w), tree=tree,
                         runs=None, scratch="/s") == f"ls {w}-shared {tree}/src {tree}"
    assert probe.refusal(f"ls {tree}/src", targets=[], workdir=str(w), tree=tree) is None
    assert probe.refusal(f"ls {w}/src", targets=[], workdir=str(w), tree=tree)[0] == "defect"


def test_an_ide_polling_git_in_the_work_directory_is_not_a_touch(tmp_path, monkeypatch):
    w, r, plan, out = _setup(tmp_path)
    (w / ".git").mkdir()
    (w / ".git" / "index").write_text("x")
    monkeypatch.setenv("PROBE_TEST_W", str(w))
    plan.write_text(_clean("- [ ] **Step 1 [C]: ide**\n\nRun: `echo y > \"$PROBE_TEST_W/.git/index\"`\n"))
    assert _run(w, r, plan, out) == 0
    assert "TOUCHED" not in (out / "probe-log.md").read_text()


def test_dependencies_stay_for_a_reviewer_and_go_on_request(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    plan.write_text("- [ ] **Step 1 [C]: deps**\n\nRun: `mkdir -p node_modules/x && touch node_modules/x/i.js`\n")
    _run(w, r, plan, out)
    assert (out / "tree" / "node_modules" / "x" / "i.js").exists()
    _run(w, r, plan, out, "--prune-deps")
    assert not (out / "tree" / "node_modules").exists()


def test_an_untagged_step_heading_is_a_defect_and_never_inherits_a_tag(tmp_path):
    """is-even, 2026-09-30: five `**Step n: …**` headings with no tag. The probe ran every
    command in the full pass, nothing in the without-C pass, and exited 0 — the plan
    review found it and cost a round."""
    w, r, plan, out = _setup(tmp_path)
    plan.write_text("### Task 1: x\n- [ ] **Step 1 [C]: tagged**\n\nRun: `true`\n\n"
                    "Step 3 runs later — prose, not a heading.\n\nRun: `echo still-C`\n\n"
                    "- [ ] **Step 2: untagged**\n\n```txt file=a.txt\na\n```\n\nRun: `echo loose`\n")
    files, commands = probe.parse_plan(plan.read_text())
    assert [c["tag"] for c in commands] == ["C", "C", None], "a bare prose line is not a heading"
    assert files[0]["tag"] is None and files[0]["where"] == "Task 1 Step 2"
    assert _run(w, r, plan, out, "--also-without", "C") == 1
    log = (out / "probe-log.md").read_text()
    assert "UNTAGGED: 1 file block(s) and 1 Run command(s)" in log
    assert "- Task 1 Step 2: file a.txt" in log and "- Task 1 Step 2: Run: echo loose" in log
    assert "NO COMMAND in this pass" in log.split("## Pass: without-C", 1)[1]
    assert _log(out)["untagged"] == 2


def test_a_without_pass_with_nothing_to_run_is_named_but_not_a_failure(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    plan.write_text(_clean("- [ ] **Step 1 [C]: only code**\n\nRun: `true`\n"))
    assert _run(w, r, plan, out, "--also-without", "C") == 0
    log = (out / "probe-log.md").read_text()
    assert "UNTAGGED" not in log and "NO COMMAND in this pass" in log
    assert _log(out)["untagged"] == 0


def _spec(tmp_path):
    spec = tmp_path / "refined.md"
    spec.write_text("# refined\n\n## Verification recipe\n- SC1: `pytest`\n"
                    "- SC3: `manual at Gc` — a person looks\n\n## Success criteria\n"
                    "- SC1: the four cases pass\n- SC2: nothing else is left\n"
                    "- SC3: it looks right\n\n## Prior art\nnone\n")
    return spec


def test_the_lint_finds_what_a_rule_can_decide(tmp_path):
    """is-even, 2026-09-30: both round-1 findings (no tags, no tick sentences) were
    rule-decidable, and the round cost 13.6 minutes on the local model."""
    w, r, plan, out = _setup(tmp_path)
    spec = _spec(tmp_path)
    plan.write_text(
        f"# X Implementation Plan\n\n> **For agentic workers:** use a skill\n\n**Goal:** g\n\n"
        f"**Architecture:** a\n\n**Tech Stack:** t\n\n**Spec:** `{spec}`\n\n"
        "### Task 1: tests\n- [ ] **Step 1 [TW]: tests (covers SC1)**\n\n"
        "```python file=test_x.py\nx = 1\n```\n\n```text\nTick: inside a fence is not one\n```\n\n"
        "### Task 2: code\n- [ ] **Step 1 [C]: code**\n\n```python file=./test_x.py\nx = 2\n```\n\n"
        "Run: `git -C . commit -m x`\n\nTick: on its output.\n\n"
        "- [ ] **Step 2 [C]: board**\n\nRun: `hermes kanban --board b list`\n\n"
        "**Tick:** on its output.\n\n## Execution Handoff\n\nnone\n")
    lint = probe.lint_plan(plan.read_text(), *probe.parse_plan(plan.read_text()))
    got = {(item, where) for item, where, _ in lint}
    assert got == {(1, "header"), (2, "SC2"), (4, "Task 1 Step 1"),
                   (4, "Task 1 Step 1 / Task 2 Step 1"), (6, "Task 2 Step 1"),
                   (6, "Task 2 Step 2")}, lint
    msgs = " ".join(m for _, _, m in lint)
    assert "Global Constraints" in msgs and "agentic" in msgs and "Execution Handoff" in msgs
    assert "SC3" not in {w for _, w, _ in lint}, "manual at Gc is covered"
    assert _run(w, r, plan, out) == 1
    log = (out / "probe-log.md").read_text()
    assert f"LINT: {len(lint)} defect(s)" in log and "- item 6: Task 2 Step 1: `git -C . commit`" in log
    assert _log(out)["lint"] == len(lint)


def test_a_complete_plan_lints_clean_and_a_missing_spec_is_named(tmp_path):
    w, r, plan, out = _setup(tmp_path)
    spec = _spec(tmp_path)
    plan.write_text(f"# X\n\n**Goal:** g\n**Architecture:** a\n**Tech Stack:** t\n"
                    f"**Spec:** {spec}\n\n## Global Constraints\n- none\n\n"
                    "### Task 1: x\n- [ ] **Step 1 [C]: run (covers SC1, SC2)**\n\n"
                    "Run: `true`\n\nExpected: exit 0. Tick: on the exit status.\n")
    assert probe.lint_plan(plan.read_text(), *probe.parse_plan(plan.read_text())) == []
    assert _run(w, r, plan, out) == 0
    assert "LINT: clean" in (out / "probe-log.md").read_text()
    assert probe.lint_plan(plan.read_text().replace(str(spec), str(tmp_path / "gone.md")),
                           [], []) == [(1, "header", f"the Spec line names "
                                                     f"{tmp_path / 'gone.md'}, which does not exist")]


def test_what_the_run_commands_leave_unnamed_is_a_lint_defect(tmp_path):
    """Liferay, 2026-09-30: the plan review rejected a stray `sc5/` fixture and two build
    by-products Global Constraints never named — all three in the planner's own probe
    tree. A listed by-product, a file block and the seeded work directory are not."""
    w, r, plan, out = _setup(tmp_path)
    plan.write_text(_clean(
        "- [ ] **Step 1 [C]: build**\n\n```txt file=src/app.txt\napp\n```\n\n"
        "Run: `mkdir -p dist cache/deep sc5 && touch dist/app.zip cache/deep/x yarn.lock src/extra.txt`\n")
        .replace("## Global Constraints\n\n- none\n",
                 "## Global Constraints\n\n- By-products: `work/dist/`, `cache/`.\n"))
    assert _run(w, r, plan, out) == 1
    log = (out / "probe-log.md").read_text()
    assert "LINT (after the full pass): 3 path(s)" in log, log
    for rel in ("sc5/", "yarn.lock", "src/extra.txt"):
        assert f"- item 7: {rel}: `{rel}` is created by a Run command" in log
    for rel in ("dist", "cache", "src/app.txt", "src/keep.txt", "docs"):
        assert f"- item 7: {rel}" not in log
    assert _log(out)["lint"] == 3
    assert probe.named_byproducts("## Global Constraints\n- `work/a/`, `/w/b`, `../c`, `d/*.log`\n",
                                  "/w") == {"a", "b", "d/*.log"}


def test_a_tick_naming_another_cards_step_is_a_defect():
    """Each card runs only its own steps' Run commands, so a Tick that hands the box to
    another card's step can never be made.

    A [TW] step's tick is the review's re-derivation of the predicted FAIL, never a
    command another card runs; a [C] step cannot tick on a [TI] step either, because TI
    runs on its own card.
    """
    plan = (_HEADER +
            "### Task 1: module\n"
            "- [ ] **Step 1 [TW]: Predict the failure**\n\n"
            "State what the suite will say when the module is absent.\n\n"
            "Tick: on the Step 2 [C] command printing the file names and exiting 0.\n\n"
            "- [ ] **Step 2 [C]: Write the module**\n\n"
            "Run: `ls mod.js`\n\n"
            "Expected: `mod.js`\n\n"
            "Tick: on the `mod.js` line the command prints.\n")

    defects = [m for (item, _where, m) in probe.lint_plan(plan, [], []) if item == 4]

    assert any("Step 2 [C]" in m and "[TW]" in m for m in defects), defects


def test_a_c_step_ticking_on_a_ti_step_is_a_defect():
    plan = (_HEADER +
            "### Task 1: end to end\n"
            "- [ ] **Step 1 [C]: Write the page**\n\n"
            "Run: `ls page.js`\n\n"
            "Expected: `page.js`\n\n"
            "Tick: on the Step 2 [TI] command exercising the route.\n\n"
            "- [ ] **Step 2 [TI]: Drive the route**\n\n"
            "Run: `curl -s localhost/`\n\n"
            "Tick: on the exit status.\n")

    defects = [m for (item, _where, m) in probe.lint_plan(plan, [], []) if item == 4]

    assert any("Step 2 [TI]" in m for m in defects), defects


def test_a_c_step_ticking_on_the_next_c_step_is_clean():
    """The shape the plan card's own example taught, and four shipped plans use.

    The C card runs EVERY [C] step in the same turn and records the output, so "the Step 2
    command prints" is the "exact line the recorded command prints" form checklist item 4
    allows. An earlier version of this check rejected all four — the Liferay board's two
    plans on 2026-10-01 (three hits each) and is-even's on 2026-10-03 — and would have cost
    a review round per plan.
    """
    plan = (_HEADER +
            "### Task 1: scaffold\n"
            "- [ ] **Step 1 [C]: Write the workspace root files**\n\n"
            "Write them.\n\n"
            "Tick: on the Step 2 [C] command printing the file names and exiting 0.\n\n"
            "- [ ] **Step 2 [C]: Verify the root files**\n\n"
            "Run: `ls settings.gradle`\n\n"
            "Expected: `settings.gradle`\n\n"
            "Tick: on the exact `settings.gradle` line the command prints.\n")

    defects = [m for (item, _where, m) in probe.lint_plan(plan, [], []) if item == 4]

    assert defects == [], defects


def test_a_tick_naming_a_step_this_task_does_not_have_is_clean():
    """An unresolvable reference is not decidable, so it is not a finding — item 4 is
    rule-decidable only."""
    plan = (_HEADER +
            "### Task 1: scaffold\n"
            "- [ ] **Step 1 [C]: Write the file**\n\n"
            "Run: `ls a.py`\n\n"
            "Tick: on the Step 9 command, which belongs to another task.\n")

    defects = [m for (item, _where, m) in probe.lint_plan(plan, [], []) if item == 4]

    assert defects == [], defects
