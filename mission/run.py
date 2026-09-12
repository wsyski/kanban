#!/usr/bin/env python3
"""Driver for generic kanban board missions.

The driver never commits. Gates wait for a human unless the lane's idea (or
the board default) sets auto-gates, in which case the gate auto-completes on
a PASS verdict with staged-file evidence — still no commit.

Usage: mission/run.py [--serve] [--once] [--timeout-min 120]
"""
import json, shutil, subprocess, sys, time, os, re, datetime

# No default: this repo has no one board, and a stale default would drive the
# wrong one. Enforced in main(), not here — the test suite imports this module.
BOARD = os.environ.get("BOARD", "")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ONCE = "--once" in sys.argv
# The main scenario is a board that stays up: you type an idea into the
# dashboard, promote it out of Triage, and the run starts. Exiting when the
# gates close would make every new idea a terminal command again.
SERVE = "--serve" in sys.argv
POLL = 20

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board_schema
import lanes
import file_lanes
import runs_util

BOARD_DIR = os.path.join(REPO, "boards", BOARD)
BOARD_CFG = os.path.join(BOARD_DIR, "board.json")
IDEAS_DIR = BOARD_DIR
# runs/ is board-level and holds the DRIVER's own state — its log and its lock,
# both of which outlive any single run (one serve-mode driver answers many ideas).
# Everything belonging to a RUN lives in runs/<run-id>/, minted when an idea is
# armed and never touched again.
RUNS_ROOT = os.path.join(BOARD_DIR, "runs")
CURRENT_RUN = os.path.join(RUNS_ROOT, "current")   # a file naming the live run


def _read_current_run():
    """The run id runs/current names, or None. A pointer FILE, not a symlink: the
    per-card paths are rendered into card bodies at filing time and swept from the
    git index by pathspec, and both break on an alias — a worker orphaned by run N
    would resolve `current` at write time and land in run N+1's directory, which is
    the overwrite this layout exists to prevent (F2), while `git diff --cached --
    runs/...` does not match through a symlink at all (E14)."""
    try:
        with open(CURRENT_RUN) as f:
            return f.read().strip() or None
    except OSError:
        return None


def use_run(run_id):
    """Point every per-run path at runs/<run-id>. Reassigns the module globals so
    the paths stay plain strings: a hundred call sites join them, tests patch
    RUN_DIR, and a lazy accessor would buy nothing."""
    global RUN_DIR, SNAP_DIR, TIMING_PATH, CARDS_DIR, VERDICTS_PATH
    RUN_DIR = os.path.join(RUNS_ROOT, run_id) if run_id else RUNS_ROOT
    SNAP_DIR = os.path.join(RUN_DIR, "snapshots")
    TIMING_PATH = os.path.join(RUN_DIR, "timing.jsonl")
    CARDS_DIR = os.path.join(RUN_DIR, "cards")
    VERDICTS_PATH = os.path.join(RUN_DIR, "verdicts.jsonl")
    return RUN_DIR


def mint_run(run_id):
    """Create runs/<run-id>/ and make it current. Called once per armed idea.

    Nothing is deleted here, or anywhere: a finished run's evidence stays exactly
    as it was and the next run starts on empty paths because they are NEW paths,
    not because something cleared them. That is what retires clear_run_state,
    snapshot_run_evidence and clear_lane_outputs — a fresh directory cannot hold a
    previous run's refined idea, so the stale-hand-off failures (#31, F2) stop
    being something a driver has to remember to prevent.
    """
    path = use_run(run_id)
    os.makedirs(path, exist_ok=True)
    tmp = CURRENT_RUN + ".tmp"
    with open(tmp, "w") as f:
        f.write(run_id + "\n")
    os.replace(tmp, CURRENT_RUN)          # atomic: a reader sees one id or the other
    log(f"RUN {run_id}: {os.path.relpath(path, REPO)}")
    return path


# Before the first idea is armed there is no run, and the driver still logs and
# locks: those live at RUNS_ROOT, and RUN_DIR falls back to it so a pre-run write
# lands where it always did rather than in a directory named after nothing.
RUN_DIR = SNAP_DIR = TIMING_PATH = CARDS_DIR = VERDICTS_PATH = None
use_run(_read_current_run())


def manifest():
    """Board manifest. REPO is template_root (control files); WORKDIR is the
    only tree git ever runs in — they differ when a board points elsewhere."""
    try:
        return json.load(open(BOARD_CFG))
    except FileNotFoundError:
        # Same defaults create-board.sh prints in --help, so a board that loses
        # its manifest degrades to the documented shape rather than silently
        # growing integration cards nobody asked for.
        return {"default-workdir": os.path.join(BOARD_DIR, "work"), "lanes": 1,
                "integration-tests": False, "auto-gates": False}


def board_defaults():
    return manifest()


WORKDIR = manifest().get("default-workdir") or os.path.join(BOARD_DIR, "work")



def board_lane_count(state):
    n = 0
    for title in state:
        m = re.match(r"^P(\d+):", title)
        if m:
            n = max(n, int(m.group(1)))
    return n


def lane_graph(state):
    """(title, parent-prefixes, kind, lane) rows for every lane on the board.

    Parents are expressed as title PREFIXES so the existing prefix matching
    (and the rework loop's P<k>-rev / RVp<k>-r cards) keeps working. A card
    that was pruned at unblock time is simply absent from `state`, and
    parents_done() treats a missing parent as not-done — so pruning must
    also repoint Gc's parent, which open_lane() does on the board itself.
    """
    rows = []
    for lane in range(1, board_lane_count(state) + 1):
        present = [c for c in lanes.lane_cards(lane, integration_tests=True)
                   if c["title"] in state]
        prev = None
        for c in present:
            parents = [prev] if prev else ([f"Gc{lane - 1}"] if lane > 1 else [])
            # Rework cards gate the review ONLY once a round has been filed.
            # Listing them unconditionally stalled every lane that passed plan
            # review first time: parents_done() treats a missing parent as
            # not-done, so RVp waited forever on a P<k>-rev that never existed.
            rework = [pfx for pfx in (f"P{lane}-rev", f"RVp{lane}-r")
                      if title_of_prefix(state, pfx)[1] is not None]
            if c["code"] == "RVp":
                parents += rework
            if c["code"] == "Gp":
                parents = [f"RVp{lane}"] + rework
            # Same shape one stage later, for the code loop a REJECT files:
            # C{lane}-rev-<r> / RVa{lane}-r<r> sit between RVa and Gc. Nothing
            # linked them, so Gc unblocked while its own rework was still live
            # and only the verdict-token check in gate_action held it — while
            # tick()'s comment claimed the parents did. Linked now, for RVa and
            # Gc alike; Gc keeps its positional parent (RVa, or RVc on a lane
            # with integration tests) and the round is added to it.
            code_rework = [pfx for pfx in (f"C{lane}-rev", f"RVa{lane}-r")
                           if title_of_prefix(state, pfx)[1] is not None]
            if c["code"] in ("RVa", "Gc"):
                parents += code_rework
            rows.append((c["title"], parents, c["code"].lower(), lane))
            prev = c["id"]
    return rows


def lane_options(lane):
    parsed = lanes.read_idea(os.path.join(IDEAS_DIR, f"lane-{lane}.md"))
    if parsed is None:
        return None
    headers, body = parsed
    opts = lanes.resolve_lane_options(board_defaults(), headers, lane)
    opts["idea"] = body
    return opts

def kb(*args, capture=True):
    r = subprocess.run(["hermes", "kanban", "--board", BOARD, *args],
                       capture_output=capture, text=True, env=runs_util.cli_env())
    if r.returncode != 0:
        raise RuntimeError(f"kb {args[:2]}: {runs_util.cli_error(r.stderr)}")
    return r.stdout

def board():
    """Live cards, keyed by title.

    Titles are unique by construction (card_title embeds code + lane), so the
    keying is safe — but a refile that fails to archive an old card leaves two
    rows sharing a title, and the dict would silently keep only one. That is
    how a card the refile missed stayed invisible for a whole run, so say it
    out loud rather than dropping it.
    """
    out = json.loads(kb("list", "--json"))
    state = {}
    for card in out:
        if card["title"] in state:
            log(f"WARNING: two live cards titled {card['title']!r} "
                f"({state[card['title']]['id']}, {card['id']}) — one is stale; "
                f"archive it, or the board will disagree with itself")
        state[card["title"]] = card
    return state

def log(msg):
    """stdout (the driver's board-level log) AND the current run's own log.

    The driver outlives any one run in serve mode, so its stdout is board-scoped;
    the per-run copy is what `run-audit.py --runs runs/<id>` reads, which is why
    auditing an earlier run needs no log slicing. Before the first idea is armed
    there is no run directory, and a failure to write one must never take the
    driver down — stdout is the record that always exists."""
    line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        if RUN_DIR and RUN_DIR != RUNS_ROOT and os.path.isdir(RUN_DIR):
            with open(os.path.join(RUN_DIR, "driver.log"), "a") as f:
                f.write(line + "\n")
    except OSError:
        pass

def title_of_prefix(state, prefix):
    """Card whose TITLE CODE equals the prefix.

    'Gi1' matches 'Gi1: ...' but NOT 'Gi10: ...' — the lane number ends at a
    boundary. 'RVp1-r' matches 'RVp1-r2: ...' (the round number continues the
    code) because the prefix itself does not end in a digit. A prefix that
    already ends in ':' or '-' carries its own boundary and matches plainly.
    Every parent lookup goes through here.
    """
    ends_digit = prefix[-1:].isdigit()
    ends_boundary = prefix[-1:] in (":", "-")
    for t, card in state.items():
        if not t.startswith(prefix):
            continue
        if ends_boundary:
            return t, card
        nxt = t[len(prefix):len(prefix) + 1]
        if nxt in (":", "-") or (nxt.isdigit() and not ends_digit):
            return t, card
    return None, None

def parents_done(state, prefixes):
    for p in prefixes:
        t, card = title_of_prefix(state, p)
        if card is None or card["status"] != "done":
            return False
    return True

def result_of(state, prefix):
    t, card = title_of_prefix(state, prefix)
    return (card or {}).get("result") or ""

def git(*args):
    r = subprocess.run(["git", "-C", WORKDIR, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {args}: {r.stderr.strip()[:200]}")
    return r.stdout.strip()

def card_id(state, title):
    c = state.get(title)
    if not c:
        raise RuntimeError(f"card missing: {title}")
    return c["id"]

def plan_review_pass(state, lane):
    """Latest finished plan-review verdict — superseded by latest_verdict()."""
    return latest_verdict(state, lane, "RVp", "Gp")

def _goal_args(assignee, code):
    """Delegates to lanes.goal_args — single source of the worker-only rule.

    The board decides whether its workers run under the goal judge: machine
    without a working auxiliary model sets `"goal": false` in board.json
    and its cards complete on their own evidence (reviewers and gates still
    judge the work).
    """
    cfg = board_defaults()
    return lanes.goal_args(code, enabled=bool(cfg.get("goal", True)),
                           max_turns=cfg.get("goal-max-turns"))


def latest_verdict_card(state, lane, reviewer_prefix, final_code=None):
    """(card, verdict text) of the newest review round that has FINISHED —
    (None, "") when none has.

    Only the card's result field counts — the verdict contract lives there.
    Falling back to run summaries (as this first did) read RVp1's parking
    block summary ('parked: awaiting lane activation') as a verdict and held
    Gp forever. `final_code` extends the scan (RVc is RVa's re-review).
    """
    cands = [reviewer_prefix, final_code] if final_code else [reviewer_prefix]
    best_card, best_done = None, -1.0
    for base in [b for b in cands if b]:
        # The colon pins the base card: a bare "Gi1" also prefixes "Gi1-r2", and
        # a round listed first and not yet done used to hide the base verdict.
        t, c = title_of_prefix(state, f"{base}{lane}:")
        if c and c["status"] == "done":
            done = c.get("completed_at") or 0
            if done > best_done:
                best_card, best_done = c, done
        for k in range(1, 10):
            t, c = title_of_prefix(state, f"{base}{lane}-r{k + 1}")
            if c and c["status"] == "done":
                done = c.get("completed_at") or 0
                if done > best_done:
                    best_card, best_done = c, done
    if not best_card:
        return None, ""
    if (best_card.get("result") or "").strip():
        return best_card, best_card.get("result")
    # The card is done but its result field is empty — the reviewer completed
    # with --summary only (E2E-2 did exactly that; e2e-1 used --result). The
    # verdict prose then lives in the CLOSING RUN's summary. Accept ONLY a
    # completed run: the parking block is also a run here, and that is how
    # 'parked: awaiting lane activation' once masqueraded as a verdict.
    runs = runs_util.board_runs(BOARD, best_card.get("id"))
    closed_ok = [r for r in runs if r.get("outcome") == "completed"]
    if closed_ok:
        last = max(closed_ok, key=lambda r: r.get("ended_at") or 0)
        return best_card, (last.get("summary") or "").strip()
    return best_card, ""


def latest_verdict(state, lane, reviewer_prefix, gate_code, final_code=None):
    """The gate-relevant verdict text — see latest_verdict_card."""
    del gate_code
    return latest_verdict_card(state, lane, reviewer_prefix, final_code)[1]


def rework_hold(state, lane, base, gate_code):
    """True while a revision/re-gate card of this loop is live (not done)."""
    for t, c in state.items():
        if (t.startswith(f"{base}{lane}-rev") or t.startswith(f"{gate_code}{lane}-r")) \
                and c["status"] not in ("done", "archived"):
            return True
    return False


def code_rework_hold(state, lane):
    """True while a CODER revision or RVa re-review round is live."""
    for t, c in state.items():
        if (t.startswith(f"C{lane}-rev") or t.startswith(f"RVa{lane}-r")) \
                and c["status"] not in ("done", "archived"):
            return True
    return False


def rework_retries():
    """Retry budget for a REVISION card, from `rework-max-retries`.

    Separate from `max-retries`, which is the board's first filing: a revision is a
    second attempt at work a reviewer already rejected, so a board may want it
    tighter or looser than the original without changing both. Default 1, as this
    was when it was a literal.
    """
    return str(manifest().get("rework-max-retries")
               or board_schema.OPTIONS["rework-max-retries"][1])


def _round_settings(lane):
    """(max_runtime, render) for a rework round: the board's own ceiling, and bodies
    rendered exactly as board filing renders them."""
    cfg = manifest()
    runtime = cfg.get("max-runtime") or file_lanes.DEFAULT_MAX_RUNTIME
    targets = cfg.get("targets") or ()

    def render(body_file):
        return file_lanes.render_body(body_file, repo=REPO, board=BOARD, workdir=WORKDIR,
                                      run_id=_read_current_run(),
                                      lane=lane, targets=targets)
    return runtime, render


def _skill_args(code):
    skill = lanes.skill_for(code)
    return ["--skill", skill] if skill else []


def _full_verdict_pointer(verdict_card_id):
    if not verdict_card_id:
        return ""
    return (f"Full verdict: `hermes kanban --board {BOARD} show {verdict_card_id}` and its "
            f"attached review file, if any — the excerpt above may be cut.\n")


def record_rework(lane, gate_code, round_no, cards, findings, state):
    """Log one return-to-predecessor: which gate sent work back, to whom, why.

    Both the per-run chain and the board's ledger, because the two answer
    different questions — and a REJECT whose round never got filed (a stall, a
    crash, a wrong hold) is exactly what a reader cannot see from the verdict
    alone, so the pair is what makes the loop auditable.
    """
    gate_title = lanes.card_title(gate_code, lane)
    gate_id = card_id(state, gate_title) if state else None
    excerpt = " ".join((findings or "").split())[:600]
    rec = {"event": "rework", "lane": lane, "gate": gate_code, "round": round_no,
           "cards": list(cards), "findings": excerpt}
    chain_record("rework", {"title": gate_title, "id": gate_id, "status": ""}, lane,
                 gate=gate_code, round=round_no, cards=list(cards), findings=excerpt)
    ledger(rec)


def file_revision(state, lane, round_no, findings, base="P", reviewer_prefix="RVp",
                  gate_code="Gp", max_rounds=3, verdict_card_id=None):
    """File one rework round: a revision card + its re-gate, linked to the gate.

    Serves BOTH loops: the plan loop (base P, reviewer RVp,
    gate Gp) and the idea loop (base I, re-gate Gi itself). The idea loop's
    'reviewer' is the re-gate — no separate reviewer sits before an idea
    gate, by design. Both cards are rendered like the cards they repeat: same
    paths, same workdir, same ceiling, same skill.
    """
    kind = "plan" if base == "P" else "idea"
    if kind == "plan":
        rev_title = f"P{lane}-rev-{round_no}: plan revision round {round_no} - lane {lane}"
        rev_body_file, rev_assignee = "p-body.txt", "manager"
        rr_title = f"RVp{lane}-r{round_no + 1}: plan review round {round_no + 1} - lane {lane}"
        rr_body_file, rr_assignee = "rvp-body.txt", "reviewer"
        sender = "The plan review"
    else:
        rev_title = f"I{lane}-rev-{round_no}: idea refinement round {round_no} - lane {lane}"
        rev_body_file, rev_assignee = "i-body.txt", "researcher"
        rr_title = f"Gi{lane}-r{round_no + 1}: idea re-gate round {round_no + 1} - lane {lane}"
        rr_body_file, rr_assignee = "gi-body.txt", "human-gate"
        sender = "The idea gate"
    if title_of_prefix(state, rev_title)[0]:
        return  # already filed
    gate_id = card_id(state, lanes.card_title(gate_code, lane))
    runtime, render = _round_settings(lane)

    rbody = render(rev_body_file)
    rbody += (f"\nREVISION ROUND {round_no} of {max_rounds} (max {max_rounds}, then human "
              f"escalation).\n\n{sender} sent this back. Address EXACTLY:\n{findings}\n"
              f"Fix only these, re-stage, re-attach, complete with a change summary.\n")
    rbody += _full_verdict_pointer(verdict_card_id)
    remap = manifest().get("assignees")
    args = ["create", rev_title, "--body", rbody,
            "--assignee", lanes.assignee_for(rev_assignee, remap),
            "--workspace", f"dir:{WORKDIR}", "--max-runtime", runtime, "--max-retries", rework_retries(),
            "--idempotency-key", f"{BOARD}-rev-{base}{lane}-{round_no}",
            "--created-by", "manager", "--json"] + _skill_args(base) + _goal_args(rev_assignee, base)
    rev_id = json.loads(kb(*args))["id"]

    rrbody = render(rr_body_file)
    if kind == "plan":
        # A re-review is a verdict card like the review it repeats: told to act
        # "as a gate-holder", it could complete without PASS/REJECT and hold Gp
        # forever with no further round filed.
        rrbody += (f"\nRE-REVIEW ROUND {round_no + 1} of {max_rounds + 1}. The plan was revised "
                   f"after a REJECT; the findings are on the parent revision card. Re-check "
                   f"EVERY checklist item against the revised plan, not only the fixed ones, "
                   f"and put the verdict first in the result field: PASS: or REJECT:.\n")
    else:
        rrbody += (f"\nRE-GATE ROUND {round_no + 1} of {max_rounds + 1}. A previous gate-holder "
                   f"sent the work back with the findings on the parent revision card. Verify "
                   f"they are addressed, then complete this card exactly as a gate-holder would.\n")
    rr_args = ["create", rr_title, "--body", rrbody,
               "--assignee", lanes.assignee_for(rr_assignee, remap),
               "--parent", rev_id, "--workspace", f"dir:{WORKDIR}", "--max-runtime", runtime,
               "--max-retries", rework_retries(), "--idempotency-key",
               f"{BOARD}-rr-{base}{lane}-r{round_no + 1}", "--created-by", "manager", "--json"]
    rr_id = json.loads(kb(*rr_args))["id"]
    kb("link", rr_id, gate_id)
    # This gate now also guards the DOWNSTREAM card against starting while
    # rework is in flight; the positional-parents check in tick() enforces it.
    # _OPENED stays untouched: the lane's option state is settled.
    log(f"filed {kind} rework round {round_no}: {rev_title} + {rr_title}")
    record_rework(lane, gate_code, round_no, [rev_title, rr_title], findings, state)

WORKDIR_FACTS = "workdir.json"          # written per run, beside its other state
_DRIFT = set()                          # drift already reported, once per change


def workdir_facts():
    """Read-only reading of the tree a run stages into: repo, branch, HEAD.

    Every git call here READS. The board's only writes to any index are stage and
    unstage, so a branch that moved is something to report, never something to
    correct: switching it back would be a second writer fighting the operator, and
    a commit or a checkout is not the board's to make.
    """
    top = git_at(WORKDIR, "rev-parse", "--show-toplevel").strip()
    if not top:
        return {"repo": None, "workdir": os.path.abspath(WORKDIR)}
    return {"repo": top,
            "workdir": os.path.abspath(WORKDIR),
            "branch": git_at(WORKDIR, "rev-parse", "--abbrev-ref", "HEAD").strip()
                      or "DETACHED",
            "head": git_at(WORKDIR, "rev-parse", "HEAD").strip() or ""}


def record_workdir_facts():
    """Pin what the run started on. Once per run, at the first lane it opens."""
    path = os.path.join(RUN_DIR, WORKDIR_FACTS)
    if os.path.exists(path):
        return
    os.makedirs(RUN_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(workdir_facts(), f, indent=2)
    os.replace(tmp, path)


def expected_workdir_facts():
    try:
        with open(os.path.join(RUN_DIR, WORKDIR_FACTS)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def foreign_staged():
    """Staged paths in the work directory's repo that are NOT this board's.

    Only for a work directory the board does not own: inside this repo the index is
    shared with the operator's ordinary work on mission/ and that is normal, and the
    pathspecs in staged_files() already scope a gate's evidence. In ANOTHER
    repository every staged path is either this lane's or the operator's, and the
    operator's reaches the next card's `git diff --cached` and the gate's evidence.

    Reported, never unstaged: the board may unstage what it put there, but throwing
    away a human's pending work to tidy its own evidence is not a trade it gets to
    make.
    """
    exp = expected_workdir_facts()
    if not exp.get("repo"):
        return []
    if os.path.abspath(exp["repo"]).startswith(os.path.abspath(REPO) + os.sep) or \
            os.path.abspath(exp["repo"]) == os.path.abspath(REPO):
        return []
    staged = [ln for ln in git_at(WORKDIR, "diff", "--cached", "--name-only")
              .splitlines() if ln.strip()]
    # Both sides are relative to the same repository root: staged_files() also runs
    # git -C WORKDIR, so `--name-only` gives paths from that repo's top.
    own = set(staged_files())
    return [p for p in staged if p not in own]


def workdir_drift(state=None):
    """Report a work directory that moved under a live run. Findings, not fixes.

    A branch switched mid-run moves where a gate's evidence would land, and the HEAD
    the gate recorded goes stale without anything noticing — which is the one thing
    that makes the gate's record untrue rather than merely incomplete.
    """
    exp = expected_workdir_facts()
    if not exp.get("repo"):
        return []
    now = workdir_facts()
    out = []
    if now.get("branch") and exp.get("branch") and now["branch"] != exp["branch"]:
        out.append(f"the work directory moved from branch {exp['branch']} to "
                   f"{now['branch']} while this run was live — a gate's recorded "
                   f"evidence names the branch it staged into, so this run's record "
                   f"is no longer true of {exp['repo']}")
    if now.get("head") and exp.get("head") and now["head"] != exp["head"]:
        out.append(f"{exp['repo']} moved from {exp['head'][:7]} to "
                   f"{now['head'][:7]} while this run was live — something committed "
                   f"or reset under the board")
    for p in foreign_staged():
        out.append(f"staged in {exp['repo']} but not this lane's: {p} — it reaches "
                   f"every later `git diff --cached` and the gate's evidence")
    for finding in out:
        if finding not in _DRIFT:
            _DRIFT.add(finding)
            log(f"WARNING: {finding}")
    return out


def commit_target():
    """Which repository and branch a gate's evidence is staged in, as one line.

    Matters when `default-workdir` points outside this repo. The authorization chain
    is "the driver stages, the human commits at the gate" — and with an external work
    directory that commit lands in ANOTHER repository, on whatever branch was checked
    out. A gate that does not say which cannot be acted on: the operator has to guess
    where to look, and a run's record does not say where its work went.
    """
    top = git_at(WORKDIR, "rev-parse", "--show-toplevel").strip()
    if not top:
        return f"{os.path.abspath(WORKDIR)} (not a git repository — nothing to commit)"
    branch = git_at(WORKDIR, "rev-parse", "--abbrev-ref", "HEAD").strip() or "DETACHED"
    head = git_at(WORKDIR, "rev-parse", "--short", "HEAD").strip() or "no commits yet"
    own = os.path.abspath(top).startswith(os.path.abspath(REPO) + os.sep) or \
        os.path.abspath(top) == os.path.abspath(REPO)
    where = "this repo" if own else "an EXTERNAL repository"
    return f"{top} ({where}), branch {branch} at {head}"


def git_at(cwd, *args):
    """git in an arbitrary tree, empty string on failure — for reading only."""
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def staged_files():
    """Paths staged in WORKDIR plus this board's artifact files — the evidence
    a gate records in place of a SHA.

    The pathspec is load-bearing. `git -C <dir> diff --cached` reports the whole
    REPOSITORY, not the directory, so without it a gate would record another
    board's staged work as this lane's output. Plausible-looking wrong
    evidence at the one place a human is asked to trust the driver.
    Intermediates (refined idea, plan) live under runs/artifacts/, not WORKDIR,
    and gates record them too — so both pathspecs are required.
    """
    # Only pathspecs inside the work directory's OWN repository. git runs -C
    # WORKDIR, and a path outside that repo drops it into --no-index mode, where
    # --cached is not even a valid option — so an external default-workdir made this
    # raise and took the gate's evidence with it. The hand-offs are in the kanban
    # repo, gitignored and never staged, so for an external tree there is nothing of
    # ours in that index to ask about.
    pathspecs = [WORKDIR]
    artifacts = os.path.join(RUN_DIR, "artifacts")
    top = git_at(WORKDIR, "rev-parse", "--show-toplevel").strip()
    if top and os.path.abspath(artifacts).startswith(os.path.abspath(top) + os.sep):
        pathspecs.append(artifacts)
    out = git("diff", "--cached", "--name-only", "--", *pathspecs)
    return [l for l in out.splitlines() if l.strip()]

def runs_result(card_id):
    """Last completed run's summary/result for this card (fallback when the
    card's result field is empty)."""
    out = kb("runs", card_id)
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("→"):
            return s[1:].strip()
    return ""

def verdict(state, prefix):
    t, c = title_of_prefix(state, prefix)
    if not c or c["status"] != "done":
        return ""
    return c.get("result") or c.get("summary") or (runs_result(c["id"]) if c.get("id") else "")

def verdict_token(text):
    """"PASS" or "REJECT" — the FIRST occurrences of the tokens, wherever
    they sit in the prose. The bodies mandate the result BEGIN with the
    verdict, but reviewers drift ("Lane-1 implementation review PASS: ...",
    E2E-2's RVa), and a gate that requires startswith() stalls the lane
    waiting for a verdict that is actually there. Whichever token appears
    FIRST wins; REJECT before PASS reads as a rejection.
    """
    m = re.search(r"\b(REJECT|PASS)\b", text or "")
    return m.group(1) if m else ""


def rejection_findings(text, limit=4000):
    """The findings after the first REJECT token, whatever punctuation follows it.

    `split("REJECT:")` raised IndexError on a verdict written "REJECT — …" and
    stalled the lane one traceback per tick; verdict_token already accepts that
    spelling, so the findings reader must too. The cap keeps a card body sane; the
    revision card points at the full verdict.
    """
    m = re.search(r"\bREJECT\b[\s:—–-]*", text or "")
    return (text[m.end():] if m else (text or "")).strip()[:limit]


def is_rework(text):
    """The idea gate's send-back: the result's first word is REWORK, in any case."""
    return bool(re.match(r"\s*REWORK\b", text or "", re.IGNORECASE))


def rework_answers(text, limit=4000):
    return re.sub(r"^\s*REWORK\b[\s:—–-]*", "", text or "", flags=re.IGNORECASE).strip()[:limit]


def held_by_verdict(state, kind, lane):
    """A card behind a verdict waits for the verdict, not only for the card.

    P follows the idea gate and TI the implementation review. Both parents
    complete whatever they decided, so parents_done() alone let P start on an
    idea the human had sent back (REWORK) and TI run against code RVa had
    rejected — in the very tick that filed the rework round, before any hold.
    """
    if kind == "p":
        return is_rework(latest_verdict(state, lane, "Gi", "Gi"))
    if kind == "ti":
        return verdict_token(latest_verdict(state, lane, "RVa", "Gc")) != "PASS"
    return False


def md_section(text, name):
    """Body of the `## name` section of a markdown file, up to the next heading."""
    m = re.search(rf"^#+[ \t]*{re.escape(name)}\b[^\n]*\n(.*?)(?=^#+[ \t]|\Z)",
                  text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


def gate_action(state, title, kind, lane):
    opts = lane_options(lane) or {}
    auto = bool(opts.get("auto-gates"))
    if kind == "gi":
        # No reviewer card precedes this gate — the refinement's check IS a
        # person reading it, which is the whole point of putting a gate here.
        # So the only evidence the driver can record is that the artifact
        # exists; the judgement is the human's and is never inferred.
        refined = os.path.join(RUN_DIR, "artifacts", f"lane-{lane}", "refined.md")
        if not os.path.exists(refined) or not open(refined).read().strip():
            return f"waiting: no refined idea at {refined}"
        # Structural evidence: the researcher is the lane's sole factual
        # authority, so the gate checks the hand-off's REQUIRED sections exist,
        # not just that the file is non-empty. Missing sections = the researcher
        # skipped its job; the gate holds and says what is missing.
        text = open(refined).read()
        missing = [s for s in lanes.REFINED_SECTIONS
                   if not re.search(rf"^#+\s*{re.escape(s)}\b", text, re.IGNORECASE | re.MULTILINE)]
        if missing:
            return f"waiting: refined idea missing section(s): {', '.join(missing)}"
        # Count Findings bullets only: the old scan ran to the end of the file and
        # counted Success-criteria bullets as environment facts.
        n_findings = len(re.findall(r"^[-*]\s+\S", md_section(text, "Findings"), re.MULTILINE))
        if n_findings == 0:
            return "waiting: refined idea Findings section is empty — no environment facts to plan against"
        evidence = (f"refined idea present, all sections, "
                    f"{n_findings} finding(s) with evidence ({os.path.getsize(refined)} bytes)")
    elif kind == "gp":
        verdict_txt = latest_verdict(state, lane, "RVp", "Gp")
        if verdict_token(verdict_txt) != "PASS":
            return f"waiting: plan review verdict = {verdict_txt[:40]!r}"
        # The plan review reads the plan by PATH, so the index count here is
        # context, not the subject: "plan staged (0 files)" read as a
        # contradiction in the run summary of 2026-09-11.
        evidence = f"plan verdict PASS ({len(staged_files())} file(s) staged)"
    else:  # gc
        final = "RVc" if state.get(lanes.card_title("RVc", lane)) else "RVa"
        verdict_txt = latest_verdict(state, lane, "RVa", "Gc", final_code="RVc")
        if verdict_token(verdict_txt) != "PASS":
            return f"waiting: final review verdict = {verdict_txt[:40]!r}"
        staged = staged_files()
        evidence = (f"{len(staged)} files staged, verdict PASS; "
                    f"to commit in: {commit_target()}")
        if title not in _ANNOUNCED:
            log(f"GATE {title.split(':')[0]} evidence: {evidence}; "
                f"staged: {', '.join(staged[:8])}")
        write_timing_report(lane)
        preserve_artifacts()
    if auto:
        cid = card_id(state, title)
        if state[title]["status"] == "blocked":
            kb("unblock", cid)
        kb("complete", cid,
           "--result", f"auto-gate (lane {lane}): {evidence}. NOTHING COMMITTED.",
           "--summary", f"auto-gate {title.split(':')[0]} — no commit")
        log(f"GATE {title.split(':')[0]}: auto-completed — nothing committed")
    elif title not in _ANNOUNCED:
        # Once per gate, not once per tick. gate_action runs every pass while a
        # gate is held, so announcing unconditionally produced one identical
        # line every 21 seconds for as long as a human took to look — which is
        # exactly long enough to bury anything real in the log.
        log(f"HUMAN GATE READY: {title} — {evidence}. "
            f"Commit at your discretion, then: hermes kanban --board {BOARD} "
            f"complete {card_id(state, title)}")
    _ANNOUNCED.add(title)
    return "gate-held"

def record_timing(state):
    """Append one JSONL line: per-card status snapshots for timing analysis.
    Every process start emits a run-boundary marker so the report can split
    multiple replays in one file."""
    if not hasattr(record_timing, "_started"):
        with open(TIMING_PATH, "a") as f:
            f.write(json.dumps({"run_boundary": True,
                                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                                "epoch": time.time(),
                                "argv": sys.argv[1:]}) + "\n")
        record_timing._started = True
    snap = {t: {"status": c["status"], "id": c["id"]} for t, c in state.items()}
    # enrich cards whose status CHANGED since last tick with their runs
    # data (spawns/elapsed/budget) — self-contained evidence, no CLI at
    # report time; only fires on transitions, so cost is a handful of calls
    cache = getattr(record_timing, "_prev", {})
    for t, c in list(snap.items()):
        prev = cache.get(t)
        if prev is not None and prev.get("status") == c["status"]:
            continue
        runs = runs_util.board_runs(BOARD, c["id"])
        closed = [r for r in runs
                  if r.get("outcome") in ("completed", "gave_up")
                  and r.get("ended_at") and r.get("started_at")]
        if closed:
            last = closed[-1]
            c["last_run"] = {"outcome": last.get("outcome"),
                             "elapsed_min": round(runs_util.elapsed_min(last), 2),
                             "started": last.get("started_at")}
        if any(r.get("outcome") == "gave_up" for r in runs):
            c["gave_up"] = True
        full = state.get(t) or c
        if full is not c:
            full.update(c)          # keep the enriched last_run/gave_up
            full = {**state[t], **full}
        card_log(full)
    record_timing._prev = {t: {"status": c["status"], "last_run": c.get("last_run")}
                           for t, c in snap.items()}
    entry = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
             "epoch": time.time(), "cards": snap}
    with open(TIMING_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

def _card_log_entry(card):
    """Self-contained record for the project card log: the card's INPUT
    (body as filed, assignee, skill) and its RESULT (result/summary, run
    history, comments). Written on every status change, appended in full —
    JSONL, one complete line per event."""
    r = {"id": card["id"], "title": card.get("title"), "status": card.get("status"),
         "assignee": card.get("assignee"), "result": card.get("result"),
         "body": card.get("body"), "at": datetime.datetime.now().isoformat(timespec="seconds"),
         "epoch": time.time()}
    runs = runs_util.board_runs(BOARD, card["id"])
    r["runs"] = [{"outcome": x.get("outcome"),
                  "elapsed_min": round(runs_util.elapsed_min(x), 2),
                  "summary": (x.get("summary") or "")[:400],
                  "started": x.get("started_at")} for x in runs]
    try:
        att = kb("attachments", card["id"]).strip()
        r["attachments"] = att.splitlines() if att else []
    except Exception:
        r["attachments"] = None
    return r


def card_log(card):
    """Append the card's full record (input + result) to
    boards/<slug>/runs/cards/<card-id>.jsonl — one line per status change,
    so a card's whole history lives in the project, not in a mach DB."""
    try:
        os.makedirs(CARDS_DIR, exist_ok=True)
        path = os.path.join(CARDS_DIR, f"{card['id']}.jsonl")
        with open(path, "a") as f:
            f.write(json.dumps(_card_log_entry(card)) + "\n")
    except Exception as e:
        log(f"WARNING: card log failed for {card.get('id')}: {e}")


_OPENED = set()


def open_lane(state, lane):
    """Resolve lane <lane> the moment its turn comes. Once per lane per run.

    Returns "open" (lane may run) or "stopped" (no idea entered).
    """
    if lane in _OPENED:
        return "open"
    opts = lane_options(lane)
    if opts is None:
        log(f"LANE {lane}: no idea entered ({IDEAS_DIR}/lane-{lane}.md) — chain stops here")
        return "stopped"
    if not opts["integration-tests"]:
        for code in lanes.IT_CODES:
            title = lanes.card_title(code, lane)
            card = state.get(title)
            if card and card["status"] != "done":
                kb("archive", card["id"])
                log(f"LANE {lane}: integration-tests=no — archived {code}{lane}")
        gc = state.get(lanes.card_title("Gc", lane))
        rva = state.get(lanes.card_title("RVa", lane))
        rvc = state.get(lanes.card_title("RVc", lane))
        if gc and rvc:
            # archiving RVc does NOT drop the RVc -> Gc dependency edge; left
            # in place the gate waits forever on an archived parent.
            try:
                kb("unlink", rvc["id"], gc["id"])
            except RuntimeError as e:
                log(f"LANE {lane}: unlink RVc{lane}->Gc{lane} skipped ({e})")
        if gc and rva:
            # same reasoning as the unlink above: _OPENED is in-memory, so a
            # crash mid-prune replays this on restart and the duplicate link
            # must not abort the tick and leave the lane permanently unopened
            try:
                kb("link", rva["id"], gc["id"])
                log(f"LANE {lane}: relinked RVa{lane} -> Gc{lane}")
            except RuntimeError as e:
                log(f"LANE {lane}: link RVa{lane}->Gc{lane} skipped ({e})")
    if not opts["unit-tests"]:
        # TW only — RVa is the CODE review and the only one before the code gate
        # (lanes.UT_CODES says why). Its child C must be reparented to the plan
        # gate, or it waits forever on an archived parent, the same failure the
        # RVc -> Gc unlink above exists to avoid.
        tw = state.get(lanes.card_title("TW", lane))
        c = state.get(lanes.card_title("C", lane))
        gp = state.get(lanes.card_title("Gp", lane))
        if tw and tw["status"] != "done":
            kb("archive", tw["id"])
            log(f"LANE {lane}: unit-tests=no — archived TW{lane}")
        if tw and c:
            try:
                kb("unlink", tw["id"], c["id"])
            except RuntimeError as e:
                log(f"LANE {lane}: unlink TW{lane}->C{lane} skipped ({e})")
        if gp and c:
            try:
                kb("link", gp["id"], c["id"])
                log(f"LANE {lane}: relinked Gp{lane} -> C{lane}")
            except RuntimeError as e:
                log(f"LANE {lane}: link Gp{lane}->C{lane} skipped ({e})")
    # Snapshot BEFORE unblocking: the card bodies already point at this path,
    # and workers must never read the mutable source (spec D8).
    os.makedirs(SNAP_DIR, exist_ok=True)
    snap = os.path.join(SNAP_DIR, f"lane-{lane}.md")
    tmp = snap + ".tmp"
    with open(tmp, "w") as f:
        f.write(opts["idea"])
    os.replace(tmp, snap)
    # The work directory AS THIS LANE FINDS IT. Written here rather than rendered
    # into the bodies at filing time, because every lane's cards are filed in one
    # moment: lane 2 would otherwise be told what the tree looked like before lane
    # 1 built anything in it. Same guarantee as the idea snapshot — written before
    # the root is unblocked, so no worker can read a missing or half-written file.
    # The cards were filed with THIS run's paths baked into their bodies. If the
    # driver is pointed at a different run — minted on a restart instead of at the
    # refile, or a hand-edited runs/current — every hand-off would be written where
    # nothing reads it and the idea gate would wait forever for a refined.md one
    # directory over. Checked here rather than trusted: the guarantee that a lane
    # cannot inherit a stale hand-off is only as good as this agreement.
    if not lane_paths_agree(state, lane):
        return "mismatch"
    record_workdir_facts()
    wd_state = file_lanes.workdir_state(WORKDIR, BOARD_DIR)
    # Beside the idea snapshot, in SNAP_DIR — the same directory
    # file_lanes.workdir_state_path renders into the card bodies.
    state_path = os.path.join(SNAP_DIR, f"lane-{lane}-workdir-at-open.md")
    tmp = state_path + ".tmp"
    with open(tmp, "w") as f:
        f.write(
            f"# Work directory as lane {lane} opened on it\n\n"
            f"Taken {datetime.datetime.now().isoformat(timespec='seconds')}, when "
            f"lane {lane} opened. This is a SNAPSHOT, not a live view: the tree "
            f"changes as this lane works, so for the current state run `git status` "
            f"in the directory itself. What it is for is planning — what was here "
            f"before this lane touched anything.\n\n"
            f"{os.path.abspath(WORKDIR)}\n\n{wd_state}\n")
    os.replace(tmp, state_path)
    idea_head = opts["idea"].splitlines()[0][:80] if opts["idea"] else ""
    log(f"LANE {lane} open: its={opts['integration-tests']} "
        f"uts={opts['unit-tests']} auto-gates={opts['auto-gates']} "
        f"snapshot={snap} workdir={wd_state.split(' — ')[0]} idea={idea_head!r}")
    # The idea text is NOT posted to the board: raw ideas stay off it, and a
    # comment would be a second, mutable copy of the contract.
    kb("comment", state[lanes.card_title("I", lane)]["id"],
       f"lane {lane} opened: integration-tests={opts['integration-tests']} "
       f"unit-tests={opts['unit-tests']} auto-gates={opts['auto-gates']}, "
       f"idea snapshot: {snap}")
    _OPENED.add(lane)
    return "open"


def rework_rounds(st):
    """File the next rework round wherever the newest finished verdict sent work back.

    Three loops, one shape: newest verdict → revision card + re-check card, linked
    to the gate, bounded, then escalation. tick() calls this BEFORE the next
    promotion pass, so a round's holds exist before a downstream card could start.
    """
    for lane in range(1, board_lane_count(st) + 1):
        # --- plan loop: Gp parked, newest plan-review verdict REJECT ---
        _, gp_card = title_of_prefix(st, f"Gp{lane}:")
        if gp_card and gp_card["status"] in ("blocked", "ready", "todo") \
                and not rework_hold(st, lane, "P", "Gp"):
            v_card, v = latest_verdict_card(st, lane, "RVp")
            if verdict_token(v) == "REJECT":
                rounds = len([t for t in st if t.startswith(f"P{lane}-rev")])
                if rounds < 3:
                    file_revision(st, lane, rounds + 1, rejection_findings(v), base="P",
                                  reviewer_prefix="RVp", gate_code="Gp",
                                  verdict_card_id=(v_card or {}).get("id"))
                else:
                    escalate(gp_card["id"], f"Gp{lane}",
                             "3 plan revision rounds exhausted — human escalation required")
        # --- code loop: Gc parked, newest implementation/final-review verdict REJECT ---
        # (RVa REJECT once had no loop at all: the gate waited forever, found live
        # 2026-09-09 23:19.)
        _, gc_card = title_of_prefix(st, f"Gc{lane}:")
        if gc_card and gc_card["status"] in ("blocked", "ready", "todo") \
                and not code_rework_hold(st, lane):
            v_card, v = latest_verdict_card(st, lane, "RVa", final_code="RVc")
            if verdict_token(v) == "REJECT":
                rounds = len([t for t in st if t.startswith(f"C{lane}-rev")])
                if rounds < 2:
                    file_coder_revision(st, lane, rounds + 1, rejection_findings(v),
                                        max_rounds=2, verdict_card_id=(v_card or {}).get("id"))
                else:
                    escalate(gc_card["id"], f"Gc{lane}",
                             "2 implementation rework rounds exhausted — human escalation required")
        # --- idea loop: P parked, newest idea-gate verdict REWORK ---
        _, p_card = title_of_prefix(st, f"P{lane}:")
        if p_card and p_card["status"] in ("blocked", "ready", "todo") \
                and not rework_hold(st, lane, "I", "Gi"):
            v_card, v = latest_verdict_card(st, lane, "Gi")
            if is_rework(v):
                rounds = len([t for t in st if t.startswith(f"I{lane}-rev")])
                if rounds < 2:      # 2 rounds: an idea needing three human
                                    # round-trips is a wrong idea
                    file_revision(st, lane, rounds + 1, rework_answers(v), base="I",
                                  reviewer_prefix="Gi", gate_code="Gi", max_rounds=2,
                                  verdict_card_id=(v_card or {}).get("id"))
                else:
                    escalate(p_card["id"], f"P{lane}",
                             "2 idea rework rounds exhausted — human escalation required")


# --- document chain -----------------------------------------------------------
# What each card was GIVEN and what it PRODUCED, so the hand-off chain can be
# checked instead of trusted: a card handed a document older than its own start
# read a leftover, and a worker that attached nothing produced
# nothing. runs/chain.jsonl is per-run state — rotated and cleared like the rest.
_CHAIN_STARTED = set()
_CHAIN_DONE = set()
WORKER_CODES = ("I", "P", "TW", "C", "TI")
# Review and gate cards carry a verdict; the ledger is where they outlive a run.
VERDICT_CODES = ("rv", "g")


def ledger(record):
    """Append one line to the board's verdict ledger.

    Run state, beside the chain: `runs/verdicts.jsonl` is rotated and cleared
    with everything else under runs/, and never staged — the board directory
    holds its DEFINITION only (board.json, lane-<k>.md, README). A rejection that
    exists only as prose in a closed card's result field is invisible; one JSON
    line per verdict and per rework round is what lets `mission/doc-chain.py`
    show, for the run in front of it, what the reviews decided and what they sent
    back.
    """
    if not BOARD:
        return          # see chain_record: no run, no ledger line, no repo dirt
    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "board": BOARD}
    rec.update(record)
    try:
        os.makedirs(BOARD_DIR, exist_ok=True)
        with open(VERDICTS_PATH, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError as e:
        log(f"ledger: cannot append to {VERDICTS_PATH} ({e})")


def lane_paths_agree(state, lane):
    """Does the lane's root card name the run the driver is writing to?

    The root's body carries its <IDEA> path from filing time. If it does not name
    the current run, the two disagree about where this lane's documents live, and
    nothing downstream can recover: the worker writes where its body says and the
    gate reads where the driver says.
    """
    title = lanes.card_title(lanes.lane_root_code(True), lane)
    card = state.get(title)
    if not card:
        return True                      # nothing filed yet; open_lane handles it
    body = card.get("body")
    if not body:
        return True                      # unreadable body is not evidence of drift
    expected = file_lanes.lane_paths(REPO, BOARD, lane, _read_current_run())["<IDEA>"]
    if expected in body:
        return True
    log(f"REFUSING to open lane {lane}: {title} was filed against a different run — "
        f"its body does not name {expected}. The driver is on run "
        f"{_read_current_run()!r}; a run is minted when an idea is ARMED, never on "
        f"driver start, so check runs/current and re-arm the idea rather than "
        f"letting the lane write where nothing reads.")
    return False


def chain_inputs(body, lane):
    """The lane documents a card's FILED body points at, by role.

    Parsed from the rendered body — evidence of what the card was told, not of
    what a later edit intended.
    """
    body = body or ""
    # THIS run's paths: a body filed under runs/<run-id>/ names that run, and
    # comparing against the run-less form matches nothing — the chain would record
    # every card as having been given no documents at all.
    return {role.strip("<>"): path for role, path
            in file_lanes.lane_paths(REPO, BOARD, lane,
                                     _read_current_run()).items() if path in body}


def chain_record(event, card, lane, ts=None, **extra):
    if not BOARD:
        # No board, no run: a process without BOARD (a test importing this
        # module, a stray call) must never drop run state into the repo. This is
        # the class behind the `boards/runs/` dirt the suite twice produced.
        return
    rec = {"ts": (ts or datetime.datetime.now()).isoformat(timespec="seconds"), "event": event,
           "lane": lane, "code": card["title"].split(":")[0], "card_id": card.get("id"),
           "title": card["title"], "status": card.get("status")}
    rec.update(extra)
    os.makedirs(RUN_DIR, exist_ok=True)
    with open(os.path.join(RUN_DIR, "chain.jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")


def record_chain_start(card, lane, observed=False):
    """One record per card as it leaves the parked state.

    `observed` marks a card someone else released — `start-board.sh --once`
    unblocks the lane root itself, and a human can unblock by hand — so the
    timestamp is the board's claim time rather than this process's unblock call.
    """
    if card["id"] in _CHAIN_STARTED:
        return
    _CHAIN_STARTED.add(card["id"])
    body = card.get("body") or ""
    ts = (datetime.datetime.fromtimestamp(card["started_at"])
          if isinstance(card.get("started_at"), (int, float)) else None)
    chain_record("start", card, lane, ts=ts, observed=observed,
                 inputs=chain_inputs(body, lane),
                 unresolved=sorted(set(re.findall(r"<[A-Z_]+>", body))))


def record_chain_starts(state):
    """Catch every card that started without a driver unblock: a hand-unblocked
    root, a resumed board, or a card the dispatcher claimed on its own."""
    for card in state.values():
        if card["status"] not in ("ready", "running", "done") or card["id"] in _CHAIN_STARTED:
            continue
        lane = card_id_lane(card["title"])
        if lane is not None:
            record_chain_start(card, lane, observed=True)


def record_chain_done(state):
    """One record per card the moment it finishes: what it attached, and the
    staged set at that moment (the lane's visible hand-off)."""
    for card in state.values():
        code = card["title"].split(":")[0]
        if card["status"] != "done" or card["id"] in _CHAIN_DONE:
            continue
        lane = card_id_lane(card["title"])
        if lane is None:
            continue
        _CHAIN_DONE.add(card["id"])
        try:
            ev = json.loads(kb("show", card["id"], "--json")).get("events", [])
            attached = [e.get("payload", {}).get("filename") for e in ev
                        if e.get("kind") == "attached"]
        except Exception as e:
            attached = []
            log(f"chain: attachments for {card['title'][:20]} unavailable ({e})")
        result = (card.get("result") or "").strip()
        attached = [a for a in attached if a]
        # What a review DECIDED belongs in the chain next to what it was given:
        # a verdict is the one hand-off that can send work backwards.
        verdict = ""
        if code.lower().startswith(VERDICT_CODES):
            verdict = "REWORK" if is_rework(result) else verdict_token(result)
        chain_record("done", card, lane, inputs=chain_inputs(card.get("body"), lane),
                     attached=attached, result=result[:200], verdict=verdict,
                     staged=sorted(staged_files()) if code in WORKER_CODES else [])
        if verdict:
            ledger({"event": "verdict", "lane": lane, "code": code, "card_id": card["id"],
                    "verdict": verdict, "attached": attached, "text": result[:600]})


def card_id_lane(title):
    """The lane a card title belongs to ('P1: …' -> 1), or None."""
    m = re.match(r"^[A-Za-z]+[a-z]*(\d+):", title)
    return int(m.group(1)) if m else None


_EMPTY_RESULT_NOTED = set()


def note_empty_results(state):
    """Name every finished worker card whose result is empty — once per run.

    The card bodies put the report in the RESULT field, but `kanban_complete`'s
    own schema prefers `summary`: on the 2026-09-11 run all three worker cards
    (P1, TW1, C1) landed their report in the summary and left `result` empty, and
    nothing surfaced it. Read-only: it changes no card.
    """
    noted = []
    for title, card in state.items():
        if title.split(":")[0].rstrip("0123456789") not in ("I", "P", "TW", "C", "TI"):
            continue
        if card["status"] != "done" or (card.get("result") or "").strip():
            continue
        if card["id"] in _EMPTY_RESULT_NOTED:
            continue
        _EMPTY_RESULT_NOTED.add(card["id"])
        noted.append(title.split(":")[0])
    if noted:
        log(f"NOTE: no --result on {', '.join(sorted(noted))} — their report is "
            f"in the summary field (see the card bodies' RESULT FIELD rule)")
    return noted


def open_lanes(state):
    """Open every lane whose turn has come, BEFORE anything is promoted.

    open_lane() used to run only from the root card's promotion branch, and that
    branch is skipped for any card that is not `blocked` — so a root someone else
    had already unblocked never opened its lane. `start-board.sh --once` used to
    unblock the root itself (and a human can unblock one by hand), so on an
    `integration_tests: false` board TI and RVc stayed live and RAN (live,
    2026-09-11), and no snapshot was refreshed.
    Opening here also means the lane's stale outputs are cleared on every entry
    path — a human continuing from a dirty state included.
    Returns True when the board changed, so the caller re-reads it.
    """
    changed = False
    for lane in range(1, board_lane_count(state) + 1):
        if lane in _OPENED:
            continue
        root = state.get(lanes.card_title(lanes.lane_root_code(True), lane))
        if not root or root["status"] in ("done", "archived"):
            continue
        if lane > 1 and not parents_done(state, [f"Gc{lane - 1}"]):
            continue
        if not lane_is_armed(lane):
            continue
        if open_lane(state, lane) == "open":
            changed = True
    return changed


def unstage_run_paths():
    """Every path under this board's runs/ stays unstaged (user rule).

    The lane's hand-offs are read by path, so the index is not how they travel; a card
    that stages one anyway only puts scratch in front of every later
    `git diff --cached` — the operator sees it and asks who did it. One git call per
    tick, and only when something is actually staged.

    RUNS_ROOT, not this run's directory: no run directory is ever deleted, so an
    earlier run's staged leftover is still in the index and still reaches every later
    diff.

    And in REPO, not WORKDIR. runs/ lives in the kanban repo; the driver's other git
    calls run -C WORKDIR, which for an external default-workdir is a DIFFERENT
    repository, where this pathspec means nothing — the call failed and the failure
    was swallowed, so the sweep quietly did nothing on exactly the boards whose index
    is shared with someone else's work.
    """
    rel = os.path.relpath(RUNS_ROOT, REPO)
    r = subprocess.run(["git", "-C", REPO, "diff", "--cached", "--name-only",
                        "--", rel], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return
    staged = r.stdout
    # unstage: the board's only writes to any index are stage and unstage, and this
    # one only ever touches paths it generated itself.
    subprocess.run(["git", "-C", REPO, "restore", "--staged", "--", rel],
                   capture_output=True, text=True)
    log(f"unstaged {len(staged.split())} path(s) under {rel} "
        f"(nothing run-generated stays in the index)")


def tick():
    st = state = board()
    record_timing(st)
    if halt_if_exhausted(st):
        return True          # truthy = board finished/stopped; serve loop halts
    esc_title, esc_card = escalated_to_triage(st)
    if esc_card is not None:
        escalate(esc_card["id"], esc_title.split(":")[0],
                 "the board escalated this card to Triage for a human — the lane "
                 "cannot advance by itself")
        return True
    workdir_drift(st)
    graph = lane_graph(st)
    # 0. open the lanes whose turn has come. Promotion below only ever looks at
    #    BLOCKED cards, so a root that was already unblocked (--once, or a human)
    #    would never open its lane — and open_lane is what prunes TI/RVc on an
    #    integration-tests=false board and refreshes the idea snapshot.
    if open_lanes(st):
        st = state = board()
    note_empty_results(st)
    # 1. handoff promotion: blocked card whose parents are all done -> unblock
    for title, parents, kind, lane in graph:
        card = st.get(title)
        if not card or card["status"] != "blocked":
            continue
        code = title.split(":")[0]
        root_code = lanes.lane_root_code(True)   # positional: first LANE_CARDS entry
        is_root = code == f"{root_code}{lane}"
        if is_root:
            # lane root (whatever card LANE_CARDS puts first — positional per
            # not hardcoded to the researcher): parents done (or
            # lane 1) AND an idea entered.
            if parents and not parents_done(st, parents):
                continue
            if not lane_is_armed(lane):
                continue        # prefilled, not running: waiting to be armed
            if open_lane(st, lane) == "stopped":
                continue
            st = state = board()   # archive/link above changed the board
        elif not parents or not parents_done(st, parents):
            continue
        if held_by_verdict(st, kind, lane):
            continue
        kb("unblock", card["id"])
        record_chain_start(card, lane)
        log(f"unblocked {title.split(':')[0]} (parents done)")
    st = state = board()
    # 1b. the document chain: a start record for every card that left the parked
    #     state, then one record per card as it finishes.
    record_chain_starts(st)
    record_chain_done(st)
    # 2. rework loops — FILE FIRST, so the holds below exist before promotion
    #    runs on the next card.
    rework_rounds(st)
    st = state = board()
    # 2b. rework holds: while an idea- or plan-rework round is live, the gate
    # guards its DOWNSTREAM card too — P/TW must not start on work the gate
    # has just sent back. Round cards were filed in step 2, so a hold exists
    # the moment the verdict lands; this is also the recovery path after a
    # driver restart mid-rework. Blocking needs ready/running; the downstream
    # card is blocked-by-parents here in the normal flow, so a no-op failure
    # is expected and harmless — skip it rather than spam the error log.
    # The code loop (RVa REJECT) is held by parents instead: lane_graph links a
    # filed round's C{lane}-rev / RVa{lane}-r<r> cards into RVa's and Gc's
    # parents, so the gate cannot open while the round is live. TI keeps its
    # verdict-based hold (held_by_verdict), which is the same guarantee.
    for lane in range(1, board_lane_count(st) + 1):
        for base, gate, downstream in (("I", "Gi", "P"), ("P", "Gp", "TW")):
            if not rework_hold(st, lane, base, gate):
                continue
            t, c = title_of_prefix(st, f"{downstream}{lane}:")
            if c and c["status"] in ("ready", "todo"):
                try:
                    kb("block", "--kind", "dependency", c["id"],
                       f"rework in flight: {gate}{lane} sent the work back")
                except RuntimeError as e:
                    log(f"LANE {lane}: hold on {downstream}{lane} skipped ({e})")
    # 3. gates
    for title, parents, kind, lane in lane_graph(st):
        if kind not in ("gi", "gp", "gc"):
            continue
        card = st.get(title)
        if not card or card["status"] == "done":
            continue
        if not parents_done(st, parents):
            continue
        if kind == "gc":
            clean_work_noise()
        msg = gate_action(st, title, kind, lane)
        if msg and msg not in ("gate-held", "skip"):
            # Once per distinct message per card, not once per tick: a gate
            # waiting on a rework round sits here for minutes, and the old path
            # wrote the identical line every tick (six in two minutes on
            # 2026-09-11) — the same spam the gate announcement was fixed for.
            if _WAITING.get(card["id"]) != msg:
                _WAITING[card["id"]] = msg
                log(f"{title.split(':')[0]}: {msg}")
    # done when every lane that HAS an idea reached its final gate
    last = 0
    for lane in range(1, board_lane_count(st) + 1):
        if lane_options(lane) is None:
            break
        last = lane
    if last == 0:
        return False
    # 4. last thing in the tick, so a card that just finished staging its
    #    hand-off does not leave it in the index for the operator to find.
    unstage_run_paths()
    _, gc = title_of_prefix(st, f"Gc{last}:")
    return bool(gc and gc["status"] == "done")




def file_coder_revision(state, lane, round_no, findings, max_rounds=2, verdict_card_id=None):
    """File one implementation-rework round: coder revision + RVa re-review,
    linked to Gc. Mirrors file_revision; findings text is phrased for the coder."""
    rev_title = f"C{lane}-rev-{round_no}: implementation revision round {round_no} - lane {lane}"
    rr_title = f"RVa{lane}-r{round_no + 1}: implementation re-review round {round_no + 1} - lane {lane}"
    if title_of_prefix(state, rev_title)[0]:
        return  # already filed
    gate_id = card_id(state, lanes.card_title("Gc", lane))
    runtime, render = _round_settings(lane)
    rbody = render("c-body.txt")
    rbody += (f"\nREVISION ROUND {round_no} of {max_rounds} (max {max_rounds}, then human "
              f"escalation).\n\nThe review returned the work. Address EXACTLY:\n{findings}\n"
              f"Fix only these, re-stage your files, re-attach, complete with a change summary.\n")
    rbody += _full_verdict_pointer(verdict_card_id)
    args = ["create", rev_title, "--body", rbody,
            "--assignee", lanes.assignee_for("coder", manifest().get("assignees")),
            "--workspace", f"dir:{WORKDIR}", "--max-runtime", runtime, "--max-retries", rework_retries(),
            "--idempotency-key", f"{BOARD}-rev-C{lane}-{round_no}",
            "--created-by", "manager", "--json"] + _skill_args("C") + _goal_args("coder", "C")
    rev_id = json.loads(kb(*args))["id"]
    rrbody = render("rva-body.txt")
    rrbody += (f"\nRE-REVIEW ROUND {round_no + 1} of {max_rounds + 1}. The previous review's "
               f"REJECT left findings on the parent revision card. Re-derive every check in this "
               f"body against the CURRENT staged index, run the suite yourself, and put the "
               f"verdict first in the result field: PASS: or REJECT:.\n")
    if state.get(lanes.card_title("RVc", lane)):
        # An RVc REJECT is re-reviewed by this card alone; without this the
        # lane's final review (full suite, staged set) would never be repeated.
        rrbody += ("This lane has integration tests, so this re-review is also its final "
                   "review: run the FULL suite — unit and integration — from a clean run, and "
                   "check the staged set and the success criteria as the final review does.\n")
    rr_args = ["create", rr_title, "--body", rrbody,
               "--assignee", lanes.assignee_for("reviewer",
                                                manifest().get("assignees")),
               "--parent", rev_id, "--workspace", f"dir:{WORKDIR}", "--max-runtime", runtime,
               "--max-retries", rework_retries(), "--idempotency-key",
               f"{BOARD}-rr-C{lane}-r{round_no + 1}", "--created-by", "manager", "--json"]
    rr_id = json.loads(kb(*rr_args))["id"]
    kb("link", rr_id, gate_id)
    log(f"filed code rework round {round_no}: {rev_title} + {rr_title}")
    record_rework(lane, "Gc", round_no, [rev_title, rr_title], findings, state)


def escalate(card_id, code, reason):
    """Escalate a rework loop that exhausted its rounds — once per run.

    The card is already blocked (parked is how it waits), and blocking a
    blocked card is a no-op the CLI reports as failure: the old path raised,
    main()'s catch-all logged it, and the next tick tried again — escalation
    spam instead of escalation. A comment is readable where the human is
    already looking; the in-memory set keeps it to one line per loop.
    """
    if code in _ESCALATED:
        return
    _ESCALATED.add(code)
    kb("comment", card_id, f"ESCALATION: {reason}")
    ledger({"event": "escalation", "code": code, "card_id": card_id,
            "findings": " ".join((reason or "").split())[:600]})
    log(f"ESCALATED: {code} — {reason}")
    # Escalation = rework rounds exhausted = the lane cannot advance by
    # itself; halt the board the way a gave_up trip does (same tick).
    if not _HALTED["reason"]:
        _HALTED["reason"] = f"{code}: {reason}"
        log(f"BOARD HALTED: {_HALTED['reason']}")
        try:
            with open(os.path.join(RUN_DIR, "halt.txt"), "w") as f:
                f.write(f"{BOARD} halted: {_HALTED['reason']}\n")
        except OSError:
            pass


def clean_work_noise():
    """`work/` holds what the idea asks a human to receive — nothing else.

    A suite run inside work/ leaves `__pycache__`/`.pytest_cache` behind (run 12
    did), and those then ride into the reviewer's staged-set check and the gate's
    evidence. One place, no card has to remember: removed before the code gate
    reads the index. Scratch belongs under runs/scratch/<card>/.
    """
    removed = []
    if not os.path.isdir(WORKDIR):
        return removed
    # Only a work directory the BOARD owns. With an explicit default-workdir the
    # tree belongs to another project, and a `__pycache__` there was almost
    # certainly not put there by this run — deleting someone's files to tidy our
    # own evidence is not a trade the board gets to make.
    if not os.path.abspath(WORKDIR).startswith(os.path.abspath(BOARD_DIR) + os.sep):
        return removed
    for root, dirs, files in os.walk(WORKDIR):
        for d in list(dirs):
            if d in ("__pycache__", ".pytest_cache"):
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                dirs.remove(d)
                removed.append(d)
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                try:
                    os.remove(os.path.join(root, f))
                    removed.append(f)
                except OSError:
                    pass
    if removed:
        log(f"work/: removed {len(removed)} cache artifact(s) — work/ is the human's output")
    return removed


def escalated_to_triage(state):
    """An ASSIGNED lane card sitting in Triage — the board's own escalation.

    The card that carries an idea into a lane is unassigned by design: that is
    what keeps the dispatcher from claiming it while a human is still typing.
    Every LANE card has an assignee. So an assigned card in triage is a card its
    worker could not complete and the board parked for a person
    (`block_loop_detected`, recurrences >= 2) — the lane cannot advance by
    itself, and the old behaviour was to poll forever with the last log line
    minutes old, which reads as a stall and hides the reason (2026-09-11: a
    stale gateway rejected every goal-mode completion, and the driver waited).
    """
    for title, card in state.items():
        if card.get("status") == "triage" and card.get("assignee"):
            return title, card
    return None, None


def halt_if_exhausted(st):
    """Stop the whole driver the moment any card gives up: retries exhausted,
    max_runtime reached, or a rework loop escalated.

    Three exhaustions leave evidence on a blocked card:
    (a) retries exhausted — dispatcher breaker trips the card into blocked
        (needs_input) with a gave_up run;
    (b) max_runtime reached — the worker is SIGTERMed at its runtime ceiling
        (timed_out); that halts only once the card is blocked, i.e. its retries
        are spent, never while the dispatcher is retrying it;
    (c) rework escalation — escalate() comments ESCALATION on the gate card
        after the revision rounds burn out.
    Any of them means the lane cannot advance by itself: driving on would
    only file more work against a broken step. One halt per run — log,
    write runs/halt.txt, deadman-notify; the serve loop exits.
    """
    if _HALTED["reason"]:
        return None
    # Exhaustion evidence lives in the card's EVENT history, not its list row:
    # `list --json` carries no runs, and the breaker appends gave_up/timed_out
    # events without a `blocked` event. A non-terminal card (not done/archived)
    # with a gave_up/timed_out event is exactly "the breaker tripped it" — a
    # done card keeps its history but must not re-halt a later run.
    for title, c in st.items():
        if c.get("status") in ("done", "archived"):
            continue
        p = _exhaustion_event(c["id"])
        # gave_up means the retries are spent. A timed_out attempt is final only
        # once the card sits blocked: while it is ready or running again the
        # dispatcher is retrying it — halting there cost three manual restarts
        # on 2026-09-10 (P1 twice, TW1), each on a card with retries left.
        if p is not None and (p.get("kind") == "gave_up" or c.get("status") == "blocked"):
            reason_txt = str(p.get("reason") or "")
            break
    else:
        for title, c in st.items():
            if c.get("status") != "blocked":
                continue
            p = _blocked_event_payload(c["id"])
            reason_txt = str((p or {}).get("reason") or "")
            if "ESCALATION" in reason_txt:
                break
        else:
            return None
    _HALTED["reason"] = f"{title}: {reason_txt or 'exhausted (see board)'}"
    # Distinguish machine-slow from provider-starved: a card whose worker log
    # shows upstream 4xx/5xx storms timed out because of the provider, not the
    # task's size — the restart decision changes.
    provider_hits = 0
    try:
        log_path = os.path.join(os.environ.get("HERMES_KANBAN_LOGS_DIR",
                os.path.join(hermes_kanban_dir(), "boards", BOARD, "logs")),
                f"{c['id']}.log")
        if os.path.exists(log_path):
            provider_hits = open(log_path, errors="replace").read().count("HTTP 4")                 + open(log_path, errors="replace").read().count("HTTP 5")
    except OSError:
        pass
    if provider_hits >= 3:
        _HALTED["reason"] += f" — provider-starved ({provider_hits} upstream 4xx/5xx in worker log)"
    log(f"BOARD HALTED: {_HALTED['reason']}")
    # The reason must be readable where the human looks first: on the card
    # itself, not only in runs/halt.txt or the driver log.
    try:
        kb("comment", c["id"], f"BOARD HALTED: {_HALTED['reason']}")
    except RuntimeError as e:
        log(f"WARNING: halt comment failed ({e})")
    notify_deadman(st)
    try:
        with open(os.path.join(RUN_DIR, "halt.txt"), "w") as f:
            f.write(f"{BOARD} halted: {_HALTED['reason']}\n")
    except OSError:
        pass
    return _HALTED["reason"]


_HALTED = {"reason": None}   # mutable holder: functions assign inner keys
_ESCALATED = set()   # gate codes already escalated this driver run


EXHAUSTION_KINDS = ("gave_up", "timed_out")


def _exhaustion_event(card_id):
    """Payload of the newest gave_up/timed_out event on a card, or None.

    The dispatcher breaker emits these when a card exhausts max_retries or is
    SIGTERMed at max_runtime (timed_out; gave_up follows when retries are also
    spent). Not a block event — the breaker writes its own kind — so the
    block-event reader cannot see it.
    """
    try:
        ev = json.loads(kb("show", card_id, "--json"))
    except Exception:
        return None
    for e in reversed(ev.get("events", [])):
        if e.get("kind") in EXHAUSTION_KINDS:
            payload = e.get("payload") if isinstance(e.get("payload"), dict) else {}
            return {"kind": e.get("kind"),
                    "reason": str(payload.get("error")
                                  or payload.get("outcome")
                                  or e.get("kind"))}
    return None


def _blocked_event_payload(card_id):
    """Latest block event payload, or None.

    block_task stores the reason and kind in the EVENT PAYLOAD, not in the
    task's result field — and `list --json` has neither key. Reading result
    text (as this used to) therefore matched nothing and the deadman never
    saw a genuinely stuck board.
    """
    try:
        ev = json.loads(kb("show", card_id, "--json"))
    except Exception:
        return None
    for e in reversed(ev.get("events", [])):
        if e.get("kind") in ("blocked", "block_loop_detected") and isinstance(e.get("payload"), dict):
            return e["payload"]
    return None


def block_reason(card):
    """'needs_input' when the card's latest block event was kind needs_input."""
    p = _blocked_event_payload(card["id"])
    if p and p.get("kind") == "needs_input":
        return "needs_input"
    return "other"


def is_parked(card):
    """Parked, not stuck: the driver's own 'awaiting lane activation' block,
    which is the parking brake on lanes not yet open — never human attention."""
    p = _blocked_event_payload(card["id"])
    return bool(p) and "awaiting lane activation" in str(p.get("reason") or "")

def notify_deadman(state):
    stuck = [f"{t.split(':')[0]}" for t, c in state.items()
             if c["status"] == "blocked"
             and block_reason(c) == "needs_input"
             and not is_parked(c)]
    msg = f"kanban-smoke DEADMAN: {len(stuck)} cards awaiting human input: {', '.join(stuck[:6])}"
    log(msg)
    with open(os.path.join(RUN_DIR, "deadman.txt"), "w") as f:
        f.write(msg + "\n")
    # Telegram if the manager gateway is configured; else the file suffices
    try:
        import urllib.request, urllib.parse
        tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat = os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0]
        if tok and chat:
            u = f"https://api.telegram.org/bot{tok}/sendMessage"
            data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
            urllib.request.urlopen(urllib.request.Request(u, data=data), timeout=10)
    except Exception:
        pass

def preserve_artifacts():
    """Copy every completed card's provenance patch into this run's own
    runs/<run-id>/patches/ so per-task diffs live next to the code commit they
    produced — and stay inside the board, like everything else it generates.

    No timestamp of its own: the run directory already names the run, and a second
    one inside it invited reading the inner name as a different run. Beside
    artifacts/, not inside it — artifacts/ holds the lane HAND-OFFS the chain stats,
    and a patch is not one.

    Called at each lane's code gate: the lane is finished, its cards are about
    to be archived by the next refile, and this is the last moment the patches
    are still collectable. They were written for exactly this and were never
    called (found reading, not running — the one finding of that kind here).
    """
    import shutil, glob
    out_dir = os.path.join(RUN_DIR, "patches")
    os.makedirs(out_dir, exist_ok=True)
    st = board()
    for title, card in st.items():
        cid = (card or {}).get("id")
        if not cid:
            continue
        for src in glob.glob(os.path.expanduser(
                f"~/.hermes/kanban/boards/{BOARD}/attachments/{cid}/*.patch")):
            dst = os.path.join(out_dir, f"{cid}.patch")
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                log(f"artifact kept: {os.path.relpath(dst, REPO)}")

def write_summary(state):
    """One-shot per-run summary: gate verdicts, per-card agent minutes, budget
    events, overhead ratio — one jq-able file per completed run."""
    import collections
    rows = {}
    total = 0.0
    for title, c in state.items():
        if c["status"] != "done":
            continue
        runs = runs_util.board_runs(BOARD, c["id"])
        mins = 0.0
        gave_up = None
        for r in runs:
            outcome = r.get("outcome")
            if outcome in ("completed", "gave_up"):
                mins += runs_util.elapsed_min(r)
                if outcome == "gave_up":
                    gave_up = True
        rows[title] = {"card_id": c["id"], "agent_min": round(mins, 2)}
        if gave_up:
            rows[title]["gave_up"] = True
        total += mins
    t0 = getattr(write_summary, "_t0", None) or time.time()
    wall = (time.time() - t0) / 60
    # agent_work_min sums EVERY closed run per card, including attempts made by
    # EARLIER driver processes (post-halt restarts reset budgets but history
    # stays). wall_min measures only the current process, so summing across
    # restarts can exceed wall (observed: overhead -2.3). Report both truths:
    # the unclamped sum (real labor across the run's lifetime) and a clamped
    # overhead at >= 0 (never negative — that reads as a bug to a human).
    agent_total = total
    overhead = max(0.0, wall - agent_total)
    summary = {
        "finished_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "wall_min": round(wall, 1),
        "agent_work_min": round(agent_total, 1),
        "overhead_min": round(overhead, 1),
        "cards": rows,
        "restarts_observed": agent_total > wall,
        "gates": {t.split(":")[0]: (c.get("result") or "")[:200]
                  for t, c in state.items() if re.match(r"^G[ipc]\d+:", t)},
        "lanes_with_ideas": [l for l in range(1, board_lane_count(state) + 1)
                             if lane_options(l) is not None],
        # Where this run's work is staged, and therefore where a gate commit lands.
        # A run whose work directory is another repository has to say so, or its
        # record does not describe where the deliverable went.
        "workdir": os.path.abspath(WORKDIR),
        "commit_target": commit_target(),
        "workdir_facts": expected_workdir_facts(),
        "workdir_drift": sorted(_DRIFT),
    }
    with open(os.path.join(RUN_DIR, "run-summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    log(f"summary written: {os.path.join(RUN_DIR, 'run-summary.json')} ({total:.0f} min agent work)")


_TIMED = set()
# Gates already announced this run — see gate_action.
_ANNOUNCED = set()
_WAITING = {}

# The triage card body file_ideas writes always opens with this line, so a card
# the human typed from scratch in the dashboard is distinguishable from one the
# driver seeded — and the lane it belongs to is stated rather than guessed.
_RAW_RE = re.compile(r"^RAW IDEA for lane (\d+)")

# Serve mode holds every lane until a human arms an idea. Set by adopt_and_refile.
_ARMED = False
# Idea cards already told they are invalid, keyed by card id -> the text that was
# wrong. The driver ticks every few seconds and a refusal is sticky (the card stays
# where the human dropped it), so without this the card collects one identical
# comment per tick. Re-editing the text re-reports, which is the point.
_REPORTED = {}


def lane_is_armed(lane):
    """May serve mode open this lane?

    Armed this session, or already opened by an earlier driver: the lane's
    snapshot is written by open_lane before it unblocks anything, so its
    existence is the durable record that this lane is under way. Without that
    second test a cron restart mid-run would refuse to promote the lane it was
    already driving, and the board would stall with no explanation.
    """
    if not SERVE or _ARMED:
        return True
    return os.path.exists(os.path.join(SNAP_DIR, f"lane-{lane}.md"))


def armed_ideas(state):
    """Triage cards the human has promoted out of Triage — the 'go' signal.

    An idea is typed over minutes; a daemon that acted the moment a card
    appeared would launch half a sentence. Moving the card out of Triage is a
    deliberate gesture, and the dashboard offers two: the card panel's
    `→ ready` button, or a drag into the Todo column. Both count — the button
    is the discoverable one (there is no `→ todo` button) and the drag is what
    a kanban habit reaches for.

    Being unassigned is what makes that safe. Every lane card carries an
    assignee and passes through `ready` on its way to a worker; an idea card
    has none, which is also why the dispatcher cannot claim one however it is
    moved. Without that test a lane card sitting in `ready` would be misread as
    a new idea and would refile the board out from under its own run.

    NB: the panel's `✨ Specify` and `⚗ Decompose` buttons also move a triage
    card on, but both rewrite it with an auxiliary LLM first. Never use them
    for an idea: they would rewrite the human's text before the researcher read
    it.

    Returns [(lane, idea_text, card_id)], lane order.
    """
    out, unnumbered = [], []
    for title, c in state.items():
        if c.get("status") not in ("todo", "ready") or not c.get("id"):
            continue
        if c.get("assignee"):
            continue
        body = c.get("body") or ""
        if not body.strip():
            continue
        m = _RAW_RE.match(body.strip())
        text = body.split("\n---\n", 1)[-1].strip() if m else body.strip()
        if not text:
            continue
        (out if m else unnumbered).append(
            (int(m.group(1)) if m else None, text, c["id"]))
    out.sort(key=lambda r: r[0])
    # A card typed from scratch carries no lane number; it takes the next free
    # slot in the order the board lists it, rather than being silently dropped.
    used = {lane for lane, _, _ in out}
    nxt = 1
    for _, text, cid in unnumbered:
        while nxt in used:
            nxt += 1
        used.add(nxt)
        out.append((nxt, text, cid))
    return sorted(out, key=lambda r: r[0])


def hermes_kanban_dir():
    """The dispatcher's kanban dir (boards/logs/db root), leak-safe like the
    DB-path probe: a profiled shell leaks HERMES_HOME, so probe both."""
    home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    if not os.path.isdir(os.path.join(home, "kanban", "boards")):
        alt = os.path.expanduser("~/.hermes")
        if os.path.isdir(os.path.join(alt, "kanban", "boards")):
            return os.path.join(alt, "kanban")
    return os.path.join(home, "kanban")

def validate_armed(armed):
    """Judge what the human just dragged, and say so ON the card. True to proceed.

    create-board.sh and start-board.sh validate board.json and every lane-<k>.md
    before they hand the board over, but an idea typed into a Triage card and
    dragged to Todo reaches filing without passing either. That is the one path
    where the author is present, so it is the one where a bad header must not
    become a log line: the driver ticks on, the card sits there, and a lane that
    never files looks exactly like a slow board.

    So the same `board_schema` that guards the files guards this, and the finding
    goes back as a comment on the card the human is looking at. The board refuses to
    file until the text is fixed — the card stays where it was dropped, so editing
    it and letting the next tick re-read it is the whole recovery.
    """
    problems = []
    manifest_problems = board_schema.validate(file_lanes.read_board(BOARD_DIR),
                                             where="board.json")
    for lane, text, cid in armed:
        found = [f"lane {lane}: {p}" for p in
                 board_schema.validate_idea(text, where=f"lane-{lane}.md")]
        if not found and not manifest_problems:
            continue
        problems.append((cid, lane, found + [f"lane {lane}: {p}"
                                            for p in manifest_problems]))
    if not problems:
        return True
    for cid, lane, found in problems:
        log(f"REFUSING refile: lane {lane}'s armed idea does not validate")
        for p in found:
            log(f"  - {p}")
        if _REPORTED.get(cid) == found:
            continue                      # already said, and nothing changed
        _REPORTED[cid] = found
        body = ("This idea does not validate, so the board did not file it:\n\n"
                + "\n".join(f"  - {p}" for p in found)
                + "\n\nEdit this card and the driver re-reads it on the next tick. "
                  "`python3 mission/board_schema.py --schema` lists every option; "
                  "a header is a whole line, `<!-- option: value -->`, and only the "
                  f"per-lane options {sorted(board_schema.PER_LANE)} may appear in an "
                  "idea.")
        try:
            kb("comment", cid, body)
        except Exception as exc:          # a comment must never stop the driver
            log(f"  (could not comment on {cid}: {exc})")
    return False


def adopt_and_refile(state):
    """Write armed ideas back to their files, archive the old run, file a fresh
    lane set. Returns True when the board was refiled.

    The card is the live idea and the file is the record: writing back keeps git
    history, the researcher's refined-idea hand-off and the snapshot exactly as
    they were when the file was the source of truth.
    """
    armed = armed_ideas(state)
    if not armed:
        return False
    if not validate_armed(armed):
        return False
    cfg = file_lanes.read_board(BOARD_DIR)
    lanes_n = cfg.get("lanes", 1)
    over = [l for l, _, _ in armed if l > lanes_n]
    if over:
        log(f"REFUSING refile: idea(s) for lane(s) {over} but board.json says "
            f"lanes={lanes_n} — raise it, or move those cards back to Triage")
        return False
    for lane, text, _cid in armed:
        dst = os.path.join(BOARD_DIR, f"lane-{lane}.md")
        with open(dst, "w") as f:
            f.write(text.rstrip() + "\n")
        log(f"adopted idea for lane {lane} -> {os.path.relpath(dst, REPO)}")
    # Archive everything, including the armed cards: file_ideas re-creates the
    # triage cards from the files we just wrote, so the loop closes on itself.
    ids = [c["id"] for c in state.values() if c.get("id")]
    if ids:
        kb("archive", *ids)
        # Verify rather than assume: a survivor of this archive is a card that
        # will be re-read as a new idea next tick and refile the board again.
        left = [c["id"] for c in board().values()
                if c["id"] in set(ids) and c.get("status") != "archived"]
        log(f"archived {len(ids) - len(left)}/{len(ids)} card(s) from the previous run")
        if left:
            log(f"WARNING: {len(left)} card(s) survived the archive: {', '.join(left)} "
                f"— archive them by hand before arming another idea")
    # One id for the cards' idempotency keys AND the run directory, so a card in
    # the engine names the directory holding its evidence.
    key = f"{BOARD}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    mint_run(key)
    made = file_lanes.file_board(BOARD, REPO, WORKDIR, lanes_n, key,
                                 max_runtime=cfg.get("max-runtime"),
                                 max_retries=cfg.get("max-retries"),
                                 targets=cfg.get("targets"), run_id=key,
                                 goal_max_turns=cfg.get("goal-max-turns"),
                                 assignees=cfg.get("assignees"))
    file_lanes.file_ideas(BOARD, REPO, BOARD_DIR, lanes_n, key, run_id=key,
                          workdir=WORKDIR)
    global _ARMED
    _ARMED = True
    _OPENED.clear()
    _TIMED.clear()
    # Per-RUN state, and a serve-mode driver answers many ideas. _DRIFT carried the
    # previous run's findings into this run's summary (and so failed it on E17 for
    # something that happened before it existed); _ANNOUNCED is keyed by card TITLE,
    # which repeats identically across runs, so a second run's human gate would never
    # announce itself.
    _DRIFT.clear()
    _ANNOUNCED.clear()
    _REPORTED.clear()
    log(f"refiled {len(made)} cards in {lanes_n} lane(s) — board ready")
    return True


def write_timing_report(lane):
    """Render the human-readable timing report when lane <lane> reaches its code
    gate — the end of the lane.

    Written BEFORE the gate is announced, because that gate is where a person
    decides whether to commit, and a report produced afterwards is evidence
    nobody used. run-summary.json is for machines; this is the table a person
    reads, and at the code gate it answers "what did this lane actually cost"
    while the answer can still change the decision.

    Once per lane per driver run: gate_action runs every tick while a gate is
    held, and rewriting the report under the reader is worse than not having it.
    """
    if lane in _TIMED:
        return
    _TIMED.add(lane)
    dst = os.path.join(RUN_DIR, f"timing-report-lane-{lane}.txt")
    r = subprocess.run([sys.executable,
                        os.path.join(REPO, "mission", "timing-report.py"),
                        "--board", BOARD],
                       capture_output=True, text=True)
    if r.returncode != 0:
        log(f"WARNING: timing report failed (non-fatal): {r.stderr.strip()[:200]}")
        return
    with open(dst, "w") as f:
        f.write(r.stdout)
    log(f"timing report written: {os.path.relpath(dst, REPO)}")

def pid_alive(held):
    """Is the pid a lockfile names still on this machine?

    A lock nobody holds is not a lock, so anything unreadable (empty file, a
    half-written pid, garbage) reads as dead: the file is only ever written with
    one pid, by os.write, immediately after creation."""
    try:
        pid = int(held)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:      # it exists, owned by someone else
        return True
    return True


def acquire_lock():
    """One driver per board. A lockfile, not a state machine — recovery stays
    'restart the driver and let its idempotent actions reconcile'.

    A DEAD holder's lockfile is taken over, not refused. The file is left behind
    by any driver that did not exit through the interpreter — SIGTERM/SIGKILL skip
    the atexit unlink — and refusing on the file's existence alone turns one kill
    into a manual `rm` before the board can restart, while every other guard says
    the board is free (observed 2026-09-12: start-board.sh's liveness check passed
    and run.py refused, so the restart silently did nothing)."""
    os.makedirs(RUNS_ROOT, exist_ok=True)
    path = os.path.join(RUNS_ROOT, "driver.lock")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        held = open(path).read().strip()
        if pid_alive(held):
            raise SystemExit(f"another driver holds {path} (pid {held}) — "
                             f"kill it or remove the lockfile")
        log(f"taking over a stale driver lock ({path}: pid {held!r} is gone)")
        fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    import atexit
    atexit.register(lambda: os.path.exists(path) and os.unlink(path))


def require_manifest():
    """A driver with no manifest would silently run git in the template repo for
    its whole life — the exact failure the template_root/workdir split exists to
    prevent. Fail at startup instead. Import stays cheap so the tests can import
    this module without a board."""
    if not os.path.exists(BOARD_CFG):
        raise SystemExit(
            f"no manifest at {BOARD_CFG} — create the board first:\n"
            f"  mission/create-board.sh --board boards/{BOARD}")


def reset_attempt_budgets():
    """A manual driver restart (re)opens every card's attempt budget.

    The dispatcher breaker persists consecutive_failures on the task row, so a
    card that exhausted max_retries stays over its limit FOREVER after a
    human restarts the driver — the human's restart IS the "try again"
    decision, so the budget must reset with the process. The timing side
    needs no reset: max_runtime is measured per run from its claim time, and
    every restart opens a fresh claim (dangling runs are reclaimed at
    connect). Only the two failure fields move; history stays.
    """
    import sqlite3
    hermes_home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    candidates = [os.path.join(hermes_home, "kanban", "boards", BOARD, "kanban.db")]
    leaked = os.environ.get("HERMES_HOME")
    for extra in ([os.path.expanduser("~/.hermes")] if leaked else []):
        alt = os.path.join(extra, "kanban", "boards", BOARD, "kanban.db")
        if alt not in candidates:
            candidates.append(alt)
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            conn = sqlite3.connect(path, timeout=30)
            with conn:
                cur = conn.execute(
                    "UPDATE tasks SET consecutive_failures = 0, "
                    "last_failure_error = NULL WHERE status != 'archived' "
                    "AND (consecutive_failures != 0 OR last_failure_error IS NOT NULL)")
            conn.close()
            if cur.rowcount:
                log(f"attempt budgets reset for {cur.rowcount} card(s)")
            return
        except sqlite3.OperationalError as e:
            log(f"WARNING: attempt-budget reset failed on {path}: {e}")


def main():
    if not BOARD:
        raise SystemExit("BOARD=<slug> is required — mission/start-board.sh sets it; "
                         "there is no default board")
    require_manifest()
    acquire_lock()
    # Say which run this process is on. A restart REJOINS the run runs/current
    # names — it must not mint one, because the cards already filed carry their
    # run's paths in their bodies and a new directory would leave every hand-off
    # pointing at a tree nothing writes to.
    joined = _read_current_run()
    if joined:
        log(f"rejoined run {joined}: {os.path.relpath(RUN_DIR, REPO)}")
    else:
        log("no run yet — the first armed idea mints one")
    reset_attempt_budgets()
    t0 = time.time()
    write_summary._t0 = t0          # wall_min in the summary is measured from here
    # A serving driver is a standing process; a 2h cap would drop the board every
    # two hours and leave the next idea unattended until cron noticed.
    timeout = None if SERVE else 120 * 60
    for a in sys.argv:
        if a.startswith("--timeout-min"):
            timeout = float(sys.argv[sys.argv.index(a) + 1]) * 60
    idle = False
    while True:
        try:
            # A new idea outranks the current tick: adopt it, refile, and let the
            # next pass drive the fresh cards.
            if SERVE and adopt_and_refile(board()):
                idle = False
                continue
            if tick():
                if _HALTED["reason"]:
                    log("BOARD HALTED — driver exiting; board state left "
                        "for human inspection")
                    return 1
                if not idle:
                    log("ALL GATES COMPLETE — scenario finished")
                    try:
                        st = board()
                        write_summary(st)
                    except Exception:
                        log("WARNING: summary generation failed (non-fatal)")
                if not SERVE:
                    return 0
                if not idle:
                    log("IDLE — waiting for a new idea (promote a Triage card to start)")
                    idle = True
        except Exception as e:
            import traceback
            log(f"ERROR: {e}\n{traceback.format_exc()}")
            # transient CLI/board errors are expected mid-run; keep driving
        # deadman: notify instead of silent stall. 'parked: awaiting lane
        # activation' is filed with kind needs_input on every NOT-yet-open
        # lane card — it is the parking brake, not human attention. Exclude
        # it, or the deadman fires on a healthy parked board every tick.
        st_now = board()
        ni = [c for c in st_now.values()
              if c["status"] == "blocked"
              and block_reason(c) == "needs_input"
              and not is_parked(c)]
        if len(ni) >= 2:
            log(f"DEADMAN: {len(ni)} cards blocked needs_input — human attention required")
            notify_deadman(st_now)
        if ONCE:
            return 0
        if timeout is not None and time.time() - t0 > timeout:
            log("timeout — stopping driver")
            return 1
        time.sleep(POLL)

if __name__ == "__main__":
    sys.exit(main())
