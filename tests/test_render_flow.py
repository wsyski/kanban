import importlib.util
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _render_flow(monkeypatch, root):
    """render-flow.py loaded as a module and pointed at a scratch tree `root`, which
    holds driver/flow.drawio, driver/flow.mmd and README.md (any of them may be
    missing or stale)."""
    spec = importlib.util.spec_from_file_location(
        "render_flow", os.path.join(REPO, "driver", "render-flow.py"))
    rf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rf)
    monkeypatch.setattr(rf, "HERE", str(root / "driver"))
    monkeypatch.setattr(rf, "REPO", str(root))
    monkeypatch.setattr(rf, "README", str(root / "README.md"))
    monkeypatch.setattr(sys, "argv", ["render-flow.py", "--check"])
    return rf


def _copy_tree(tmp_path):
    (tmp_path / "driver").mkdir()
    for name in ("flow.drawio", "flow.mmd"):
        shutil.copy(os.path.join(REPO, "driver", name), tmp_path / "driver" / name)
    shutil.copy(os.path.join(REPO, "README.md"), tmp_path / "README.md")
    return tmp_path


def test_diagrams_are_generated_from_the_current_lane_table():
    r = subprocess.run([sys.executable, "driver/render-flow.py", "--check"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_the_generic_diagram_names_no_build_tool():
    """REPLACED 2026-09-24 — this asserted only that 'failsafe' (a Maven plugin) is
    absent, a word nothing near the diagram would write (review tests S1/Suggestion 9).
    The generic diagram must name no project's build tooling at all."""
    for name in ("flow.mmd", "flow.drawio"):
        text = open(os.path.join(REPO, "driver", name)).read().lower()
        for word in ("failsafe", "surefire", "maven", "gradle", "pom.xml", "junit"):
            assert word not in text, (name, word)


def test_check_fails_when_one_diagram_is_stale(tmp_path, monkeypatch, capsys):
    """CI runs `--check` as a correctness step and no test ever made it fail. A copy of
    the real outputs is current; one line appended to flow.mmd makes exactly that file
    stale — and the README beside it stays current, so this is not passing because of
    a missing file."""
    root = _copy_tree(tmp_path)
    rf = _render_flow(monkeypatch, root)
    assert rf.main() == 0
    with open(root / "driver" / "flow.mmd", "a") as f:
        f.write("%% hand edit\n")
    assert rf.main() == 1
    out = capsys.readouterr().out
    assert "stale: driver/flow.mmd" in out, out
    assert "README" not in out, out


def test_check_names_a_missing_readme(tmp_path, monkeypatch, capsys):
    """`open(README)` was unguarded and ran BEFORE the existence check the other targets
    get, so a missing README was a FileNotFoundError traceback in CI instead of a stale
    line (review Important 20). Leaving README out of the targets would be worse: then
    `--check` examined nothing and exited 0."""
    root = _copy_tree(tmp_path)
    os.unlink(root / "README.md")
    rf = _render_flow(monkeypatch, root)
    assert rf.main() == 1
    assert "stale: README.md (missing" in capsys.readouterr().out
