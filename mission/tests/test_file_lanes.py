import sys, os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import file_lanes

DOC = """Example ideas for the smoke test.

## Idea 1: CLI
<!-- integration-tests: false -->

Build the CLI.

## Idea 2: service

Build the service.
"""


def test_import_writes_one_file_per_section(tmp_path):
    doc = tmp_path / "ideas.md"
    doc.write_text(DOC)
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    n = file_lanes.import_ideas(str(doc), str(ideas), lane_count=3)
    assert n == 2
    assert (ideas / "lane-1.md").read_text().startswith("## Idea 1: CLI")
    assert "integration-tests: false" in (ideas / "lane-1.md").read_text()
    assert (ideas / "lane-2.md").read_text().startswith("## Idea 2: service")
    assert not (ideas / "lane-3.md").exists()


def test_import_rejects_more_sections_than_lanes(tmp_path):
    doc = tmp_path / "ideas.md"
    doc.write_text(DOC)
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    with pytest.raises(ValueError, match="2 ideas but only 1 lane"):
        file_lanes.import_ideas(str(doc), str(ideas), lane_count=1)


def test_import_refuses_to_clobber_entered_idea(tmp_path):
    doc = tmp_path / "ideas.md"
    doc.write_text(DOC)
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "lane-1.md").write_text("## my own typed idea\n")
    with pytest.raises(ValueError, match="--force"):
        file_lanes.import_ideas(str(doc), str(ideas), lane_count=3)


def test_import_overwrites_with_force(tmp_path):
    doc = tmp_path / "ideas.md"
    doc.write_text(DOC)
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "lane-1.md").write_text("## my own typed idea\n")
    file_lanes.import_ideas(str(doc), str(ideas), lane_count=3, force=True)
    assert (ideas / "lane-1.md").read_text().startswith("## Idea 1: CLI")


def test_import_ignores_empty_placeholder_files(tmp_path):
    doc = tmp_path / "ideas.md"
    doc.write_text(DOC)
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "lane-1.md").write_text("")
    file_lanes.import_ideas(str(doc), str(ideas), lane_count=3)
    assert (ideas / "lane-1.md").read_text().startswith("## Idea 1: CLI")


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

    def blocked_ids(self):
        return [a[3] for a in self.calls if a[0] == "block"]

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
    repo = os.path.dirname(repo)
    made = file_lanes.file_board("b", repo, str(tmp_path), 2, "k")
    return fake, made


def test_every_card_is_blocked(monkeypatch, tmp_path):
    """The whole board sits parked: nothing is `todo`, so the dispatcher can
    never claim a card the driver has not activated."""
    fake, made = file_two_lanes(monkeypatch, tmp_path)
    assert sorted(fake.blocked_ids()) == sorted(made.values())


def test_no_card_is_created_with_a_parent(monkeypatch, tmp_path):
    """block_task only transitions ready/running cards, so a card created with a
    parent is `todo` and its block silently no-ops. Edges are added afterwards."""
    import lanes
    fake, _ = file_two_lanes(monkeypatch, tmp_path)
    assert all("--parent" not in a for a in fake.created())


def test_each_card_is_blocked_before_it_is_linked(monkeypatch, tmp_path):
    """Ordering is the whole point: linking a card before blocking it makes it
    `todo`, the block no-ops, and the dispatcher can claim it."""
    fake, _ = file_two_lanes(monkeypatch, tmp_path)
    blocked_at = {}
    for i, a in enumerate(fake.calls):
        if a[0] == "block":
            blocked_at[a[3]] = i
    for i, a in enumerate(fake.calls):
        if a[0] == "link":
            parent, child = a[1], a[2]
            assert blocked_at.get(child, 10**9) < i, f"{child} linked before blocked"
            assert blocked_at.get(parent, 10**9) < i, f"{parent} linked before blocked"


def test_intra_lane_edges_are_linked(monkeypatch, tmp_path):
    fake, made = file_two_lanes(monkeypatch, tmp_path)
    assert (made["P2"], made["RVp2"]) in fake.links()
    assert (made["RVc1"], made["Gc1"]) in fake.links()


def test_no_cross_lane_edge_is_filed(monkeypatch, tmp_path):
    """Lane sequencing is the driver's job (lane_graph gates lane k on Gc{k-1});
    a board edge here would let the dispatcher run ahead of open_lane."""
    fake, made = file_two_lanes(monkeypatch, tmp_path)
    assert (made["Gc1"], made["P2"]) not in fake.links()


def test_every_card_is_filed(monkeypatch, tmp_path):
    fake, made = file_two_lanes(monkeypatch, tmp_path)
    assert len(fake.created()) == 18
    assert len(made) == 18


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
    assert "/repo/mission/runs/b/snapshots/lane-1.md" in body


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
