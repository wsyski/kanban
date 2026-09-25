import json
import sys, os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import card_render
import file_lanes
import run

def test_read_board_defaults_slug_from_directory_name(tmp_path):
    """The directory names the board. board.json may say so too, but it does not
    have to — and a directory and a manifest that disagree is a bug waiting to
    happen, so the directory wins by being the default."""
    d = tmp_path / "my-board"
    d.mkdir()
    (d / "board.json").write_text('{"title": "My Board", "lanes": 2}\n')
    cfg = card_render.read_board(str(d))
    assert cfg["slug"] == "my-board"
    assert cfg["lanes"] == 2


def test_read_board_keeps_an_explicit_slug(tmp_path):
    d = tmp_path / "dir-name"
    d.mkdir()
    (d / "board.json").write_text('{"slug": "explicit", "lanes": 1}\n')
    assert card_render.read_board(str(d))["slug"] == "explicit"


def test_read_board_without_a_manifest_is_an_error(tmp_path):
    d = tmp_path / "no-manifest"
    d.mkdir()
    with pytest.raises(FileNotFoundError):
        card_render.read_board(str(d))


class FakeKb:
    """Records hermes CLI calls and hands back synthetic card ids."""

    def __init__(self):
        self.calls = []
        self.n = 0

    def __call__(self, board, *args):
        self.calls.append(args)
        if args[0] == "create":
            self.n += 1
            return '{"id": "t_%03d"}' % self.n
        return ""

    def created(self):
        return [a for a in self.calls if a[0] == "create"]

    def parent_of(self, title):
        for a in self.created():
            if a[1] == title and "--parent" in a:
                return a[a.index("--parent") + 1]
        return None

    def links(self):
        return [(a[1], a[2]) for a in self.calls if a[0] == "link"]


def file_two_lanes(monkeypatch, tmp_path):
    import file_lanes
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    made = file_lanes.file_board("b", repo, str(tmp_path), 2, "k")
    return fake, made


def _file_one_lane(monkeypatch, tmp_path, **kwargs):
    """One lane filed against the REAL repo (the card bodies live there)."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    file_lanes.file_board("b", repo, str(tmp_path), 1, "k", **kwargs)
    return fake


def test_scratch_is_rendered_but_is_not_a_hand_off(monkeypatch, tmp_path):
    """`<RUNS>` resolves in a body, and is deliberately NOT a lane document: a
    directory that changes while a card works would read to the chain as a
    document written after the card started."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    body = card_render.render_body("c-body.txt", repo=repo, board="b",
                                  workdir=str(tmp_path), lane=1)
    assert "<RUNS>" not in body and "/boards/b/runs/scratch/" in body
    assert "<RUNS>" not in card_render.lane_paths("/repo", "b", 1)


def test_a_board_can_file_without_the_goal_judge(monkeypatch, tmp_path):
    """`goal-cards: []` has to reach the FILING path: a card filed with --goal
    anyway wedges on a judge that is reachable but transport-failing (O10)."""
    fake = _file_one_lane(monkeypatch, tmp_path, goal_cards=[])
    assert fake.created()
    assert not [a for a in fake.created() if "--goal" in a]


def test_the_goal_judge_is_off_by_default_for_a_worker_card(monkeypatch, tmp_path):
    """Goal mode is opt-in: a board with no `goal` key files no `--goal`."""
    fake = _file_one_lane(monkeypatch, tmp_path)
    assert not [a for a in fake.created() if "--goal" in a], \
        "a board with no 'goal' key must not file cards under the goal judge"


def test_goal_flags_never_reach_a_review_or_gate_card(monkeypatch, tmp_path):
    fake = _file_one_lane(monkeypatch, tmp_path, goal_cards=["I", "P", "TW", "C", "TI"])
    assert [a for a in fake.created() if "--goal" in a], \
        "a worker card should be filed under the goal judge when goal mode is on"
    for a in fake.created():
        if "--goal" in a:
            # a goal-loop judge can complete a card whose success case is blocking
            # and silently open the gate it guards — so never a gate, never a review
            assert a[a.index("--assignee") + 1] != "human-gate", a
            assert not a[1].startswith(("RV", "Gi", "Gp", "Gc")), a


def test_every_card_is_filed_parked(monkeypatch, tmp_path):
    """The whole board sits parked, and it is parked BY THE CREATE CALL: nothing is
    `ready` for even an instant, so a live dispatcher can never claim a card the
    driver has not activated. The second call this used to make — create `ready`,
    then block — left a window: on 2026-09-13 the dispatcher claimed P1 through it
    and spawned its worker 28 s before the lane opened (F2)."""
    fake, made = file_two_lanes(monkeypatch, tmp_path)
    created = fake.created()
    assert len(created) == len(made)
    for a in created:
        assert a[a.index("--initial-status") + 1] == "blocked", a
    assert not [a for a in fake.calls if a[0] == "block"], \
        "the parking is part of the create call; a separate block reopens the window"


def test_no_card_is_created_with_a_parent(monkeypatch, tmp_path):
    """block_task only transitions ready/running cards, so a card created with a
    parent is `todo` and its parking silently no-ops. Edges are added afterwards."""
    import lanes
    fake, _ = file_two_lanes(monkeypatch, tmp_path)
    assert all("--parent" not in a for a in fake.created())


def test_each_card_is_parked_before_it_is_linked(monkeypatch, tmp_path):
    """Ordering is the whole point: linking a card before it is parked makes it
    `todo`, and a `todo` card is not sticky — recompute_ready releases it. The
    parking rides inside the create call, so the invariant reads "no edge before
    every card is filed"."""
    fake, _ = file_two_lanes(monkeypatch, tmp_path)
    filed_at, n = {}, 0
    for i, a in enumerate(fake.calls):
        if a[0] == "create":
            n += 1
            filed_at["t_%03d" % n] = i      # FakeKb hands back ids in create order
    for i, a in enumerate(fake.calls):
        if a[0] == "link":
            for cid in (a[1], a[2]):
                assert filed_at[cid] < i, f"{cid} linked before it was parked"


def test_intra_lane_edges_are_linked(monkeypatch, tmp_path):
    fake, made = file_two_lanes(monkeypatch, tmp_path)
    assert (made["P2"], made["RVp2"]) in fake.links()
    assert (made["RVc1"], made["Gc1"]) in fake.links()


def test_the_fork_is_filed_as_two_edges_into_the_review(monkeypatch, tmp_path):
    """TW and C are siblings under the plan gate, so the board gets Gp→TW, Gp→C and
    BOTH edges into RVa. Filing a chain here would leave the coder blocked on a test
    file and the review released by one half of its evidence."""
    fake, made = file_two_lanes(monkeypatch, tmp_path)
    links = fake.links()
    assert (made["Gp1"], made["TW1"]) in links
    assert (made["Gp1"], made["C1"]) in links
    assert (made["TW1"], made["RVa1"]) in links
    assert (made["C1"], made["RVa1"]) in links
    assert (made["TW1"], made["C1"]) not in links, "the coder does not wait for the tester"


def test_no_cross_lane_edge_is_filed(monkeypatch, tmp_path):
    """Lane sequencing is the driver's job (lane_graph gates lane k on Gc{k-1});
    a board edge here would let the dispatcher run ahead of open_lane."""
    fake, made = file_two_lanes(monkeypatch, tmp_path)
    assert (made["Gc1"], made["P2"]) not in fake.links()


def test_every_card_is_filed(monkeypatch, tmp_path):
    fake, made = file_two_lanes(monkeypatch, tmp_path)
    assert len(fake.created()) == 22        # 11 cards x 2 lanes, IT-complete
    assert len(made) == 22


def test_file_ideas_creates_one_triage_card_per_entered_idea(monkeypatch, tmp_path):
    import file_lanes
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    (tmp_path / "lane-1.md").write_text("## Idea 1: CLI\n\nBuild the CLI.\n")
    (tmp_path / "lane-3.md").write_text("")          # placeholder, not entered
    made = file_lanes.file_ideas("b", "/repo", str(tmp_path), 3, "k")
    assert list(made) == [1]
    created = fake.created()
    assert len(created) == 1
    assert created[0][1] == "Idea 1: CLI"   # the heading already names it
    assert "--triage" in created[0]


def test_headingless_idea_still_gets_a_title(monkeypatch, tmp_path):
    import file_lanes
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    (tmp_path / "lane-2.md").write_text("just some prose, no heading\n")
    file_lanes.file_ideas("b", "/repo", str(tmp_path), 2, "k")
    assert fake.created()[0][1] == "Idea 2"


def test_file_ideas_carries_the_raw_text_and_points_at_the_snapshot(monkeypatch, tmp_path):
    import file_lanes
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    (tmp_path / "lane-1.md").write_text("## Idea 1: CLI\n\nBuild the CLI.\n")
    file_lanes.file_ideas("b", "/repo", str(tmp_path), 1, "k")
    body = fake.created()[0][fake.created()[0].index("--body") + 1]
    assert "Build the CLI." in body
    # The run directory is minted when an idea is ARMED, so the card names the runs
    # root and the file under it, never the id of the run that filed it (#31 class:
    # a path a reader would trust and a worker would never write to).
    assert "snapshots/lane-1.md" in body
    assert "/repo/boards/b/runs" in body
    assert "runs/k/snapshots" not in body


def test_the_idea_card_body_sends_the_holder_to_the_card(monkeypatch, tmp_path):
    """The card is the LIVE idea and the file is the record: arming adopts the card's
    text and writes it back over the file, so a sentence telling the human to 'edit the
    source' sent them to a file whose edit is clobbered."""
    import file_lanes
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    (tmp_path / "lane-1.md").write_text("## Idea 1: CLI\n\nBuild the CLI.\n")
    file_lanes.file_ideas("b", "/repo", str(tmp_path), 1, "k")
    body = fake.created()[0][fake.created()[0].index("--body") + 1]
    assert "Edit THIS CARD" in body
    assert "Edit the source" not in body
    # the marker block must still split cleanly from the adopted text
    assert body.split("\n---\n", 1)[1].strip().startswith("## Idea 1")


def test_file_ideas_files_nothing_on_an_empty_generic_board(monkeypatch, tmp_path):
    """A generic board with no ideas entered has an empty triage column."""
    import file_lanes
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    for k in (1, 2):
        (tmp_path / f"lane-{k}.md").write_text("")
    assert file_lanes.file_ideas("b", "/repo", str(tmp_path), 2, "k") == {}
    assert fake.calls == []


def test_idea_cards_have_no_edges(monkeypatch, tmp_path):
    """Intake, not work: a triage card gates nothing and is nobody's parent."""
    import file_lanes
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    (tmp_path / "lane-1.md").write_text("## Idea 1: CLI\n\nBuild it.\n")
    file_lanes.file_ideas("b", "/repo", str(tmp_path), 1, "k")
    assert fake.links() == []
    assert all("--parent" not in a for a in fake.created())


def test_filed_bodies_carry_no_raw_placeholders(monkeypatch, tmp_path):
    import re
    fake, _ = file_two_lanes(monkeypatch, tmp_path)
    for a in fake.created():
        body = a[a.index("--body") + 1]
        assert not run.unresolved_placeholders(body), a[1]


def test_the_filing_defaults_are_the_option_tables():
    """DEFAULT_MAX_RUNTIME / DEFAULT_MAX_RETRIES were literals byte-equal to the option
    table's defaults, against the house rule of reading them (review Important 10)."""
    import board_schema
    assert file_lanes.DEFAULT_MAX_RUNTIME == board_schema.OPTIONS["max-runtime"][1]
    assert file_lanes.DEFAULT_MAX_RETRIES == board_schema.OPTIONS["max-retries"][1]


def _repo_with_manifest(tmp_path, text):
    repo = tmp_path / "repo"
    (repo / "boards" / "b").mkdir(parents=True)
    (repo / "boards" / "b" / "board.json").write_text(text)
    return repo


def test_the_options_line_names_a_header_that_conflicts_with_the_board(tmp_path, monkeypatch):
    """The success path and its CONFLICTS line had never run: every test passed "/repo",
    so read_board raised and control fell into the except (review tests I5 / I31). The
    header wins silently otherwise, and the board file lies on the card a human reads."""
    repo = _repo_with_manifest(tmp_path, json.dumps({"slug": "b", "lanes": 1,
                                                     "integration-tests": True}))
    line = file_lanes._options_line(
        str(repo), "b", 1,
        "## Idea 1: a lane\n\n<!-- integration-tests: false -->\n\n### Done means\n\nx\n")
    assert "CONFLICTS with the board file" in line, line
    assert "integration-tests=false (idea header" in line, line


def test_a_manifest_that_will_not_parse_stops_the_filing(tmp_path, monkeypatch):
    """`except Exception: board_cfg = {}` filed every card on defaults — 60m ceilings,
    the goal judge off, and NO model flag, so the reviews ran the author's model (review
    Important 13). Only a MISSING manifest keeps the documented defaults. The engine is
    a FakeKb: before the fix this call went on to file cards."""
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    repo = _repo_with_manifest(tmp_path, '{"slug": "b", "lanes": 1,')
    with pytest.raises(ValueError):            # json.JSONDecodeError is a ValueError
        file_lanes.file_board("b", str(repo), str(tmp_path / "w"), 1, "k")
    assert fake.created() == [], "cards were filed on invented defaults"


def test_a_header_that_contradicts_the_board_stops_the_idea_filing(tmp_path, monkeypatch):
    """A per-lane array whose length does not match `lanes` is a configuration fault;
    the old catch turned it into "Lane options: unavailable (...)" in a card body and
    filed anyway (review Important 14)."""
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    repo = _repo_with_manifest(tmp_path, json.dumps({"slug": "b", "lanes": 1,
                                                     "unit-tests": [True, False, True]}))
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "lane-1.md").write_text("## Idea 1\n\n### Done means\n\nx\n")
    with pytest.raises(ValueError):
        file_lanes.file_ideas("b", str(repo), str(ideas), 1, "k")
    assert fake.created() == []


# ---- a per-lane `model`/`provider` array is indexed by the lane filed -------

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _filing_repo(tmp_path, manifest):
    """A repo laid out like this one around a manifest of the test's choosing:
    `boards/b/board.json`, and `template/` symlinked so the REAL card bodies render
    (render_body resolves them from the repo it is handed)."""
    repo = tmp_path / "repo"
    (repo / "boards" / "b").mkdir(parents=True)
    (repo / "boards" / "b" / "board.json").write_text(json.dumps(manifest))
    os.symlink(os.path.join(REPO, "template"), repo / "template")
    return repo


def _model_of(fake, title):
    """(model, provider) as the stub saw the flags on the card with this title."""
    for a in fake.created():
        if a[1] == title:
            return (a[a.index("--model") + 1] if "--model" in a else None,
                    a[a.index("--provider") + 1] if "--provider" in a else None)
    raise AssertionError(f"no card titled {title!r}: {[a[1] for a in fake.created()]}")


def test_a_per_lane_model_array_is_indexed_by_the_lane_filed(monkeypatch, tmp_path):
    """`model`/`provider` are per-lane options and board_schema accepts the array form
    (test_board_schema pins "one backend, a model per lane" and both-arrays as valid),
    but the filing path handed the raw list to `subprocess` — `TypeError: expected
    str, bytes or os.PathLike object, not list` (final review, item 4). One provider
    serving a different model per lane is the normal local setup, so the array is
    indexed by the lane being filed rather than dropped."""
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    repo = _filing_repo(tmp_path, {"slug": "b", "lanes": 2,
                                   "model": ["m1", "m2"], "provider": ["p1", "p2"]})
    file_lanes.file_board("b", str(repo), str(tmp_path / "w"), 2, "k")
    assert _model_of(fake, "C1: implement - lane 1") == ("m1", "p1")
    assert _model_of(fake, "C2: implement - lane 2") == ("m2", "p2")
    # every card of a lane takes that lane's pair, the researcher and a review included
    assert _model_of(fake, "I1: idea refinement - lane 1") == ("m1", "p1")
    assert _model_of(fake, "RVa2: code review - lane 2") == ("m2", "p2")


def test_a_scalar_board_pair_files_byte_identically_for_every_lane(monkeypatch, tmp_path):
    """The scalar path is unchanged: `lane_value` returns anything that is not a list
    as it is, so every card carries the board's own pair — the two tokens
    `lanes.model_args` builds for a scalar, in the same order."""
    import lanes
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    repo = _filing_repo(tmp_path, {"slug": "b", "lanes": 2,
                                   "model": "m1", "provider": "p1"})
    file_lanes.file_board("b", str(repo), str(tmp_path / "w"), 2, "k")
    want = lanes.model_args("C", {"model": "m1", "provider": "p1"})
    assert want == ["--model", "m1", "--provider", "p1"]
    assert fake.created()
    for a in fake.created():
        i = a.index("--model")
        assert list(a[i:i + len(want)]) == want, a[1]


def test_a_model_array_with_no_entry_for_a_lane_stops_the_filing(monkeypatch, tmp_path):
    """A list with no entry for the lane being filed cannot be honoured, and inventing
    one (or filing a model-less card) is worse than refusing: board_schema refuses the
    shape at the door, so a caller that gets here has skipped the door. Nothing is
    filed — the array is read before the first create, the way a manifest fault is."""
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    repo = _filing_repo(tmp_path, {"slug": "b", "lanes": 2, "model": ["m1"]})
    with pytest.raises(ValueError, match="lane 2"):
        file_lanes.file_board("b", str(repo), str(tmp_path / "w"), 2, "k")
    assert fake.created() == [], "a card was filed before the array was checked"
