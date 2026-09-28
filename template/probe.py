#!/usr/bin/env python3
"""Probe a plan: build the files it writes in a throwaway tree and run its Run commands.

The plan card and the plan review both answer one question — does the named toolchain
do what the plan says it does — and neither could answer it by reading. On
roman-evaluator-liferay-client-ext (2026-09-26/28) the planner was forbidden to run
anything and was rejected three rounds running for values it could only have got by
running them; the reviewer that built the plan's files by hand found the defects, and
the one that did not passed a plan whose build could never succeed. This script is the
shared, one-call way to run it: the plan's own text in, a probe log out.

    python3 template/probe.py --plan <PLAN> --out <RUNS>/scratch/<card-id>/probe \\
        --workdir <WORKDIR> --runs <RUNS> [--targets <root>,...] \\
        [--also-without C] [--timeout 900] [--files-only] [--prune-deps]

What it reads from the plan (the conventions the plan checklist asks for):
- a fenced block whose info string ends `file=<path>` is that file's whole content;
  `patch=<path>` is a unified diff (`a/`/`b/` headers relative to the work directory);
- `Run: `<command>`` on one line, or a fenced block whose info string starts with `run`
  (one command per line), is a Run command;
- the step a block or command sits under (`Step <n> [C]`, `[TW]`, `[TI]`) is its tag.

What it will not do: write outside `--out`; run a command that deploys, builds a bundle or
a container, or names a declared target root (the operator's steps — skipped, allowed); run
one with a placeholder it cannot resolve, one that still names the real work directory, or
one in a shape a card's terminal blocks (`python3 -c`, `bash -c`, an interpreter's `-e`, a
script piped into an interpreter) — skipped, and each is a defect of the plan. The real
work directory is copied into the tree (dependency and build directories left out); every
spelling of its path in a command or a file is rewritten to the tree; git sees no
repository above the tree (and, where the work directory is git-controlled, the tree is a
fresh repository of the copy); and the real work directory and the target-root files the
plan names are fingerprinted around every command — a change there is reported TOUCHED,
with the paths, and fails the probe.

The log (`probe-log.md`) is rewritten after every step, `complete: no` until the end, so
a probe cut short — by a terminal's time limit, or a signal, which also kills the command
it was running — still says how far it got. Its header records the sha256 of the plan's
BYTES, the mode and the output directory; its footer the full pass's tally — what the
driver checks before it accepts a plan review's PASS (run.unprobed_review). A probe that
may outlast your terminal's time limit runs in the background, in its own session:
`setsid nohup python3 … > <out>/stdout.log 2>&1 &`, then read probe-log.md until
`complete: yes`. Each Run command runs alone: whatever it leaves running in the
background (a dev server) is killed when it exits, so a check that needs one starts it
in the same command.

Exit status: 0 when the full pass is clean (every file written, no defect skip, every
command that ran exited 0, nothing TOUCHED), 1 otherwise, 2 on a usage error. A non-zero
probe is EVIDENCE for the card that ran it, never a reason to stop.
"""
import argparse
import datetime
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import card_render  # noqa: E402  (git_control: the one GIT IS OPTIONAL test)

# Directories a copy of the work directory leaves out: reproducible from the files the
# plan names, and large enough (13 725 files under node_modules on the Liferay board)
# to turn a probe into a copy job. `bundles` is a Liferay workspace's server.
SKIP_DIRS = {"node_modules", ".gradle", "build", "dist", "target", ".venv", "venv",
             "__pycache__", ".pytest_cache", ".git", "bundles"}
# What a person's editor writes into the work directory while a probe runs: not a write
# of the probe's, so not TOUCHED.
EDITOR_DIRS = {".idea", ".vscode"}
_EDITOR_FILE = re.compile(r"(?:\.sw[a-p]|~|\.tmp)$|^\.#")
# Pruned from the trees by --prune-deps, and by the driver when the run finishes
# (run.prune_probe_trees): reproducible, and one per card, per pass, per round piles up
# under runs/. Not by default — a review re-runs a command in the probe's copy to prove
# a VERIFIED FIX, and that needs the dependencies still there.
PRUNE_DIRS = ("node_modules", ".gradle", ".venv", "venv")
TAIL_LINES = 40
REWRITE_MAX_BYTES = 2 * 1024 * 1024

_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
# A step HEADING, not a sentence that mentions one ("Task 6 Step 4 [TW] predicts…"):
# optional list/checkbox/bold/heading markup, then `Step <n>`, then its tag.
_STEP = re.compile(r"^\s*(?:[-*]\s*)?(?:\[[ xX]\]\s*)?(?:\*\*|#{2,6}\s*)?Step\s+(\d+)\b"
                   r"[^\[\n]*\[(TW|C|TI)\]")
_TASK = re.compile(r"^\s*#{2,4}\s*Task\s+(\d+)\b")
_RUN_INLINE = re.compile(r"^\s*(?:[-*]\s*)?Run:\s*`([^`]+)`")
_CARD_ID = re.compile(r"<[^<>\n]*card[^<>\n]*id[^<>\n]*>", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"<[A-Za-z][A-Za-z0-9 _.'-]*>")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
# Tasks that write outside the work directory by design — the Liferay workspace's
# deploy, bundle and container tasks. The operator runs them, never a probe.
# Matched as TASKS of the build tools only: `ls configs/deploy` or `grep deployment x`
# is a check that runs.
_TASKS_OUTSIDE = r"(?:\S*:)?(?:deploy\w*|initBundle|distBundle\w*|\w*DockerContainer\w*)"
_WRITES_OUTSIDE = re.compile(
    rf"\b(?:gradlew|gradle|blade)\b[^;&|]*?(?<![\w/.-]){_TASKS_OUTSIDE}(?![\w/.-])"
    rf"|\b(?:npm|yarn|pnpm)\s+(?:run\s+)?deploy\w*\b", re.IGNORECASE)
# The shapes the worker contract says a card's terminal DENIES: a script handed to an
# interpreter inline, and a script piped into one on stdin.
_INTERP = r"(?:python[\d.]*|node|bash|sh|zsh|perl|ruby|php)"
# A path-qualified interpreter (`.venv/bin/python -c`) is the same shape; `python3 -m
# <module>` names a script by module and is the contract's allowed form; `||` is not a
# pipe.
_DENIED = (re.compile(rf"(?:^|[\s;&|(/]){_INTERP}\s+-[A-Za-z]*[ce]\b"),
           re.compile(rf"(?<!\|)\|(?!\|)\s*(?:sudo\s+)?(?:\S*/)?{_INTERP}\b"
                      rf"(?!\s+(?:[^\s-]|-m\b))"))
_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR",
            "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_NAMESPACE")


class PlanError(Exception):
    pass


class Interrupted(Exception):
    """A signal reached the probe: the running command's group is killed, the log is
    written `complete: no`, and the probe exits 1."""


def parse_plan(text):
    """([file entries], [command entries]) in plan order.

    A file entry: {"path", "content", "kind": file|patch, "tag", "where"}; a command:
    {"cmd", "tag", "where"}. `where` is "Task <t> Step <s>" (or "line <n>" before the
    first step) so the log reads like the plan.
    """
    files, commands = [], []
    task = step = tag = None
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0

    def where(n):
        if step is None:
            return f"line {n + 1}"
        return f"Task {task} Step {step}" if task else f"Step {step}"

    while i < len(lines):
        line = lines[i]
        m = _TASK.match(line)
        if m:
            task, step, tag = m.group(1), None, None
        m = _STEP.match(line)
        if m and not _FENCE.match(line):
            step, tag = m.group(1), m.group(2)
        m = _FENCE.match(line)
        if m:
            indent, fence, info = m.group(1), m.group(2), m.group(3).strip()
            body, j = [], i + 1
            while j < len(lines):
                close = _FENCE.match(lines[j])
                if close and close.group(2)[0] == fence[0] \
                        and len(close.group(2)) >= len(fence) and not close.group(3).strip():
                    break
                body.append(lines[j][len(indent):] if lines[j].startswith(indent) else lines[j])
                j += 1
            if j >= len(lines):
                raise PlanError(f"line {i + 1}: a fenced block is never closed")
            words = info.split()
            # `file=`/`patch=` is the info string's LAST attribute and runs to its end:
            # a card-scratch path carries a placeholder with spaces ("<this card's id>").
            target = re.search(r"\b(file|patch)=(.+)$", info)
            if target:
                kind, path = target.group(1), target.group(2).strip().strip("'\"")
                content = "\n".join(body)
                files.append({"path": path, "content": content + "\n",
                              "kind": kind, "tag": tag, "where": where(i)})
            elif words and words[0].lower() == "run":
                for n, cmd in enumerate(body):
                    if cmd.strip() and not cmd.lstrip().startswith("#"):
                        commands.append({"cmd": cmd.strip(), "tag": tag,
                                         "where": where(i + 1 + n)})
            i = j + 1
            continue
        m = _RUN_INLINE.match(line)
        if m:
            commands.append({"cmd": m.group(1).strip(), "tag": tag, "where": where(i)})
        i += 1
    return files, commands


def _inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def spellings(workdir):
    """Every way a plan may spell the work directory's path — absolute, resolved, and
    through `~` / `$HOME` — longest first, so a rewrite never leaves a tail behind."""
    if not workdir:
        return []
    out = {os.path.abspath(workdir), os.path.realpath(workdir)}
    home = os.path.expanduser("~")
    for w in list(out):
        if w.startswith(home + os.sep):
            rel = w[len(home):]
            out |= {"~" + rel, "$HOME" + rel, "${HOME}" + rel}
    return sorted(out, key=len, reverse=True)


def _spelled(s):
    # The spelling as a PATH, not a prefix: `/x/work` must not match `/x/work-shared`.
    return re.compile(re.escape(s) + r"(?=/|$|[^\w.-])")


def _to_tree(text, workdir, tree):
    for s in spellings(workdir):
        text = _spelled(s).sub(lambda _m: tree, text)
    return text


def names_workdir(text, workdir, tree=None):
    """Whether `text` still names the work directory (the tree's own path aside — it may
    start with the same characters)."""
    if tree:
        text = text.replace(tree, "")
    return any(_spelled(s).search(text) for s in spellings(workdir))


def relative_path(path, workdir):
    """The plan's path relative to the tree root, or raise PlanError."""
    p = os.path.expanduser(path.strip().strip("`"))
    if os.path.isabs(p):
        if workdir and _inside(p, workdir):
            p = os.path.relpath(os.path.realpath(p), os.path.realpath(workdir))
        else:
            raise PlanError(f"{path}: an absolute path outside the work directory")
    norm = os.path.normpath(p)
    if norm.startswith("..") or os.path.isabs(norm):
        raise PlanError(f"{path}: escapes the work directory")
    return norm


def destination(path, *, tree, workdir, runs, scratch):
    """Where the probe writes a plan's file: the tree for a work-directory path, the
    probe's own scratch for a card-scratch path (a helper script a Run command calls)."""
    p = _CARD_ID.sub("probe", path.strip().strip("`"))
    if runs and os.path.isabs(p):
        m = re.match(re.escape(os.path.abspath(runs)) + r"/scratch/[^/]+/(.+)$", p)
        if m:
            rel = os.path.normpath(m.group(1))
            if rel.startswith(".."):
                raise PlanError(f"{path}: escapes the card's scratch directory")
            return os.path.join(scratch, rel)
    return os.path.join(tree, relative_path(p, workdir))


def seed_tree(workdir, tree):
    """Copy the work directory into the tree, leaving dependency and build dirs out.
    A text file that names the work directory names the tree instead (a `.npmrc`, a
    `gradle.properties`), or the tree's tools would reach back into the real one.
    (copied, [unreadable paths])."""
    os.makedirs(tree, exist_ok=True)
    if not workdir or not os.path.isdir(workdir):
        return 0, []
    copied, errors = 0, []
    for root, dirs, names in os.walk(workdir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(root, workdir)
        dest = os.path.join(tree, rel) if rel != "." else tree
        os.makedirs(dest, exist_ok=True)
        for n in names:
            src = os.path.join(root, n)
            # A `.git` FILE is a linked worktree's pointer to the real repository: copied,
            # every git command in the tree — and init_tree_repo — would write THAT index.
            if n == ".git" or os.path.islink(src) or not os.path.isfile(src):
                continue
            try:
                text = None
                if os.path.getsize(src) <= REWRITE_MAX_BYTES:
                    with open(src, "rb") as fh:
                        data = fh.read()
                    if b"\0" not in data:
                        try:
                            decoded = data.decode("utf-8")
                        except UnicodeDecodeError:
                            decoded = None
                        if decoded is not None and names_workdir(decoded, workdir):
                            text = _to_tree(decoded, workdir, tree)
                if text is not None:
                    with open(os.path.join(dest, n), "w", encoding="utf-8") as fh:
                        fh.write(text)
                    shutil.copystat(src, os.path.join(dest, n))
                    copied += 1
                    continue
                shutil.copy2(src, os.path.join(dest, n))
                copied += 1
            except OSError as e:
                errors.append(f"{os.path.relpath(src, workdir)}: {e.strerror or e}")
    return copied, errors


def init_tree_repo(tree, workdir):
    """Where the work directory is git-controlled, make the tree a fresh repository of
    the seeded copy, so a plan's `git status` or a version plugin's `git describe` sees
    a clean HEAD — never the kanban repository above the tree. A line for the log."""
    state, _top = card_render.git_control(workdir) if workdir else ("none", None)
    if state != "controlled":
        return None
    env = _no_repo_env(tree)
    git = ["git", "-c", "user.name=probe", "-c", "user.email=probe@localhost",
           "-c", "commit.gpgsign=false"]
    own = os.path.realpath(os.path.join(tree, ".git"))
    for cmd in (git + ["init", "-q"], "check", git + ["add", "-A"],
                git + ["commit", "-q", "--no-verify", "--allow-empty",
                       "-m", "probe: seeded copy of the work directory"]):
        if cmd == "check":
            # Never add or commit into a repository that is not the tree's own.
            r = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=tree, env=env,
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if r.returncode != 0 or os.path.realpath(r.stdout.strip()) != own:
                return (f"git: the tree's repository is not its own "
                        f"({r.stdout.strip() or r.stderr.strip()[:120]}) — nothing added")
            continue
        r = subprocess.run(cmd, cwd=tree, env=env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            return f"git: could not make the tree a repository ({(r.stderr or r.stdout).strip()[:160]})"
    return ("git: the work directory is git-controlled, so the tree is a fresh repository "
            "of the seeded copy (one commit)")


def rewrite(cmd, *, workdir, tree, runs, scratch):
    """The command as the probe runs it: the work directory is the tree, card scratch is
    the probe's own scratch, and a card-id placeholder is `probe`."""
    # Order matters: the card-id placeholder first ("<this card's id>" holds a space),
    # then card scratch, then the work directory — the tree itself lives under a card's
    # scratch, so rewriting the work directory first would hand the scratch rule a path
    # it then rewrites again.
    out = _CARD_ID.sub("probe", cmd)
    if runs:
        out = re.sub(re.escape(os.path.abspath(runs)) + r"/scratch/[^/\s'\"`]+",
                     scratch, out)
    return _to_tree(out, workdir, tree)


def refusal(cmd, *, targets, workdir, tree=None):
    """(kind, why) the probe will not run `cmd` (already rewritten), or None. `kind` is
    "operator" for a step that is the operator's by design (allowed) and "defect" for a
    command the plan must fix."""
    if _WRITES_OUTSIDE.search(cmd):
        return ("operator", "writes outside the work directory (deploy, a bundle or a "
                            "container task) — the operator's step, never a probe's")
    for t in targets:
        if t and os.path.abspath(os.path.expanduser(t)) in cmd:
            return "operator", f"names the declared target root {t}"
    if names_workdir(cmd, workdir, tree):
        return "defect", "still names the real work directory"
    bare = _QUOTED.sub("", cmd)
    # A placeholder outside quotes: `grep -c "<div>" x` is a literal, `<archive>` is not.
    left = _PLACEHOLDER.findall(bare)
    if left:
        return ("defect", f"placeholder {', '.join(sorted(set(left)))} — a Run command must "
                          f"run as written; use a glob or the path itself")
    if any(p.search(bare) for p in _DENIED):
        return ("defect", "a shape a card's terminal BLOCKS (an inline script or one piped "
                          "into an interpreter) — write the script into card scratch and "
                          "run it by its path")
    return None


def _patch_paths(diff_text):
    """The target paths a unified diff names (`+++ <path>`), /dev/null excluded, and
    whether every header carries git's `a/`/`b/` prefixes."""
    out, prefixed = [], True
    for line in diff_text.splitlines():
        if line.startswith(("+++ ", "--- ")):
            p = line[4:].split("\t")[0].strip()
            if p == "/dev/null":
                continue
            if p.startswith(("a/", "b/")):
                p = p[2:]
            else:
                prefixed = False
            if line.startswith("+++ "):
                out.append(p)
    return out, prefixed


def _no_repo_env(tree, base=None):
    """An environment in which git finds no repository above the tree: the probe copy
    lives inside the kanban repository's runs/, and `git apply` there took the patch's
    headers as repository paths and skipped them all, exit 0. A `GIT_DIR` would override
    the ceiling, so every variable that points git somewhere is dropped."""
    env = dict(base or os.environ)
    for k in _GIT_ENV:
        env.pop(k, None)
    env["GIT_CEILING_DIRECTORIES"] = os.path.dirname(os.path.abspath(tree))
    return env


def write_files(files, tree, *, workdir, targets, runs=None, scratch=None, skip_tag=None):
    rows = []
    for f in files:
        row = {"where": f["where"], "tag": f["tag"] or "-", "path": f["path"],
               "kind": f["kind"], "note": ""}
        rows.append(row)
        raw = os.path.expanduser(f["path"].strip().strip("`"))
        if os.path.isabs(raw) and any(_inside(raw, os.path.expanduser(t)) for t in targets):
            row.update(note="under a declared target root — never probed", target=raw)
            continue
        try:
            dest = destination(f["path"], tree=tree, workdir=workdir, runs=runs,
                               scratch=scratch or os.path.join(tree, "..", "scratch"))
        except PlanError as e:
            row.update(note=f"NOT WRITTEN: {e}", failed=True)
            continue
        # A product file of the left-out card is left out; a helper script in card
        # scratch is not the card's product and is always written.
        if skip_tag and f["tag"] == skip_tag and _inside(dest, tree):
            row["note"] = f"left out (--also-without {skip_tag})"
            continue
        # A file that names the real work directory names the tree instead, so what it
        # configures points into the probe's copy (a gradle.properties, a config path).
        content = _to_tree(f["content"], workdir, tree)
        try:
            os.makedirs(os.path.dirname(dest) or tree, exist_ok=True)
            if f["kind"] == "file":
                existed = os.path.lexists(dest)
                if os.path.islink(dest):
                    os.remove(dest)
                with open(dest, "w", encoding="utf-8") as fh:
                    fh.write(content)
                data = content.encode("utf-8")
                row.update(bytes=len(data), sha=hashlib.sha256(data).hexdigest()[:12],
                           note="replaced" if existed else "", written=True)
            else:
                row["note"] = apply_patch(content, tree)
                row["written" if row["note"] == "patch applied" else "failed"] = True
        except OSError as e:
            row.update(note=f"NOT WRITTEN: {type(e).__name__}: {e}", failed=True)
    return rows


def apply_patch(content, tree):
    """Apply one `patch=` block at the tree's root, or say why not."""
    paths, prefixed = _patch_paths(content)
    bad = [p for p in paths if os.path.isabs(p) or not _inside(os.path.join(tree, p), tree)]
    if bad:
        return f"PATCH REFUSED: {', '.join(bad)} is not inside the work directory"
    fd, patch = tempfile.mkstemp(prefix=".probe-patch-", dir=os.path.dirname(os.path.abspath(tree)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        env = _no_repo_env(tree)
        strip = "-p1" if prefixed else "-p0"
        check = subprocess.run(["git", "apply", strip, "--check", "--recount", patch],
                               cwd=tree, capture_output=True, text=True, env=env,
                               stdin=subprocess.DEVNULL)
        if check.returncode != 0:
            return f"PATCH FAILED: {(check.stderr or check.stdout).strip()[:200]}"
        r = subprocess.run(["git", "apply", strip, "--recount", patch], cwd=tree,
                           capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        return ("patch applied" if r.returncode == 0
                else f"PATCH FAILED: {(r.stderr or r.stdout).strip()[:200]}")
    finally:
        os.remove(patch)


def _stat_row(path, st):
    return (path, st.st_mode, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def fingerprint(workdir, paths=()):
    """What the probe must not change: every entry under the real work directory, and
    the target-root files the plan names. ctime and inode are in the row, so a change
    restored with its old size and mtime (`cp -p`, `touch -r`, `tar x`) still shows. A
    dependency or build directory is read one level deep — the probe never copies it,
    and a `yarn install` that reached the real one must still show."""
    seen = {}

    def add(p):
        try:
            seen[p] = _stat_row(p, os.lstat(p))
        except OSError:
            seen[p] = None

    for p in paths:
        add(p)
    if workdir and os.path.isdir(workdir):
        for dirpath, dirs, names in os.walk(workdir):
            keep = []
            for d in dirs:
                full = os.path.join(dirpath, d)
                # .git: nothing the probe runs can reach it (its own repository, the
                # ceiling, rewritten paths), and an IDE polling `git status` rewrites the
                # index every few seconds.
                if d in EDITOR_DIRS or d == ".git":
                    continue
                add(full)
                if d in SKIP_DIRS:
                    try:
                        for child in os.listdir(full):
                            add(os.path.join(full, child))
                    except OSError:
                        pass
                else:
                    keep.append(d)
            dirs[:] = keep
            for n in names:
                if n != ".git" and not _EDITOR_FILE.search(n):
                    add(os.path.join(dirpath, n))
    return seen


def changed(before, after):
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


class _Current:
    proc = None


def _kill_group(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def _run_one(cmd, cwd, env, timeout, log_path):
    """(output, exit code or 'TIMEOUT …'): the command in its own process group, stdin
    closed, its output in `log_path`. The probe waits for the SHELL, not for the output
    to close — a server the command backgrounds holds the output open, and waiting on it
    turned a finished command into a timeout. The whole group is killed on a timeout, on
    a signal to the probe, and when the command exits (a child it left running would keep
    writing into the tree)."""
    with open(log_path, "wb") as out:
        p = subprocess.Popen(cmd, shell=True, executable="/bin/bash", cwd=cwd, env=env,
                             stdin=subprocess.DEVNULL, stdout=out,
                             stderr=subprocess.STDOUT, start_new_session=True)
        _Current.proc = p
        try:
            code = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(p)
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            code = f"TIMEOUT after {timeout}s"
        except BaseException:
            _kill_group(p)
            raise
        finally:
            _Current.proc = None
        _kill_group(p)
    with open(log_path, "rb") as fh:
        return fh.read().decode("utf-8", "replace"), code


def _on_signal(signum, _frame):
    if _Current.proc is not None:
        _kill_group(_Current.proc)
    raise Interrupted(f"signal {signum}")


def run_commands(commands, tree, *, workdir, runs, scratch, targets, timeout, logs,
                 guard=(), only_tags=None, flush=lambda rows: None):
    rows = []
    os.makedirs(logs, exist_ok=True)
    os.makedirs(scratch, exist_ok=True)
    env = _no_repo_env(tree, dict(os.environ, PYTHONDONTWRITEBYTECODE="1", CI="1"))
    for n, c in enumerate(commands, 1):
        if only_tags is not None and c["tag"] not in only_tags:
            continue
        ran = rewrite(c["cmd"], workdir=workdir, tree=tree, runs=runs, scratch=scratch)
        row = {"n": n, "where": c["where"], "tag": c["tag"] or "-", "cmd": c["cmd"],
               "ran": ran}
        rows.append(row)
        why = refusal(ran, targets=targets, workdir=workdir, tree=tree)
        if why:
            row.update(status="SKIPPED", skip=why[0], why=why[1])
            flush(rows)
            continue
        log_path = os.path.join(logs, f"{n:02d}.log")
        before = fingerprint(workdir, guard)
        t0 = time.time()
        row["status"] = "running"
        flush(rows)
        output, code = _run_one(ran, tree, env, timeout, log_path)
        touched = changed(before, fingerprint(workdir, guard))
        row.update(status="exit 0" if code == 0 else f"exit {code}",
                   ok=code == 0 and not touched, secs=round(time.time() - t0, 1),
                   log=log_path, tail="\n".join(output.rstrip().splitlines()[-TAIL_LINES:]))
        if touched:
            row["status"] += " — TOUCHED the real work directory or a target-root file"
            row["touched"] = touched
        flush(rows)
    return rows


def _files_table(rows):
    out = ["| step | tag | path | bytes | sha256 | note |", "|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['where']} | {r['tag']} | `{r['path']}` | {r.get('bytes', '')} "
                   f"| {r.get('sha', '')} | {r['note']} |")
    return out


def tally(rows):
    done = [r for r in rows if r.get("status") not in ("SKIPPED", "running")]
    failed = [r for r in done if not r.get("ok")]
    skipped = [r for r in rows if r.get("status") == "SKIPPED"]
    return {"commands": len(rows), "ran": len(done), "exit0": len(done) - len(failed),
            "failed": len(failed), "skipped": len(skipped),
            "skipped-defect": sum(1 for r in skipped if r.get("skip") == "defect")}


def _commands_section(rows):
    t = tally(rows)
    out = [f"{t['commands']} command(s): {t['exit0']} exit 0, {t['failed']} failed, "
           f"{t['skipped']} skipped ({t['skipped-defect']} for a defect of the plan)", ""]
    for r in rows:
        out.append(f"### {r['n']}. {r['where']} [{r['tag']}] — {r.get('status', 'running')}"
                   + (f" in {r['secs']} s" if "secs" in r else ""))
        out.append(f"plan: `{r['cmd']}`")
        if r["ran"] != r["cmd"]:
            out.append(f"ran as: `{r['ran']}`")
        if r.get("why"):
            out.append(f"skipped ({r['skip']}): {r['why']}")
        if r.get("touched"):
            out.append("touched: " + ", ".join(r["touched"][:10])
                       + (" …" if len(r["touched"]) > 10 else ""))
        if r.get("tail"):
            # Indented, so no line of a command's output can pass for a log field.
            out += ["", "```text"] + ["    " + l for l in r["tail"].splitlines()] + ["```",
                                                                                  f"full output: {r['log']}"]
        out.append("")
    return out


def prune(tree):
    """Remove the dependency directories (PRUNE_DIRS) from a probe tree."""
    for dirpath, dirs, _names in os.walk(tree):
        for d in list(dirs):
            if d in PRUNE_DIRS:
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                dirs.remove(d)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--targets", default="")
    ap.add_argument("--also-without", dest="without", choices=("C", "TW", "TI"))
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--files-only", action="store_true")
    ap.add_argument("--prune-deps", action="store_true")
    a = ap.parse_args(argv)
    targets = [t.strip() for t in a.targets.split(",") if t.strip()
               and not t.strip().startswith("none")]
    out = os.path.abspath(a.out)
    workdir = os.path.abspath(a.workdir)
    if _inside(out, workdir) or any(_inside(out, os.path.expanduser(t)) for t in targets):
        print(f"probe.py: --out {out} is inside the work directory or a target root — a "
              f"probe never writes there", file=sys.stderr)
        return 2
    os.makedirs(out, exist_ok=True)
    log_path = os.path.join(out, "probe-log.md")
    started = time.time()
    head = ["# Probe log", "", f"plan: {os.path.abspath(a.plan)}", "plan-sha256: (not read yet)",
            f"workdir: {workdir}", f"out: {out}",
            f"mode: {'files-only' if a.files_only else 'full'}",
            f"started: {datetime.datetime.fromtimestamp(started).isoformat(timespec='seconds')}",
            f"started-epoch: {int(started)}", ""]
    body, summary, last = [], {}, {"extra": []}

    def write_log(extra=(), complete=False):
        last["extra"] = list(extra)
        lines = head + body + list(extra)
        if summary:
            lines += ["full-pass: " + ", ".join(
                f"{k} {summary.get(k, 0)}" for k in
                ("files", "files-failed", "commands", "ran", "exit0", "failed", "skipped",
                 "skipped-defect"))]
        lines += [f"complete: {'yes' if complete else 'no'}", ""]
        tmp = log_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        os.replace(tmp, log_path)

    # First, before anything can fail: an earlier probe's `complete: yes` must never be
    # read as this one's result.
    write_log()
    try:
        with open(a.plan, "rb") as fh:
            raw = fh.read()
        # The sha of the BYTES — what the driver hashes too; a CRLF plan read in text
        # mode would hash to a different value forever.
        sha = hashlib.sha256(raw).hexdigest()
        head[3] = f"plan-sha256: {sha}"
        files, commands = parse_plan(raw.decode("utf-8", "replace"))
    except (OSError, PlanError) as e:
        body.append(f"PLAN UNREADABLE: {e} — nothing was built or run")
        write_log(complete=True)
        print(f"probe.py: {e}", file=sys.stderr)
        return 2
    # What an earlier probe left behind is not this probe's evidence — and a symlink a
    # command planted there would be written through.
    for old in os.listdir(out):
        if old == "scratch" or old.startswith(("logs", "tree")):
            p = os.path.join(out, old)
            if os.path.islink(p) or os.path.isfile(p):
                os.remove(p)
            else:
                shutil.rmtree(p)
    passes = [("full", None, None)]
    if a.without:
        # The predicted FAIL: the other cards' files without this tag's, and only the
        # steps of the tags that remain — what the TW card's run would see on its own.
        passes.append((f"without-{a.without}", a.without,
                       {t for t in ("TW", "C", "TI") if t != a.without}))
    worst = 0
    # A signal the probe was started to ignore stays ignored: `nohup` ignores SIGHUP so
    # the probe outlives the terminal, and a background job ignores SIGINT.
    old_handlers = {s: signal.signal(s, _on_signal)
                    for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
                    if signal.getsignal(s) is not signal.SIG_IGN}
    try:
        write_log()
        for name, skip_tag, only_tags in passes:
            tree = os.path.join(out, "tree" if name == "full" else f"tree-{name}")
            seeded, seed_errors = seed_tree(workdir, tree)
            git_line = init_tree_repo(tree, workdir)
            frows = write_files(files, tree, workdir=workdir, targets=targets, runs=a.runs,
                                scratch=os.path.join(out, "scratch"), skip_tag=skip_tag)
            body += [f"## Pass: {name}", "", f"tree: {tree} (seeded with {seeded} file(s) "
                     f"from the work directory, dependency and build directories left out)"]
            if seed_errors:
                body.append(f"not seeded ({len(seed_errors)}): " + "; ".join(seed_errors[:10]))
            if git_line:
                body.append(git_line)
            body += ["", f"### Files ({len(frows)})", ""] + _files_table(frows) + [""]
            if name == "full":
                summary["files"] = sum(1 for r in frows if r.get("written"))
                summary["files-failed"] = sum(1 for r in frows if r.get("failed"))
                if summary["files-failed"]:
                    worst = 1
            write_log()
            if a.files_only:
                continue
            guard = [r["target"] for r in frows if r.get("target")]
            crows = run_commands(commands, tree, workdir=workdir, runs=a.runs,
                                 scratch=os.path.join(out, "scratch"), targets=targets,
                                 timeout=a.timeout, guard=guard,
                                 logs=os.path.join(out, "logs" if name == "full" else f"logs-{name}"),
                                 only_tags=only_tags,
                                 flush=lambda rows: write_log(["### Commands", ""]
                                                              + _commands_section(rows)))
            body += ["### Commands", ""] + _commands_section(crows)
            last["extra"] = []
            if name == "full":
                summary.update(tally(crows))
                if summary["failed"] or summary["skipped-defect"]:
                    worst = 1
            write_log()
    except Interrupted as e:
        # The interrupted pass's command rows live only in the last flush: keep them, so
        # the log still says how far the probe got.
        body.extend(last["extra"])
        body.append(f"INTERRUPTED by {e} — the running command's process group was killed")
        write_log()
        print(f"probe interrupted ({e}); log: {log_path}", file=sys.stderr)
        return 1
    finally:
        for s, h in old_handlers.items():
            signal.signal(s, h)
    if a.prune_deps:
        for d in os.listdir(out):
            if d.startswith("tree"):
                prune(os.path.join(out, d))
    body += [f"finished: {datetime.datetime.now().isoformat(timespec='seconds')}", ""]
    write_log(complete=True)
    print(f"probe log: {log_path}")
    return worst


_HEADER_KEYS = {"plan-sha256": "sha", "mode": "mode", "started-epoch": "started", "out": "out"}


def read_log(log_path):
    """What the driver checks in a probe log: {"sha", "mode", "started", "out",
    "complete", "files", "files-failed", "ran", "failed", "skipped-defect", …} — None
    when there is no readable log. Header fields are read only before the first pass and
    the tally only from the footer, so no line of a command's output can set either."""
    try:
        with open(log_path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    info = {}
    for line in lines:
        if line.startswith("## Pass"):
            break
        key, _, value = line.partition(":")
        if key in _HEADER_KEYS:
            value = value.strip()
            if key == "started-epoch":
                value = int(value) if value.isdigit() else None
            info[_HEADER_KEYS[key]] = value
    footer = [l for l in lines if l.strip()][-2:]
    for line in footer:
        key, _, value = line.partition(":")
        value = value.strip()
        if key == "complete":
            info["complete"] = value == "yes"
        elif key == "full-pass":
            for part in value.split(","):
                k, _, n = part.strip().rpartition(" ")
                if n.isdigit():
                    info[k] = int(n)
    return info


def recorded_plan_sha(log_path):
    """The plan-sha256 a probe log records, or None."""
    return (read_log(log_path) or {}).get("sha")


if __name__ == "__main__":
    sys.exit(main())
