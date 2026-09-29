#!/usr/bin/env python3
"""Run ONE card of an existing run, on a board of its own, and record it into that run.

  driver/run-card.py --run boards/<slug>/runs/<run> --card RVp1 [--keep]
  driver/run-card.py --run boards/<slug>/runs/<run>-try1 --card P1-rev-1

The run directory is the card's whole input: the card reads what the run holds and writes
back into it — hand-offs, artifacts, the work tree, and the driver's own records — as if it
had run on the full board. Keep a copy of the run (and the work tree) first if you want the
original: this overwrites what the card overwrites. Everything else is as usual: board.json
read live, the lane, the board's <WORKDIR>.
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
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "template"))
sys.path.insert(0, HERE)
import board_schema                                    # noqa: E402
import card_render                                     # noqa: E402
import driver_lock                                     # noqa: E402
import file_lanes                                      # noqa: E402
import lanes                                           # noqa: E402
import run                                             # noqa: E402
import runs_util                                       # noqa: E402

CARD_RE = re.compile(r"^(?P<code>[A-Za-z]+)(?P<lane>\d+)(?:-rev-(?P<rev>\d+)|-r(?P<rr>\d+))?$")
RR_KIND = {"RVp": "plan", "RVa": "code"}          # re-review rounds the driver files
CARD_ROWS = {row[0]: row for row in lanes.LANE_CARDS}
REV_KIND = {"P": "plan", "I": "idea", "C": "code", "TW": "code", "TI": "code"}
SENDERS = {"plan": "The plan review", "idea": "The idea gate", "code": "The review"}
# The file each card's body tells it to leave in its scratch directory.
HANDOFF = {"I": "refined.md", "P": "plan.md", "TW": "patch.diff", "C": "patch.diff",
           "TI": "patch.diff", "RVp": "review.md", "RVa": "review.md", "RVc": "review.md"}


def parse_card(arg):
    """`RVp1` -> ('RVp', 1, None, None); `P1-rev-2` -> ('P', 1, 2, None);
    `RVp1-r2` -> ('RVp', 1, None, 2)."""
    m = CARD_RE.match(arg or "")
    if not m:
        raise SystemExit(f"--card {arg!r}: expected <CODE><lane>[-rev-<n>|-r<k>], "
                         f"e.g. RVp1, C2, P1-rev-1, RVp1-r2")
    code, lane = m["code"], int(m["lane"])
    rev = int(m["rev"]) if m["rev"] is not None else None
    rr = int(m["rr"]) if m["rr"] is not None else None
    if code not in CARD_ROWS:
        raise SystemExit(f"--card {arg!r}: unknown card code {code!r}; "
                         f"known: {', '.join(CARD_ROWS)}")
    if CARD_ROWS[code][2] in lanes.NO_PROFILE_ROLES:
        raise SystemExit(f"--card {arg!r}: gates run no worker — the driver decides them, "
                         f"and ./test.sh tests that logic")
    if rev is not None and code not in REV_KIND:
        raise SystemExit(f"--card {arg!r}: {code} has no revision rounds")
    if rev == 0:
        raise SystemExit(f"--card {arg!r}: revision rounds start at 1")
    if rr is not None and (code not in RR_KIND or rr < 2):
        raise SystemExit(f"--card {arg!r}: re-review rounds are RVp<l>-r<k>/RVa<l>-r<k>, k >= 2")
    return code, lane, rev, rr


def card_title(code, lane, rev, rr=None):
    """The title the driver files this card under (file_revision / file_code_revision)."""
    if rr:
        return (f"RVp{lane}-r{rr}: plan review round {rr} - lane {lane}" if code == "RVp" else
                f"RVa{lane}-r{rr}: implementation re-review round {rr} - lane {lane}")
    if not rev:
        return lanes.card_title(code, lane)
    if code == "P":
        return f"P{lane}-rev-{rev}: plan revision round {rev} - lane {lane}"
    if code == "I":
        return f"I{lane}-rev-{rev}: idea refinement round {rev} - lane {lane}"
    what = run.CODE_REWORK_ROLES[code][2]
    return f"{code}{lane}-rev-{rev}: {what} revision round {rev} - lane {lane}"


def board_layout(run_dir):
    """(board_dir, runs_root, run_name) of `<board>/runs/<run>`."""
    run_dir = os.path.abspath(run_dir)
    runs_root = os.path.dirname(run_dir)
    board_dir = os.path.dirname(runs_root)
    if (os.path.basename(runs_root) != "runs" or not os.path.isdir(run_dir)
            or not os.path.isfile(os.path.join(board_dir, "board.json"))):
        raise SystemExit(f"{run_dir}: not a run dir — expected <board>/runs/<run> "
                         f"beside <board>/board.json")
    return board_dir, runs_root, os.path.basename(run_dir)


def _jsonl(path):
    if not os.path.isfile(path):
        return []
    with open(path) as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def done_before(run_dir, title):
    """The run's done cards as the board would hold them NOW: the newest card per title,
    in done order (chain.jsonl lines are append-only, so chronological), without the
    card under test's own title.

    No cutoff at the card's earlier start: the run as it stands IS the input, so an
    operator who runs RVp1 on a copy and then P1-rev-1 on the same copy gets the REJECT
    they just produced — a cutoff at P1-rev-1's original start would hide it."""
    cards = {}
    cards_dir = os.path.join(run_dir, "cards")
    for name in sorted(os.listdir(cards_dir)) if os.path.isdir(cards_dir) else ():
        entries = _jsonl(os.path.join(cards_dir, name))
        if entries:
            cards[entries[-1]["id"]] = entries[-1]
    order = [e["card_id"] for e in _jsonl(os.path.join(run_dir, "chain.jsonl"))
             if e.get("event") == "done" and e.get("card_id") in cards]
    newest = {}
    for cid in order:                 # a later done of the same title replaces the earlier
        c = cards[cid]
        if c.get("status") == "done" and c["title"] != title:
            newest.pop(c["title"], None)
            newest[c["title"]] = c
    return list(newest.values())


def _titled(cards):
    """The cards as the driver's readers take them: by title, in done order."""
    return {c["title"]: dict(c, completed_at=i + 1) for i, c in enumerate(cards)}


# Per loop, as driver.rework_rounds reads it: the reviewer whose newest verdict decides,
# the final-review code whose verdict counts too, and what a trigger looks like.
LOOPS = {"plan": ("RVp", None, "a REJECT from RVp{l}"),
         "idea": ("Gi", None, "a REWORK from Gi{l}"),
         "code": ("RVa", "RVc", "a REJECT from RVa{l}/RVc{l} with OWNER: {c}")}


def revision_trigger(prior, code, lane, rev):
    """What driver.rework_rounds would hand this revision round, read with the driver's
    own `latest_verdict_card`. Refuses when the run holds no trigger, and where
    production would escalate instead of filing the round."""
    kind = REV_KIND[code]
    reviewer, final, want = LOOPS[kind]
    state = _titled(prior)
    card, text = run.latest_verdict_card(state, lane, reviewer, final_code=final)
    name = f"{code}{lane}-rev-{rev}"
    if card is not None and not (card.get("result") or "").strip():
        # The driver would read the closing run's summary from the board the verdict ran
        # on; the run keeps 400 characters of it (cards/<id>.jsonl), not the verdict.
        raise SystemExit(f"{name}: {card['title'].split(':')[0]} completed with an empty "
                         f"result (summary only) — the run keeps no full verdict to file "
                         f"a revision from; on a copy, put it in cards/{card['id']}.jsonl's "
                         f"result")
    text = text or ""
    if run.UNPROBED_MARK in text:
        raise SystemExit(f"{name}: the newest RVp{lane} verdict is an {run.UNPROBED_MARK} — "
                         f"production files a probe retry for it, not a revision")
    if kind == "idea":
        ok = card is not None and run.is_rework(text)
    else:
        ok = (card is not None and run.verdict_token(text) == "REJECT"
              and (kind == "plan" or run.rework_owner(text) == code))
    if not ok:
        raise SystemExit(f"{name}: the run holds no trigger for it — needs "
                         f"{want.format(l=lane, c=code)}, newest is "
                         f"{card['title'] if card else 'nothing'}: {text[:120]!r}")
    cap = lanes.max_reworks(run.lane_options(lane))
    if rev > cap:
        raise SystemExit(f"{name}: max-reworks is {cap} — production escalates to a person "
                         f"instead of filing round {rev}")
    return {"card": card,
            "text": None if kind == "idea" else text,
            "findings": (run.rework_answers(text) if kind == "idea"
                         else run.rejection_findings(text)),
            "sender": SENDERS[kind],
            "judged": (run.judged_version(state, lane, code) if kind != "code" else None),
            "max_rounds": cap}


def rereview_trigger(prior, code, lane, rr):
    """What the driver held when it filed this re-review with its revision: the newest
    done revision round of the loop, and the version the review BEFORE it judged.

    Production files the re-review together with the revision, so `judged` is computed
    before that revision ran — here it is computed without the revision's own card.
    Refuses when the run holds no revision this round can follow."""
    kind = RR_KIND[code]
    pat = rf"^P{lane}-rev-(\d+):" if kind == "plan" else rf"^(?:C|TW|TI){lane}-rev-(\d+):"
    revs = [(c, int(m.group(1))) for c in prior for m in [re.match(pat, c["title"])] if m]
    if not revs:
        raise SystemExit(f"{code}{lane}-r{rr}: the run holds no done "
                         f"{'P' if kind == 'plan' else 'C/TW/TI'}{lane}-rev-<n> for it to re-review")
    rev_card, round_no = revs[-1]
    before = [c for c in prior if c["id"] != rev_card["id"]]
    state = _titled(before)
    if kind == "code" and rr != round_no + 1:
        raise SystemExit(f"{code}{lane}-r{rr}: the newest code revision is round {round_no}, "
                         f"so its re-review is RVa{lane}-r{round_no + 1}")
    if kind == "plan" and rr < round_no + 1:
        raise SystemExit(f"{code}{lane}-r{rr}: the newest plan revision is round {round_no}; "
                         f"its re-review is round {round_no + 1} or later")
    opts = run.lane_options(lane) or {}
    return {"rev_card": rev_card, "round_no": round_no,
            "max_rounds": lanes.max_reworks(opts or None),
            "judged": run.judged_version(state, lane, "P") if kind == "plan" else None,
            # the option open_lane prunes RVc/TI by — a pruned RVc's card log outlives it
            "final_review": kind == "code" and bool(opts.get("integration-tests", True))}


def check_result(code, text, scratch):
    """What the driver needs to read from this card's finish, and whether it can.

    `text` is what the driver READ — for a review, `latest_verdict_card`'s answer, which
    falls back to the run summary and reads an unprobed RVp PASS as a REJECT."""
    text = (text or "").strip()
    if code in lanes.JUDGE_CODES:
        checks = {"verdict_token": bool(run.verdict_token(text)),
                  "verified_items": bool(run.verified_items(text))}
        if code == "RVp":
            checks["probed"] = run.UNPROBED_MARK not in text
    else:
        checks = {"result_line": bool(re.match(r"^(CHANGED|NO CHANGE)\b", text))}
    if text.startswith("NO CHANGE"):
        return checks                 # an empty diff is not attached (worker contract)
    path = os.path.join(scratch, HANDOFF[code])
    checks["handoff"] = os.path.isfile(path) and os.path.getsize(path) > 0
    return checks


HERMES_BIN = shutil.which("hermes") or "hermes"
POLL_S = 10
GRACE_S = 300          # past --max-runtime: the dispatcher's own kill lands first


def hermes(*args, env=None, timeout=120):
    """One `hermes` call outside kb(): board create/rm and dispatch. Never raises.

    A worker spawned under pytest inherits PYTEST_* and the CLI's live-system guard then
    refuses the production state.db (measured 2026-09-27); a leaked HERMES_HOME/GIT_DIR
    breaks filing and git."""
    e = runs_util.cli_env()
    for k in [k for k in e if k.startswith("PYTEST")] + ["HERMES_HOME", "GIT_DIR"]:
        e.pop(k, None)
    e["HERMES_BIN"] = HERMES_BIN
    e.update(env or {})
    try:
        p = subprocess.run([HERMES_BIN, *args], capture_output=True, text=True, env=e,
                           timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def stop_worker(card_id):
    """Stop the card's worker if it is still alive — reset.sh's pattern. Neither this
    process ending nor the board's removal stops it, and one left running writes into the
    run after the lock is released."""
    try:
        subprocess.run(["pkill", "-f", f"work kanban task {card_id}"],
                       capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"could not stop the worker of {card_id} ({e}) — stop it by hand: "
              f"pkill -f 'work kanban task {card_id}'", file=sys.stderr)


def file_stubs(prior):
    """The upstream cards as the board held them: done, their result, their hand-offs.
    Filed blocked and assigned human-gate, then unblocked and completed — the order the
    driver's auto-gate completes a parked gate in (_gate_action)."""
    ids = {}
    for c in prior:
        sid = json.loads(run.kb("create", c["title"], "--body", c.get("body") or "",
                                "--assignee", "human-gate", "--initial-status", "blocked",
                                "--created-by", "coder", "--json"))["id"]
        run.kb("unblock", sid)
        run.kb("complete", sid, "--result", c.get("result") or "")
        for name in run.HANDOFF_NAMES:
            path = os.path.join(run.STATE.run_dir, "scratch", c["id"], name)
            if os.path.isfile(path) and os.path.getsize(path):
                run.kb("attach", sid, path)
        ids[c["title"].split(":")[0]] = sid
    return ids


def _only(card_id):
    return {t: c for t, c in run.board().items() if c["id"] == card_id}


def wait_for(cid, title, timeout_s):
    """Poll the one-card board until the card settles or `timeout_s` passes.

    Returns (status, one-card state). "timed out" leaves the worker to main's finally."""
    deadline = time.time() + timeout_s
    while True:
        time.sleep(POLL_S)
        st = _only(cid)
        run.record_timing(st)
        status = st[title]["status"] if title in st else "missing"
        if status in ("done", "blocked", "archived", "missing"):
            return status, st
        if time.time() > deadline:
            return "timed out", st


def run_one(code, lane, rev, rr, title, prior, trigger, slug, run_name, live):
    stubs = file_stubs(prior)
    prior_state = {c["title"]: c for c in prior}
    _, body_file, role, _ = CARD_ROWS[code]
    cfg = run.manifest()
    body = card_render.render_body(body_file, repo=run.REPO, board=slug,
                                   kanban_board=run.BOARD, workdir=run.WORKDIR, lane=lane,
                                   targets=cfg.get("targets") or (), run_id=run_name,
                                   run_root=run.STATE.run_dir)
    if rev:
        vcode = trigger["card"]["title"].split(":")[0]
        body = run.revision_body(
            body, REV_KIND[code], rev, trigger["max_rounds"], trigger["findings"],
            trigger["sender"], trigger["text"],
            run.revision_sources(trigger["judged"], trigger["card"]["id"]),
            run._full_verdict_pointer(stubs.get(vcode)))
    if rr:
        # Production files a re-review WITH its revision: base review body + the round's
        # paragraph, the review's model pin and nothing else (no --skill, no goal), and
        # the revision card as its parent.
        body += run.rereview_text(RR_KIND[code], trigger["round_no"], trigger["max_rounds"],
                                  rr_no=rr, judged=trigger["judged"],
                                  final_review=trigger["final_review"])
        links = [stubs[trigger["rev_card"]["title"].split(":")[0]]]
    elif rev:
        links = []                    # production files a revision round parentless
    else:
        parents = next((c["parents"] for c in lanes.lane_cards(
            lane, sequential=bool(cfg.get("sequential"))) if c["code"] == code), [])
        links = [stubs[p] for p in parents if p in stubs]
    runtime = cfg.get("max-runtime") or file_lanes.DEFAULT_MAX_RUNTIME
    extra = ((run.card_model_args(code, lane) if rr else
              run._goal_args(role, code)
              + run.card_model_args(code, lane)) + ["--initial-status", "blocked"])
    key = f"{run.BOARD}-{run_name}-card-{title.split(':')[0]}"
    # Blocked and parentless, then linked — file_board's order: a card created with
    # --parent is `todo` and does not take the block.
    cid = json.loads(run.kb(*run._create_args(title, body, role, key, runtime, extra)))["id"]
    live["cid"] = cid
    for p in links:
        run.kb("link", p, cid)
    if rev and REV_KIND[code] == "code":
        # file_code_revision keeps the tree the round starts from, for its churn line
        run.snapshot_lane_files(prior_state, lane, title.split(":")[0])
    st = _only(cid)
    run.record_timing(st)
    run.mark_attempt(st[title])
    run.kb("unblock", cid)
    run.record_chain_start(st[title], lane)
    rc_, out = hermes("kanban", "--board", run.BOARD, "dispatch", "--max", "1")
    print(f"dispatch: {out.strip().splitlines()[-1] if out.strip() else rc_}", file=sys.stderr)
    status, st = wait_for(cid, title, (board_schema.duration_seconds(runtime) or 3600) + GRACE_S)
    card = st.get(title) or {}
    scratch = os.path.join(run.STATE.run_dir, "scratch", cid)
    text, checks = card.get("result") or "", {}
    if status == "done":
        # The prior cards were attached on the board they ran on; given here only so the
        # churn line finds the version a revision was sent (by title, in its scratch).
        run.STATE.attached.update(c["id"] for c in prior)
        run.attach_hand_offs({**prior_state, **st})
        run.record_chain_done(st)
        if code in lanes.JUDGE_CODES:
            _, text = run.latest_verdict_card(st, lane, code)
        checks = check_result(code, text, scratch)
    report = {"card": title, "card_id": cid, "board": run.BOARD, "status": status,
              "verdict": run.verdict_token(text or "") or None,
              "owner": (run.rework_owner(text) if code in ("RVa", "RVc")
                        and run.verdict_token(text or "") == "REJECT" else None),
              "verified": sorted(run.verified_items(text or "")),
              "checks": checks, "scratch": scratch,
              "result": (card.get("result") or "")[:600]}
    print(json.dumps(report))         # one line, last: run.log() shares this stdout
    return 0 if status == "done" and checks and all(checks.values()) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True, help="<board>/runs/<run> — the card's input "
                    "and where its output lands")
    ap.add_argument("--card", required=True, help="<CODE><lane>[-rev-<n>|-r<k>], e.g. "
                    "RVp1, C1, P1-rev-1, RVp1-r2")
    ap.add_argument("--keep", action="store_true", help="leave the one-card board")
    a = ap.parse_args(argv)
    code, lane, rev, rr = parse_card(a.card)
    board_dir, runs_root, run_name = board_layout(a.run)
    slug = os.path.basename(board_dir)
    driver_lock.take(runs_root, "a driver or another run-card holds this board — stop it")
    kanban_board = f"{slug}-card-{a.card.lower()}-{time.strftime('%Y%m%d-%H%M%S')}"
    run.configure(kanban_board, board_dir, os.path.join(runs_root, run_name))
    title = card_title(code, lane, rev, rr)
    prior = done_before(run.STATE.run_dir, title)
    trigger = (revision_trigger(prior, code, lane, rev) if rev else
               rereview_trigger(prior, code, lane, rr) if rr else None)
    rc_, out = hermes("kanban", "boards", "create", kanban_board,
                      "--default-workdir", run.WORKDIR)
    if rc_ != 0:
        raise SystemExit(f"boards create {kanban_board} failed ({rc_}):\n{out}")
    live = {}
    try:
        return run_one(code, lane, rev, rr, title, prior, trigger, slug, run_name, live)
    finally:
        if live.get("cid"):
            stop_worker(live["cid"])  # --keep keeps a board, never a live worker
        if not a.keep:
            hermes("kanban", "boards", "rm", kanban_board, "--delete")


if __name__ == "__main__":
    sys.exit(main())
