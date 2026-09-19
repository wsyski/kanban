#!/usr/bin/env python3
"""Run any board's card graph through Hermes BOTS instead of `hermes kanban`.

A second, parallel driver for the same boards `driver/run.py` runs: it reads the
same `board.json`, the same `lane-<k>.md`, the same card bodies and the same graph
(`template/lanes.py`), and turns each card into ONE `hermes … chat` turn on the
bot that owns that role. Nothing is filed on a kanban board, so every card's
conversation is an ordinary session on the profile — visible in Hermes Desktop's
Bots tab (bot row → Open recent session, or the bot's session browser).

What it keeps from kanban: the graph and its order, the card bodies verbatim
(worker contract included), gates and `auto-gates`, review verdicts and rework
rounds up to `max-reworks`, the review model pin, per-lane options from the idea
header, and one fresh context per card.

It shares the board's `work/` and `runs/` with the kanban driver: one product tree
per board, and one run directory tree whose ids say which driver made them
(`bots-<ts>` here, `<slug>-<ts>` there). `runs/current-bots` names this driver's
live run; `runs/current` stays kanban's alone. The two take the SAME
`runs/driver.lock`, so one BOARD is driven one way at a time — the lock is per
board, and other boards run concurrently in either mode.

What it does not have: the board's claim locks, the dispatcher's breaker, goal
mode (`goal-cards`), attachments, the chain/timing records and `run-audit.py`.
The card CONTRACT here is honoured by the bot or not at all — no process boundary
enforces it. This driver is for watching the work happen; `driver/run.py` stays
the one that proves it.

    bots/run-board.py --board boards/is-even            # run every lane
    bots/run-board.py --board boards/is-even --resume   # continue past a held gate
    bots/run-board.py --board boards/is-even --dry-run  # render prompts only
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "template"))

import board_schema  # noqa: E402
import card_render
import driver_lock  # noqa: E402  — the board's lock, shared with driver/run.py
import lanes  # noqa: E402

ADAPTER = os.path.join(REPO, "bots", "card-adapter.txt")

# Which card a REJECTION sends its work back to. The graph's chain says who follows
# whom; only the verdict knows whose output it just refused. Reviews and gates judge
# the same hand-offs, so a gate's target is the card that wrote what the human read:
# the refined idea (Gi), the plan (Gp), the code (Gc).
REWORK_TARGET = {"RVp": "P", "RVa": "C", "RVc": "TI",
                 "Gi": "I", "Gp": "P", "Gc": "C"}

GATE_HELD_EXIT = 10

# Manifest options the kanban driver acts on and this one cannot. `goal-cards` is the
# Ralph-style judge loop, which lives inside the hermes worker path (`--goal` at filing,
# `auxiliary.goal_judge` on the profile) rather than in the card body — there is nothing
# for a chat turn to switch on. `max-retries` is the dispatcher's per-card attempt
# budget, and this driver has no dispatcher. Named here so a run SAYS which parts of its
# manifest it honoured instead of diverging in silence.
UNHONOURED = {
    "goal-cards": "the goal judge runs inside the kanban worker, not in the card body",
    "max-retries": "the dispatcher's attempt budget; a bot card gets one turn",
}


# Cards in a fork run in threads, and two half-written log lines are worse than none.
_LOG_LOCK = threading.Lock()


def log(run, line):
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    text = f"{stamp} {line}"
    with _LOG_LOCK:
        print(text, flush=True)
        with open(os.path.join(run, "driver.log"), "a") as f:
            f.write(text + "\n")


def record_timing(run, row):
    """One line per card in `timing.jsonl` — what it cost, and on what.

    The driver's log already carries stamps, but subtracting them by hand is how a
    run's cost stays unknown. A card's own line says its seconds, its model and its
    verdict, so two runs of one board can be compared without reading either log.
    """
    with _LOG_LOCK:
        with open(os.path.join(run, "timing.jsonl"), "a") as f:
            f.write(json.dumps(row) + "\n")


def state_path(run):
    return os.path.join(run, "state.json")


def read_state(run):
    """This run's state, or a fresh one. A file that exists and cannot be PARSED is
    fatal and says so: it is what `--resume` continues from, and silently treating it
    as empty would re-run every card the run already paid for."""
    try:
        with open(state_path(run)) as f:
            return json.load(f)
    except OSError:
        return {"done": [], "held_gate": None}
    except ValueError as exc:
        raise SystemExit(
            f"{state_path(run)} is not readable JSON ({exc}) — it records which cards "
            f"finished, so this run cannot be continued. Its cards are in cards/, and "
            f"a run without --resume starts a fresh one.")


def write_state(run, state):
    """Written whole, then moved into place: a driver killed mid-write must not leave
    a truncated file where the resume state was."""
    path = state_path(run)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


# The bot driver's own pointer. `runs/current` belongs to the kanban driver and is
# what `run-audit.py`, `runs-report.py` and `unstarted_mint` resolve a board's live
# run through; a bot run that wrote it would make every one of them audit the wrong
# directory. Read-only here, and only to see whether a kanban run is live.
BOTS_POINTER = "current-bots"
RUN_PREFIX = "bots-"
DRY_PREFIX = "bots-dry-"


def take_driver_lock(runs):
    """`runs/driver.lock`, the board's ONE driver lock — the kanban driver's own rule.

    Both drivers build in the same `work/`, so they are mutually exclusive by
    construction rather than by convention: whichever holds this file runs the board.
    The rule (stale holder taken over, live holder refused, release only while the lock
    is still ours) lives in `template/driver_lock.py`, which both drivers import.
    """
    _, note = driver_lock.take(
        runs, "the kanban driver and this one share THIS board's work/, so one board is "
              "driven one way at a time (other boards are unaffected)")
    if note:
        print(note)


def current_run(board_dir, *, resume=False, dry_run=False):
    """This board's bot run directory — `runs/bots-<id>`, named by `runs/current-bots`.

    A RESUME never mints. The pointer is how `--resume` finds the run whose gate a
    human just accepted, and a mint here would silently restart the board from its
    first card with an empty `state.json` — the one failure a person meets rather
    than a developer. A DRY RUN never writes the pointer either: it renders into its
    own `bots-dry-<ts>` scratch so it cannot repoint a live run.
    """
    runs = os.path.join(board_dir, "runs")
    pointer = os.path.join(runs, BOTS_POINTER)
    if resume:
        run_id = ""
        if os.path.exists(pointer):
            with open(pointer) as f:
                run_id = f.read().strip()
        directory = os.path.join(runs, run_id) if run_id else ""
        if not directory or not os.path.isfile(os.path.join(directory, "state.json")):
            raise SystemExit(
                f"--resume found no run to continue ({pointer} names {run_id or 'nothing'}) "
                f"— start a run without --resume")
        return directory
    prefix = DRY_PREFIX if dry_run else RUN_PREFIX
    run_id = prefix + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    directory = os.path.join(runs, run_id)
    for sub in ("snapshots", "cards", "scratch", "artifacts"):
        os.makedirs(os.path.join(directory, sub), exist_ok=True)
    if not dry_run:
        with open(pointer, "w") as f:
            f.write(run_id)
    return directory


def render_card(body_file, card_id, *, board, workdir, lane, targets, run):
    """The card body every placeholder resolved, under the bot adapter."""
    # `run_root` is how every path a card body names — <RUNS>, <IDEA>, <PLAN>,
    # <REFINED> — lands under THIS run rather than under the kanban driver's.
    body = card_render.render_body(body_file, repo=REPO, board=board, workdir=workdir,
                                  lane=lane, targets=targets, run_root=run)
    with open(ADAPTER) as f:
        adapter = f.read()
    result_file = os.path.join(run, "cards", f"{card_id}.result.txt")
    header = f"{adapter}\n\n{'-' * 72}\n\n"
    text = header + body
    text = text.replace("<RESULT_FILE>", result_file)
    text = text.replace("<RUNS>", run)
    text = text.replace("<YOUR-CARD-ID>", card_id)
    return text, result_file


def session_title(cfg, lane, card_id, run):
    """The card session's title — STAMPED WITH THE RUN, so a rerun is a new session.

    It used to be `<slug> L<n> <card>`, and `-c <title> --create-if-missing` then RESUMED
    the previous run's conversation. Measured 2026-09-19: all six cards of a rerun picked up
    yesterday's session (RVa1 carried 151 messages), and the first call cost 95k tokens of
    history the card never asked for — the card's own prompt is what it should read. The
    slug stays first, so a session is still findable by board.
    """
    return f"{cfg['slug']} L{lane} {card_id} {os.path.basename(run)}"


def run_turn(profile, prompt_file, *, workdir, title, model_args, skill, budget, log_to):
    """One bot turn: the card's whole conversation, in its own session.

    The child's environment carries the suite hygiene every card body asks for and models
    keep forgetting: a card that runs pytest in the board's `work/` leaves `__pycache__`
    and `.pytest_cache` there, and on THIS driver that is an audit failure (B7) rather than
    the kanban side's note. Asking for it in prose has been measured not to work, so it is
    set where the child is spawned.
    """
    cmd = ["hermes", "-p", profile, "chat", "--in", workdir,
           "-c", title, "--create-if-missing",
           "--query-file", prompt_file, "-Q", *model_args]
    if skill:
        cmd += ["-s", skill]
    if budget:
        cmd += ["--run-budget", str(budget)]
    with open(log_to, "w") as out:
        try:
            proc = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT,
                                  env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                                       "PYTEST_ADDOPTS": "-p no:cacheprovider"},
                                  timeout=(budget + 300) if budget else None)
        except subprocess.TimeoutExpired:
            # The card is over its ceiling. Reported as a card that wrote no result —
            # the same halt as any other failed card, so `--resume` has a run to
            # continue from instead of a stack trace and no state.
            out.write(f"\n[driver] killed: no answer within {budget + 300}s\n")
            return None
    return proc.returncode


def read_result(result_file):
    """The card's result line, or None when the card never wrote one."""
    try:
        with open(result_file) as f:
            text = f.read().strip()
    except OSError:
        return None
    return text or None


def card_prompt_extra(reason, *, who="review"):
    """The revision note a rework round appends to the card it re-runs.

    One note for both rejections a lane can meet — a review's REJECT and a human's
    answer at a gate — because the card's job is identical either way: fix what the
    rejection names and nothing else. `who` only says whose words follow.
    """
    return ("\n\n" + "-" * 72 + f"\nREVISION ROUND — the {who} of your previous "
            "attempt REJECTED it. Fix exactly what it names, change nothing else, "
            f"and write your result as before. The {who} said:\n\n" + reason + "\n")


def run_card(*, code, card_id, body_file, role, skill, board, cfg, lane_cfg, lane,
             workdir, targets, run, extra="", dry_run=False):
    text, result_file = render_card(body_file, card_id, board=board,
                                    workdir=workdir, lane=lane, targets=targets, run=run)
    if extra:
        text += extra
    prompt_file = os.path.join(run, "cards", f"{card_id}.prompt.txt")
    with open(prompt_file, "w") as f:
        f.write(text)
    if dry_run:
        log(run, f"{card_id}: rendered {prompt_file} (dry run)")
        return "DRY RUN"
    if os.path.exists(result_file):
        os.remove(result_file)
    profile = lanes.assignee_for(role, cfg.get("assignees"))
    model = lanes.model_args(code, cfg, lane_cfg)
    budget = board_schema.duration_seconds(cfg.get("max-runtime")
                                           or board_schema.OPTIONS["max-runtime"][1])
    title = session_title(cfg, lane, card_id, run)
    transcript = os.path.join(run, "cards", f"{card_id}.transcript.txt")
    log(run, f"{card_id}: {lanes.LABELS.get(code, code)} on @{profile} "
             f"({' '.join(model) or 'profile model'}) — session {title!r}")
    started = time.time()
    rc = run_turn(profile, prompt_file, workdir=workdir, title=title, model_args=model,
                  skill=skill, budget=budget, log_to=transcript)
    seconds = round(time.time() - started, 1)
    result = read_result(result_file)
    record_timing(run, {"card": card_id, "code": code, "profile": profile,
                        "model": model[1] if model else "", "seconds": seconds,
                        "rc": rc, "session": title,
                        "result": (result or "").splitlines()[:1]})
    if result is None:
        why = "timed out" if rc is None else f"exit {rc}"
        log(run, f"{card_id}: NO RESULT ({why}) — transcript {transcript}")
        return None
    log(run, f"{card_id} [{seconds:.0f}s]: {result.splitlines()[0][:160]}")
    return result


def run_batch(cards, **kw):
    """Run these cards — together when the graph says they may — and return
    {card_id: result}. One thread per card; the turns are subprocesses, so the GIL
    costs nothing and a failed card is reported by its own `None` like any other."""
    if len(cards) == 1:
        card = cards[0]
        return {card["id"]: run_card(code=card["code"], card_id=card["id"],
                                     body_file=card["body"], role=card["role"],
                                     skill=card["skill"], **kw)}
    log(kw["run"], f"in parallel: {', '.join(c['id'] for c in cards)} "
                   f"— the lane's fork, which this board does not serialise")
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(cards)) as pool:
        futures = {c["id"]: pool.submit(run_card, code=c["code"], card_id=c["id"],
                                        body_file=c["body"], role=c["role"],
                                        skill=c["skill"], **kw)
                   for c in cards}
    return {card_id: f.result() for card_id, f in futures.items()}


def run_cost(run):
    """` — N card(s) in Xm Ys, slowest <card> (Zs)`, or "" when nothing was timed."""
    try:
        rows = [json.loads(line) for line in open(os.path.join(run, "timing.jsonl"))]
    except OSError:
        return ""
    if not rows:
        return ""
    total = sum(r["seconds"] for r in rows)
    worst = max(rows, key=lambda r: r["seconds"])
    return (f" — {len(rows)} card(s) in {int(total // 60)}m {int(total % 60)}s of model "
            f"time, slowest {worst['card']} ({worst['seconds']:.0f}s)")


def open_lane(board_dir, board, lane, workdir, run):
    """The lane's immutable inputs, written where every card body already points."""
    idea_path = os.path.join(board_dir, f"lane-{lane}.md")
    idea = lanes.read_idea(idea_path)
    if idea is None:
        raise SystemExit(f"lane {lane}: no idea entered in {idea_path}")
    headers, body = idea
    snapshot = card_render.lane_paths(REPO, board, lane, run_root=run)["<IDEA>"]
    os.makedirs(os.path.dirname(snapshot), exist_ok=True)
    with open(snapshot, "w") as f:
        f.write(body)
    state_file = card_render.workdir_state_path(REPO, board, lane, run_root=run)
    with open(state_file, "w") as f:
        f.write(card_render.workdir_state(workdir, board_dir) + "\n")
    os.makedirs(os.path.dirname(
        card_render.lane_paths(REPO, board, lane, run_root=run)["<PLAN>"]), exist_ok=True)
    return headers


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", help="boards/<slug>")
    ap.add_argument("--slug", help="board slug, when --board is omitted")
    ap.add_argument("--lane", type=int, help="run one lane instead of every lane")
    ap.add_argument("--resume", action="store_true",
                    help="continue the current run, PASSING the gate it stopped on")
    ap.add_argument("--rework", metavar="REASON",
                    help="answer the held gate with a REJECTION: the card that wrote "
                         "what you read is revised from REASON, then the gate is held "
                         "again for you to re-read")
    ap.add_argument("--dry-run", action="store_true", help="render prompts, run nothing")
    args = ap.parse_args()
    if args.rework and args.resume:
        raise SystemExit("--resume PASSES the held gate and --rework rejects it — one or the other")
    if args.rework is not None and not args.rework.strip():
        raise SystemExit("--rework needs a reason: it is what the revision is built from")

    board_dir = os.path.abspath(args.board or os.path.join(REPO, "boards", args.slug or ""))
    if not os.path.isdir(board_dir):
        raise SystemExit(f"no board at {board_dir}")
    cfg = card_render.read_board(board_dir)
    problems = board_schema.validate(cfg)
    if problems:
        raise SystemExit("\n".join(problems))
    board = cfg["slug"]

    # The SAME work directory the kanban driver builds in. A board's product has one
    # home: a bot run reads what the last run left exactly as `lane-<k>.md` says, and
    # `runs/driver.lock` is what keeps the two drivers out of each other's tree.
    workdir = os.path.abspath(cfg.get("default-workdir") or os.path.join(board_dir, "work"))
    os.makedirs(workdir, exist_ok=True)
    if not args.dry_run:
        take_driver_lock(os.path.join(board_dir, "runs"))
    run = current_run(board_dir, resume=args.resume or bool(args.rework),
                      dry_run=args.dry_run)

    state = read_state(run)
    log(run, f"bot-board {board}: run {os.path.basename(run)}, workdir {workdir}")
    # What the tree held when this run started. With one shared work/ it is the
    # difference between a run that improved the last one's product and one that
    # replaced it, and it is the first thing either driver's reader wants.
    log(run, f"work dir: {card_render.workdir_state(workdir, board_dir)}")
    for option, why in sorted(UNHONOURED.items()):
        if cfg.get(option) not in (None, [], board_schema.OPTIONS[option][1]):
            log(run, f"NOT honoured: {option} = {json.dumps(cfg[option])} — {why}. "
                     f"Run this board on driver/run.py for it.")
    if args.rework and not state.get("held_gate"):
        raise SystemExit("no gate is held in this run — there is nothing to reject")
    if args.resume and state.get("held_gate"):
        log(run, f"{state['held_gate']}: PASS from the human (--resume)")
        state["done"].append(state["held_gate"])
        state["held_gate"] = None
        write_state(run, state)
    elif args.resume:
        # No gate held, so this run HALTED — a card wrote no result, or one blocked.
        # `state.json` already names every card that finished, so the run continues at
        # the card that failed instead of re-buying the ones that did not.
        log(run, f"resuming a halted run at the first unfinished card "
                 f"({len(state['done'])} card(s) already done)")
    if args.rework:
        # Answered where the gate is reached, not here: the revision card, its body and
        # the lane's options are the lane loop's to resolve, and a gate is re-held
        # afterwards exactly as the board files a re-gate card.
        state["pending_rework"] = args.rework
        write_state(run, state)
        log(run, f"{state['held_gate']}: REWORK from the human — {args.rework[:120]}")

    targets = cfg.get("targets", [])
    lane_count = int(cfg.get("lanes", 1))
    if args.lane and not 1 <= args.lane <= lane_count:
        raise SystemExit(f"--lane {args.lane}: this board has {lane_count} lane(s)")
    lane_numbers = [args.lane] if args.lane else range(1, lane_count + 1)
    for lane in lane_numbers:
        headers = open_lane(board_dir, board, lane, workdir, run)
        lane_cfg = lanes.resolve_lane_options(cfg, headers, lane)
        cards = lanes.lane_cards(
            lane,
            integration_tests=lane_cfg["integration-tests"],
            unit_tests=lane_cfg["unit-tests"],
            assignees=cfg.get("assignees"),
            refinement=lane_cfg["refinement"],
            sequential=cfg.get("sequential", False))
        by_code = {c["code"]: c for c in cards}
        log(run, f"lane {lane}: {' -> '.join(c['id'] for c in cards)}")

        # A card runs when its PARENTS are done — the graph's own condition, not the
        # filing order. Two cards ready at once are the lane's fork (TW ∥ C), and they
        # run together; `sequential: true` already made C wait for TW in `lane_cards`,
        # so the manifest decides the overlap and nothing here has to re-read it.
        pending = [c for c in cards if c["id"] not in state["done"]]
        for card in cards:
            if card["id"] in state["done"]:
                log(run, f"{card['id']}: already done in this run")
        while pending:
            ready = [c for c in pending if all(p in state["done"] for p in c["parents"])]
            if not ready:
                log(run, f"HALT — no card can run: {', '.join(c['id'] for c in pending)} "
                         f"all wait on a card this run never finished")
                return 1
            gate = next((c for c in ready if c["role"] == "human-gate"), None)
            batch = [gate] if gate else ready
            results = run_batch(batch, board=board, cfg=cfg, lane_cfg=lane_cfg, lane=lane,
                                workdir=workdir, targets=targets, run=run,
                                dry_run=args.dry_run) if not gate else {}

            for card in batch:
                code, card_id = card["code"], card["id"]
                pending.remove(card)

                if card["role"] == "human-gate":
                    if board_schema.gate_is_auto(cfg.get("auto-gates"), code):
                        log(run, f"{card_id}: auto-gate — the manifest hands it to the driver")
                        state["done"].append(card_id)
                        write_state(run, state)
                        continue
                    reason = state.pop("pending_rework", None)
                    if reason:
                        target = REWORK_TARGET.get(code)
                        rounds = state.setdefault("gate_reworks", {})
                        done = rounds.get(card_id, 0)
                        cap = lanes.max_reworks(lane_cfg)
                        if not target or target not in by_code:
                            log(run, f"HALT — {card_id} has no card to send work back to")
                            write_state(run, state)
                            return 1
                        if done >= cap:
                            log(run, f"HALT — {card_id} rejected {done} time(s), the board's "
                                     f"cap; this is a human's call now, not another round")
                            write_state(run, state)
                            return 1
                        rounds[card_id] = done + 1
                        revision = by_code[target]
                        rev_id = f"{revision['id']}-gate-rev-{rounds[card_id]}"
                        log(run, f"{card_id}: rework round {rounds[card_id]}/{cap} on {rev_id}")
                        again = run_card(code=revision["code"], card_id=rev_id,
                                         body_file=revision["body"], role=revision["role"],
                                         skill=revision["skill"], board=board, cfg=cfg,
                                         lane_cfg=lane_cfg, lane=lane, workdir=workdir,
                                         targets=targets, run=run,
                                         extra=card_prompt_extra(reason, who="human gate"),
                                         dry_run=args.dry_run)
                        write_state(run, state)
                        if again is None:
                            log(run, f"HALT — {rev_id} reported nothing")
                            return 1
                    state["held_gate"] = card_id
                    write_state(run, state)
                    log(run, f"{card_id}: GATE HELD — read the lane's files, then answer: "
                             f"--resume to accept, --rework \"<reason>\" to send it back")
                    return GATE_HELD_EXIT

                result = results.get(card_id)
                if result is None:
                    log(run, f"HALT — {card_id} reported nothing")
                    return 1
                if result.upper().startswith("BLOCKED"):
                    log(run, f"HALT — {card_id} blocked: {result}")
                    return 1

                if code in lanes.JUDGE_CODES and result.upper().startswith("REJECT"):
                    target = REWORK_TARGET.get(code)
                    cap = lanes.max_reworks(lane_cfg)
                    rounds = 0
                    while target and rounds < cap and result.upper().startswith("REJECT"):
                        rounds += 1
                        revision = by_code[target]
                        rev_id = f"{revision['id']}-rev-{rounds}"
                        log(run, f"{card_id}: REJECT — rework round {rounds}/{cap} on {rev_id}")
                        again = run_card(code=revision["code"], card_id=rev_id,
                                         body_file=revision["body"], role=revision["role"],
                                         skill=revision["skill"], board=board, cfg=cfg,
                                         lane_cfg=lane_cfg, lane=lane, workdir=workdir,
                                         targets=targets, run=run,
                                         extra=card_prompt_extra(result),
                                         dry_run=args.dry_run)
                        if again is None:
                            log(run, f"HALT — {rev_id} reported nothing")
                            return 1
                        result = run_card(code=code, card_id=f"{card_id}-r{rounds}",
                                          body_file=card["body"], role=card["role"],
                                          skill=card["skill"], board=board, cfg=cfg,
                                          lane_cfg=lane_cfg, lane=lane, workdir=workdir,
                                          targets=targets, run=run, dry_run=args.dry_run)
                        if result is None:
                            log(run, f"HALT — re-review of {rev_id} reported nothing")
                            return 1
                    if result.upper().startswith("REJECT"):
                        log(run, f"HALT — {card_id} still rejects after {rounds} rework(s); "
                                 f"this is a human's call now")
                        return 1

                state["done"].append(card_id)
                write_state(run, state)

    log(run, f"ALL CARDS COMPLETE{run_cost(run)}")
    return 0


if __name__ == "__main__":
    # A board run is long enough that `timeout`, a service stop or a plain `kill` are as
    # likely as Ctrl-C, and a SIGTERM that unwinds through the same path releases the
    # board's lock (atexit) instead of leaving it for the next driver to take over.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # The lock releases through atexit either way; what a person needs here is the
        # sentence that says the run is not lost.
        print("\ninterrupted — the cards that finished are recorded; "
              "--resume continues this run", flush=True)
        sys.exit(130)
