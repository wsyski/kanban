"""Board filing: import ideas, file N parked lanes onto a hermes board."""
import json
import os
import subprocess

import lanes


def import_ideas(doc_path, ideas_dir, lane_count, force=False):
    sections = lanes.split_ideas(open(doc_path).read())
    if len(sections) > lane_count:
        raise ValueError(
            f"{doc_path}: {len(sections)} ideas but only {lane_count} lane(s) "
            f"— raise --lanes or trim the file")
    for i, text in enumerate(sections, start=1):
        target = os.path.join(ideas_dir, f"lane-{i}.md")
        if os.path.exists(target) and open(target).read().strip() and not force:
            raise ValueError(
                f"{target} already holds an entered idea — pass --force to overwrite")
        with open(target, "w") as f:
            f.write(text)
    return len(sections)


def kb(board, *args):
    r = subprocess.run(["hermes", "kanban", "--board", board, *args],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"kb {args[:2]}: {r.stderr.strip()[:300]}")
    return r.stdout


def file_board(board, repo, workdir, lane_count, key_prefix):
    """File lane_count full lanes, every card parked. Returns id map.

    Every lane is filed IT-complete; pruning happens at unblock time, when the
    lane's idea is known (spec D8).

    Cards are created parentless, blocked, and only THEN linked. That order is
    forced by hermes: block_task transitions only `running`/`ready` cards
    (kanban_db.py), so a card created with --parent is `todo` and silently
    refuses to block. A card left unblocked is not merely untidy — recompute_ready
    promotes any non-sticky card once its parents finish, so a worker could claim
    it before the driver ever resolved that lane. Parentless cards are `ready` at
    creation, the block takes, and it is sticky: only an explicit unblock releases
    it, and the driver's promotion loop is the only thing that issues one.

    So the whole board sits parked until the driver activates a lane, and every
    hand-off is the driver's decision rather than the dispatcher's.

    <WORKDIR> is where workers edit and stage; <IDEA> is the absolute path of the
    lane's immutable snapshot, which the driver writes before unblocking the root.
    """
    # absolutize here too: the manifest stores an absolute workdir, and a
    # relative --workdir would otherwise leave the filed cards disagreeing
    # with it about which tree they mean
    workdir = os.path.abspath(workdir)
    made = {}
    for lane in range(1, lane_count + 1):
        cards = lanes.lane_cards(lane, integration_tests=True)
        for card in cards:
            snapshot = f"{repo}/mission/runs/{board}/snapshots/lane-{lane}.md"
            body = open(f"{repo}/mission/card-bodies/{card['body']}").read()
            body = (body.replace("<WORKDIR>", workdir)
                        .replace("<BOARD>", board)
                        .replace("<IDEA>", snapshot)
                        .replace("<N>", str(lane)))
            args = ["create", card["title"], "--body", body,
                    "--assignee", card["assignee"], "--workspace", f"dir:{workdir}",
                    "--max-runtime", "60m", "--max-retries", "1",
                    "--idempotency-key", f"{key_prefix}-{card['id']}",
                    "--created-by", "manager", "--json"]
            if card["skill"]:
                args += ["--skill", card["skill"]]
            cid = json.loads(kb(board, *args))["id"]
            made[card["id"]] = cid
            kb(board, "block", "--kind", "needs_input", cid,
               "parked: awaiting lane activation")
        # edges last, so every card was `ready` when it was blocked
        for card in cards:
            if card["parent"]:
                kb(board, "link", made[card["parent"]], made[card["id"]])
    return made


def idea_title(text, lane):
    """The triage card's title: the idea's own `## ` heading, which already
    names it (`Idea 2: wordcount service`). Only headingless text needs a
    manufactured title."""
    for line in text.splitlines():
        if line.startswith("## "):
            return line[3:].strip()
    return f"Idea {lane}"


def file_ideas(board, repo, ideas_dir, lane_count, key_prefix):
    """One TRIAGE card per entered idea — the board's "Raw ideas" column.

    Triage is hermes's own intake state ("a specifier will flesh out the spec"),
    and `specify` promotes a triage card to `todo`, never straight to `ready`, so
    an idea sitting here cannot dispatch a worker.

    This is the visible record that a project's ideas are loaded. It is intake,
    not work: the cards carry no edges and gate nothing. The driver still reads
    the lane's idea from its file and snapshots it at activation. A lane with no
    idea gets no card, which is what an empty generic board looks like.
    """
    made = {}
    for lane in range(1, lane_count + 1):
        path = os.path.join(ideas_dir, f"lane-{lane}.md")
        if not os.path.exists(path):
            continue
        text = open(path).read()
        if not text.strip():
            continue
        snapshot = f"{repo}/mission/runs/{board}/snapshots/lane-{lane}.md"
        body = (f"RAW IDEA for lane {lane} — human input, not a work card.\n\n"
                f"Source: {os.path.join(ideas_dir, f'lane-{lane}.md')}\n"
                f"The driver snapshots this to {snapshot} when it activates lane "
                f"{lane}; lane {lane}'s cards read the snapshot, never the source.\n"
                f"Edit the source until the lane is activated.\n\n---\n\n{text}")
        out = kb(board, "create", idea_title(text, lane),
                 "--body", body, "--triage",
                 "--idempotency-key", f"{key_prefix}-idea-{lane}",
                 "--created-by", "human", "--json")
        made[lane] = json.loads(out)["id"]
    return made


def write_board_config(repo, slug, workdir, lane_count,
                       integration_tests, auto_gates):
    """The manifest. `template_root` owns control files; `workdir` is the
    only tree the driver runs git in — they differ whenever a board points
    somewhere other than this repo."""
    path = os.path.join(repo, "mission", "boards", f"{slug}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"slug": slug,
                   "template_root": repo,
                   "workdir": os.path.abspath(workdir),
                   "lane_count": lane_count,
                   "integration_tests": integration_tests,
                   "auto_gates": auto_gates}, f, indent=2)
    return path
