#!/usr/bin/env python3
"""Run ONE kanban card against a frozen input, on a board of its own.

Why this exists: proving a card body or a rework rule on the real board costs a whole
run — forty minutes and every earlier card's work — so engine changes were either
untested or tested by burning a lane. This takes the one thing a card actually needs,
its BODY TEXT, plus the one thing that text points at, a frozen hand-off, and runs it
alone. Nothing else of the source run is consulted: the card depends on nothing but the
text it is handed.

The board is real — its own `board.json` is copied from the source board, so the model,
provider, assignee and prompt resolution under test are the ones production uses — and
the card is filed with no parents, so no gate, lane or earlier round can influence it.

  tests/integration/replay_card.py --board <source-slug> --card RVp1
  tests/integration/replay_card.py --board <source-slug> --card RVp1 --plan <file> \\
      --model swift15-27b --provider llama-swap --timeout 900

Two modes, and the difference decides what the verdict is ABOUT:

  * STAGED (any `--plan`/`--refined`/`--idea`/`--findings`): the documents are copied into
    the replay root and every path the body names resolves there. Self-contained — the card
    depends on nothing but the text it is handed — which is what a fixture wants.
  * IN PLACE (the default with no frozen input): the body names the SOURCE run's real
    paths, so the card reads the live plan where the plan itself says it lives, and the
    reviewer's scratch lands in the real run's `scratch/`. This is the honest way to review
    a live artifact: staged, the plan legitimately names the source board's paths while the
    body named the replay's, and a reviewer duly reported that mismatch as a finding about
    the plan (measured 2026-09-27 — two live runs, three findings, all of them the harness).

Writes a JSON report (the assertions, the verdict, the wall time, the model the worker
actually ran) and keeps the board's card body for inspection; `--keep` leaves the whole
replay board in place.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
# Outside the repo on purpose: a replay board's runs/ and work/ are scratch, and the
# engine repo's own boards/ tree belongs to live runs — a helper staging by pathspec there
# picks up whatever it finds (measured 2026-09-27: replay dirs appeared staged in the
# shared working tree). KANBAN_REPLAY_ROOT moves it; the default is this session's scratch.
ROOT = os.environ.get("KANBAN_REPLAY_ROOT") or os.path.expanduser("~/.cache/kanban-replay")
sys.path.insert(0, os.path.join(REPO, "template"))
sys.path.insert(0, os.path.join(REPO, "driver"))
import board_schema                                    # noqa: E402
import card_render                                     # noqa: E402
import lanes                                           # noqa: E402
import run as driver                                   # noqa: E402  (the ledger's readers
# and rework_tail live there: a second copy here would drift from what production files)

# Which body file a card code reads, and who it is assigned to — from the one table the
# board itself files cards from, so a replay can never drift from the real assignment.
CARD_ROWS = {row[0]: row for row in lanes.LANE_CARDS}


def sh(*args, env=None, timeout=600, cwd=None):
    """One CLI call. Returns (rc, output) — never raises on a non-zero exit: a card that
    cannot even be filed is a result this harness reports, not a traceback."""
    e = dict(os.environ)
    e.pop("HERMES_HOME", None)          # a leaked HERMES_HOME makes kanban operations
    e.pop("GIT_DIR", None)              # refuse to file; a leaked GIT_DIR breaks git
    for k in [k for k in e if k.startswith("PYTEST")]:
        # A worker spawned under pytest inherits the marker, and the CLI's live-system
        # guard then refuses the production state.db and never loads the provider
        # config: the card dies with `Unknown provider '<the board's provider>'`.
        # Measured 2026-09-27 — the harness is meant to be driven BY a test, so its
        # children must not look like one.
        e.pop(k, None)
    if env:
        e.update(env)
    p = subprocess.run(args, capture_output=True, text=True, env=e, timeout=timeout, cwd=cwd)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def kanban(board, *args, **kw):
    return sh("hermes", "kanban", "--board", board, *args, **kw)


def model_flags(manifest, code, idea_path):
    """The `--model`/`--provider` pair production files this card with.

    One call path — `lanes.model_args` — so a replay cannot disagree with the board it
    copies: the board-level `model_override` wins for review cards, then the lane's idea
    header, then the board's own pair. This is also the path whose absence bit the live
    run on 2026-09-27: a card filed before a rename kept asking for the old model name,
    and a replay that invented its own resolution would have hidden that.
    """
    lane_cfg = {}
    parsed = lanes.read_idea(idea_path) if idea_path and os.path.isfile(idea_path) else None
    if parsed:
        headers = board_schema.headers_to_cfg(parsed[0])
        lane_cfg = {k: headers[k] for k in ("model", "provider") if k in headers}
    return lanes.model_args(code, manifest, lane_cfg)


def source_layout(args):
    """The paths the frozen input comes from, and the workdir a card runs in."""
    board_dir = os.path.join(REPO, "boards", args.board)
    manifest = card_render.read_board(board_dir)
    workdir = manifest.get("default-workdir") or os.path.join(board_dir, "work")
    if args.from_run:
        run_dir = args.from_run
    else:
        runs = os.path.join(board_dir, "runs")
        dirs = [os.path.join(runs, d) for d in os.listdir(runs)
                if d.startswith("run-") and os.path.isdir(os.path.join(runs, d))]
        run_dir = max(dirs, key=os.path.getmtime)      # newest run: its plan IS the
        # current revised plan, so a run with no --plan integrates the real artifact
    return board_dir, manifest, workdir, run_dir          # workdir = the SOURCE tree


def stage_frozen(args, manifest, workdir, run_dir, replay_dir, run_id, lane=1,
                 in_place=False):
    """Lay the replay run out exactly as a real lane's is laid out.

    Every path a body names resolves inside this directory tree, which is the whole
    trick: the card is handed the same absolute paths a production card gets, and a
    copy of the frozen documents sits at each of them.

    IN PLACE copies nothing: the run IS the source run, and `render_the_card` names it.
    """
    if in_place:
        real = os.path.join(run_dir, "artifacts", f"lane-{lane}", "plan.md")
        return run_dir, {"artifacts/lane-%d/plan.md" % lane: {"path": real, "from": real}}
    run = os.path.join(replay_dir, "runs", run_id)
    for sub in (f"snapshots", os.path.join("artifacts", f"lane-{lane}"),
                os.path.join("scratch", "unused")):
        os.makedirs(os.path.join(run, sub), exist_ok=True)
    os.makedirs(workdir, exist_ok=True)

    def take(name, explicit, source_default):
        dest = os.path.join(run, *name.split("/"))
        src = explicit or source_default
        if src and os.path.isfile(src):
            shutil.copyfile(src, dest)
            return dest, src
        return None, None

    frozen_dir = os.path.join(replay_dir, "frozen")
    os.makedirs(frozen_dir, exist_ok=True)
    # A staged document must name what the BODY names. A fixture that says `Spec: <REFINED>`
    # handed to a body whose <REFINED> resolved to the staged path reads to a reviewer as a
    # plan defect — a placeholder where a path belongs — and it reported exactly that
    # (measured 2026-09-27). Production plans carry resolved paths because their authors
    # read them from the body, so resolving them here is the faithful thing.
    replay_board = os.path.basename(os.path.normpath(replay_dir))   # stage_frozen gets the
    values = card_render.render_body_values(repo=REPO, board=replay_board,  # dir, not the slug
                                            workdir=workdir, lane=lane, targets=(),
                                            run_id=run_id, run_root=run)
    staged = {}
    for name, explicit in (("artifacts/lane-%d/plan.md" % lane, args.plan),
                           ("artifacts/lane-%d/refined.md" % lane, args.refined),
                           ("snapshots/lane-%d.md" % lane, args.idea)):
        dest, src = take(name, explicit, os.path.join(run_dir, *name.split("/")))
        staged[name] = {"path": dest, "from": src}
        if dest and os.path.isfile(dest):
            text = open(dest).read()
            for ph, val in values.items():
                text = text.replace(ph, val)
            open(dest, "w").write(text)
        if dest and name.endswith("plan.md"):
            pristine = os.path.join(frozen_dir, name.replace("/", "_"))
            shutil.copyfile(dest, pristine)      # AFTER resolution: the baseline the churn
            staged[name]["pristine"] = pristine  # measurement must be the one handed over
    # The reading of the work directory a lane opens with, and the tree itself: a review
    # that re-derives a build needs them, a plan review only needs the file to exist.
    take("snapshots/lane-%d-workdir-at-open.md" % lane, None,
         os.path.join(run_dir, "snapshots", "lane-%d-workdir-at-open.md" % lane))
    if not args.no_work:
        src = args.work_from or os.path.join(REPO, "boards", args.board, "work")
        if os.path.isdir(src):
            shutil.copytree(src, workdir, dirs_exist_ok=True)
    return run, staged


def render_the_card(args, board, workdir, run_id, run_root, lane=1):
    """The card's body text — the one input this whole harness is about.

    `run_root` is what puts every run-scoped path in the body UNDER the replay root.
    Without it the renderer builds them from `repo`, so a body staged under the replay
    root told the worker to read `<repo>/boards/<replay>/runs/...` — paths that do not
    exist, and inside the engine repo the harness exists to stay out of (measured
    2026-09-27: the worker went looking for the plan there).

    IN PLACE passes the SOURCE board and run with no `run_root`, so `<PLAN>`, `<REFINED>`
    and `<RUNS>` resolve to the real paths — the ones the plan's own text names.
    """
    row = CARD_ROWS.get(args.card)
    if not row:
        raise SystemExit(f"unknown card code {args.card!r}; known: {', '.join(CARD_ROWS)}")
    body_file, assignee = row[1], row[2]
    text = card_render.render_body(body_file, repo=REPO, board=board,
                                   workdir=workdir, lane=lane, targets=(),
                                   run_id=run_id, run_root=run_root)
    return text, assignee, body_file


# The items each review card judges, for checking a tick list against its own range.
REVIEW_CARDS = {"RVp", "RVa", "RVc"}
CHECK_ITEMS = {"RVp": [str(i) for i in range(1, 9)], "RVa": list("abcdef"), "RVc": list("abcde")}


# The ledger's readers are the DRIVER's (`verified_items`, `cited_items`, `frozen_items`):
# the harness judging a verdict by its own parser is how the two would come to disagree
# about what a verdict said — and a `1 (structure) — …` entry form, which the driver's
# reader accepts, was invisible to a stricter copy of it that lived here (measured
# 2026-09-27: a good six-item ledger read as one item).


def revision_churn(args, run, card_id, body_path):
    """Did the round fix its findings without rewriting the document?

    The goal is one round per fix: a round that regenerates everything reads the same as
    one that closed its findings, and the next round then re-opens ground nobody asked it
    to touch. So a revision replay reports (a) that the file CHANGED at all, (b) how much
    of it moved, and (c) whether text the verdict objected to is gone.
    """
    pristine = os.path.join(args.root, "frozen", "artifacts_lane-1_plan.md")
    frozen = pristine if os.path.isfile(pristine) else os.path.join(run, "artifacts", "lane-1", "plan.md")
    handoff = os.path.join(run, "scratch", card_id, "plan.md")
    out = {"changed": False, "shape": "no hand-off", "remaining": []}
    if not os.path.isfile(handoff):
        return out
    old_text = open(frozen).read() if os.path.isfile(frozen) else ""
    new_text = open(handoff).read()
    out["changed"] = old_text != new_text
    if not out["changed"]:
        return out
    import difflib
    diff = "".join(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True),
                                        n=0))
    added = removed = 0
    for ln in diff.splitlines():
        if ln.startswith("+++") or ln.startswith("---"):
            continue
        added += ln.startswith("+")
        removed += ln.startswith("-")
    out["added"], out["removed"] = added, removed
    out["shape"] = "REGENERATION" if added >= 100 and removed <= 1 else "surgical"
    out["remaining"] = [s for s in args.expect_gone if s in new_text]
    return out


def _file_hash(path):
    """A short content hash, None when the file cannot be read."""
    import hashlib
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except OSError:
        return None


def _normalised_hash(text):
    """A review's identity: whitespace-insensitive, case-insensitive."""
    import hashlib
    import re as _re
    return hashlib.sha1(_re.sub(r"\s+", " ", (text or "")).strip().lower()
                        .encode()).hexdigest()[:12]


def _prior_reviews(card_code):
    """The hashes of reviews this card already produced, newest fixtures on disk.

    A live reviewer answers differently every time; the same verdict twice, word for
    word, means the thing under test is not reviewing. That is cheap to assert and it is
    the one property a canned or cached answer cannot fake.
    """
    d = os.path.join(HERE, "verdicts")
    out = []
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name.startswith(card_code + "-") and name.endswith(".txt"):
                try:
                    text = open(os.path.join(d, name)).read().strip()
                except OSError:
                    continue
                if text:
                    out.append(_normalised_hash(text))
    return out


def assertions(result, card_code):
    """Structural checks on the verdict — never prose equality.

    A review's result is judged on its SHAPE: a verdict token first, findings that cite
    where they bite, and the tick list this change exists for. Prose changes every run;
    the shape is the contract.
    """
    text = (result or "").strip()
    items = CHECK_ITEMS.get(card_code, [])
    ticked = driver.verified_items(text)
    cited = driver.cited_items(text)
    frozen = driver.frozen_items(text)
    if card_code not in REVIEW_CARDS:
        # A worker card's result opens with CHANGED:/NO CHANGE: (the result-field
        # contract), never a verdict: only a review card has one to give.
        return {"worker_result_line": bool(re.match(r"^(CHANGED|NO CHANGE)\b", text)),
                "names_evidence": bool(re.search(
                    r"\.(md|py|js|ts|json|gradle|txt|yaml|yml)\b[^\n]{0,12}:\d+", text))
                or bool(re.search(r"\b(plan|step)\s*\d", text, re.I))}
    checks = {
        "verdict_token": bool(re.match(r"^(PASS|REJECT)\b", text)),
        # Only a REJECT must be addressable: a finding that names no line cannot be acted
        # on, so evidence is required there. A PASS cites checklist items and has no defect
        # to locate — demanding a line of every verdict failed a good PASS (measured
        # 2026-09-27: "PASS: checklist 1-8 hold ... VERIFIED: 1 — ...").
        "names_evidence": (not text.upper().startswith("REJECT")) or bool(
            re.search(r"\.(md|py|js|ts|json|gradle|txt|yaml|yml)\b[^\n]{0,12}:\d+", text))
            or bool(re.search(r"\b(check|item)\s*\(?[0-9a-f]\)?", text, re.I)),
        "tick_list_present": "VERIFIED:" in text,
        "tick_items_in_range": bool(ticked) and bool(items) and ticked <= {i.lower() for i in items},
        # The engine drops a tick whose item a finding names (driver.frozen_items), so this
        # one is a MODEL quality metric: a verdict that both ticks and rejects an item is
        # reported, never silently trusted. It is not asserted — real verdicts do it.
        "tick_disjoint_from_findings": not (ticked & cited),
    }
    checks["frozen_items"] = ",".join(sorted(frozen, key=driver.item_sort_key))
    if text.upper().startswith("REJECT"):
        checks["reject_has_findings"] = len(text) > 200
    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True, help="source board slug to copy board.json from")
    ap.add_argument("--card", default="RVp", help="card code to replay, e.g. RVp1, P1, C1")
    ap.add_argument("--from-run", help="source run dir (default: newest)")
    ap.add_argument("--plan", help="frozen plan.md to hand the card (default: from --from-run)")
    ap.add_argument("--refined", help="frozen refined.md")
    ap.add_argument("--idea", help="frozen idea snapshot")
    ap.add_argument("--work-from", help="work tree to copy in (default: the board's own work/)")
    ap.add_argument("--no-work", action="store_true", help="leave the work directory empty")
    ap.add_argument("--in-place", action="store_true",
                    help="name the SOURCE run's real paths (default when nothing is frozen)")
    ap.add_argument("--model", help="override the model (default: whatever board.json says)")
    ap.add_argument("--provider", help="override the provider")
    ap.add_argument("--timeout", type=int, default=900, help="seconds to wait for the card")
    ap.add_argument("--keep", action="store_true", help="leave the replay board behind")
    ap.add_argument("--findings", help="a frozen REJECT verdict: replay a REVISION card")
    ap.add_argument("--round", type=int, default=1, help="which rework round (default 1)")
    ap.add_argument("--expect-gone", action="append", default=[],
                    help="text the revision must have removed (repeatable)")
    ap.add_argument("--root", help="replay root (default ~/.cache/kanban-replay)")
    ap.add_argument("--dry-run", action="store_true",
                    help="stage, render and file the card, then stop before dispatch")
    ap.add_argument("--json", help="write the report here")
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    replay_board = f"replay-{args.card.lower().replace('-', '')}-{stamp}"
    args.root = os.path.join(args.root or ROOT, "boards", replay_board)
    run_id = f"run-{stamp}"
    lane = 1

    board_dir, manifest, src_workdir, run_dir = source_layout(args)
    replay_dir = os.path.join(ROOT, "boards", replay_board)
    os.makedirs(replay_dir, exist_ok=True)
    # IN PLACE is the default when nothing is frozen: a live plan names the run it came
    # from, so the body must name those same paths. Staged, the plan names the source
    # board's paths while the body named the replay's, and reviewers reported the
    # mismatch as findings about the plan (measured 2026-09-27, two runs).
    in_place = args.in_place or not (args.plan or args.refined or args.idea or args.findings)
    src_run_id = os.path.basename(os.path.normpath(run_dir))
    # in place the card works in the SOURCE tree: the plan builds there, and a reviewer
    # re-deriving a build must look at the tree the plan names, not an empty copy.
    workdir = src_workdir if in_place else os.path.join(replay_dir, "work")
    # The board is REAL: its manifest is the source board's, so model, provider, assignee
    # and prompt resolution behave exactly as production does. That is the point of
    # replaying on a board rather than in a bare prompt.
    live = dict(manifest)
    live["slug"] = replay_board
    with open(os.path.join(replay_dir, "board.json"), "w") as fh:
        json.dump(live, fh, indent=2, sort_keys=True)

    run, staged = stage_frozen(args, manifest, workdir, run_dir, replay_dir, run_id, lane,
                               in_place)
    body, assignee, body_file = render_the_card(
        args, args.board if in_place else replay_board, workdir,
        src_run_id if in_place else run_id, None if in_place else run, lane)
    if args.findings:
        # A revision card is its base card's body PLUS the round block the driver appends,
        # so the harness calls the driver's own function rather than restating its text:
        # a copy would drift from what production files, and the whole point is to test
        # what production files.
        os.environ["HERMES_KANBAN_BOARD"] = args.board
        findings = open(args.findings).read().strip()
        lead = {"P": "The plan review sent this back.",
                "C": "The implementation review returned the work."}.get(
                    args.card, "The review sent this back.")
        closing = {"P": "Re-stage, re-write the hand-off file in your scratch directory, "
                        "complete with a change summary.",
                   "C": "Re-stage your files, re-write your patch file, and complete with a "
                        "result that says what changed and names every test still failing."
                   }.get(args.card, "Re-stage and complete with a change summary.")
        body += driver.rework_tail(args.round, int(manifest.get("max-reworks") or 3),
                                   findings, lead, closing)
    body_path = os.path.join(replay_dir, f"card-body-{args.card}.txt")
    with open(body_path, "w") as fh:
        fh.write(body)

    rc, out = sh("hermes", "kanban", "boards", "create", replay_board,
                 "--default-workdir", workdir)
    if rc != 0 and "already exists" not in out:
        raise SystemExit(f"boards create failed ({rc}):\n{out}")

    # A review may not modify what it judges. In place the plan IS the live artifact, so
    # hash it either side of the run and report it: a replay that quietly rewrote a live
    # run's plan would be worse than a failed test.
    plan_path = os.path.join(run, "artifacts", f"lane-{lane}", "plan.md")
    plan_sha = [_file_hash(plan_path), None] if in_place else [None, None]

    t0 = time.time()
    argv = ["create", f"{args.card}: replay {os.path.basename(replay_board)}",
            "--body", body, "--assignee", assignee,          # the TEXT, as the driver passes it
            "--workspace", f"dir:{workdir}", "--json"]
    prod = model_flags(manifest, args.card, os.path.join(run, "snapshots", "lane-1.md"))
    log(f"production would file: {prod or '(none — the profile default)'}")
    pinned = prod
    if args.model or args.provider:                 # an explicit override: the test pins
        pinned = (["--model", args.model] if args.model else []) + \
                 (["--provider", args.provider] if args.provider else [])
        log(f"overridden to: {pinned}")
    argv += pinned
    rc, out = kanban(replay_board, *argv)
    if rc != 0:
        raise SystemExit(f"create failed ({rc}):\n{out}")
    card_id = json.loads(out[out.index("{"):out.rindex("}") + 1])["id"]

    if args.dry_run:
        log(f"dry run: card {card_id} filed from {body_path}; body starts: {body[:400]!r}")
        return 0

    # One dispatch pass: the same path production uses, and no parents means nothing else
    # can be ready — this card, or nothing.
    rc, out = kanban(replay_board, "dispatch", "--max", "1",
                     env={"HERMES_BIN": shutil.which("hermes") or "hermes"})
    log(f"dispatch: {out.strip().splitlines()[-1] if out.strip() else '(no output)'}")

    status, result, waited = None, "", 0
    while time.time() - t0 < args.timeout:
        time.sleep(10)
        waited = int(time.time() - t0)
        _, out = kanban(replay_board, "show", card_id)
        # The CLI prints these INDENTED (`  status:    done`, then a `Result:` header with
        # the verdict on the lines under it). A `^status:` anchor matched nothing, so every
        # finished card read as "?" and each run burned its whole timeout waiting for a
        # card that was already done — 30 minutes per replay, measured 2026-09-27.
        m = re.search(r"^\s*status:\s*(\S+)", out, re.M)
        status = m.group(1) if m else "?"
        if status in ("done", "blocked", "archived"):
            r = re.search(r"^\s*Result:\s*\n(.*?)(?=\n\s*(?:Events|Runs|Comments|"
                          r"Attachments|Body)\b|\Z)", out, re.M | re.S)
            result = (r.group(1) if r else "").strip()
            break

    checks = assertions(result, args.card)
    plan_sha[1] = _file_hash(plan_path) if in_place else None
    if in_place:
        checks["plan_untouched"] = plan_sha[0] == plan_sha[1]
    churn = None
    if args.findings:
        churn = revision_churn(args, run, card_id, body_path)
    prior = _prior_reviews(args.card)
    report = {"board": replay_board, "card": args.card, "card_id": card_id,
              "review_hash": _normalised_hash(result),
              "previous_reviews": len(prior),
              "distinct_from_previous": _normalised_hash(result) not in prior,
              "status": status, "waited_s": waited, "model_flags": pinned,
              "in_place": in_place, "plan_sha": plan_sha,
              "source_run": run_dir, "frozen": {k: v["from"] for k, v in staged.items()},
              "body": body_path, "checks": checks, "churn": churn,
              "all_checks_pass": all(checks.values()),
              "verdict": result[:2000]}
    log(json.dumps(report, indent=2)[:4000])
    if result.strip():
        fixtures = os.path.join(HERE, "verdicts")
        os.makedirs(fixtures, exist_ok=True)
        with open(os.path.join(fixtures, f"{args.card}-{stamp}.txt"), "w") as fh:
            fh.write(result)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(report, fh, indent=2)
    if not args.keep:
        shutil.rmtree(replay_dir, ignore_errors=True)      # under ROOT, never in the repo
        # the STORE board goes through the CLI: removing its directory behind the CLI's
        # back left boards listed as "(empty)" forever (measured 2026-09-27)
        # Unpacked: `sh(("hermes", ...))` hands subprocess a TUPLE, which raises TypeError —
        # and it raised AFTER the report was written, so every run left its store board
        # behind and no test ever saw it (measured 2026-09-27: three lingering boards).
        rc, out = sh("hermes", "kanban", "boards", "rm", replay_board, "--delete")
        log(f"teardown: board {replay_board} rm rc={rc} {out.strip()[-60:]}")
        if in_place:
            # The synthetic card's scratch lives in the SOURCE run — production geometry,
            # which is the point of the mode — and a replay must not leave its card id in
            # a live run's tree.
            shutil.rmtree(os.path.join(run, "scratch", card_id), ignore_errors=True)
    return 0 if report["all_checks_pass"] else 1


def log(msg):
    print(msg, file=sys.stderr, flush=True)


if __name__ == "__main__":
    sys.exit(main())
