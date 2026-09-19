"""The layer boundary, enforced: `template/` is what both drivers import; `driver/` is the
kanban driver's own; `bots/` is the second driver.

The tree was split for exactly this reason and nothing held it: a `bots/` module that
starts importing `driver/file_lanes.py`, or a shared module that reaches back into the
driver, still RUNS — it just re-couples the two drivers the split exists to keep apart, and
the coupling shows up later as "both had to change". So the check is on imports, and the
file lists are written out by hand: a new module has to be classified deliberately, and
this test fails loudly until it is.

`doc-chain.py`, `run-audit.py`, `render-flow.py`, `runs-report.py` and `timing-report.py`
have hyphens in their names and are loaded by path, so they never appear as imports — they
are still classified, because their OWN imports are what the first test checks.
"""
import ast
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# What both drivers may import: the card graph, the option declaration, the body renderer
# and the board lock.
TEMPLATE_FILES = ["board_schema", "card_render", "driver_lock", "lanes"]
# The kanban driver's own. `bots/` may import NONE of these.
DRIVER_FILES = ["doc-chain", "file_lanes", "render-flow", "run", "run-audit",
                "runs-report", "runs_util", "timing-report"]


def _importable(stems):
    """The names these files can be IMPORTED as (a hyphenated file is loaded by path)."""
    return {s.replace("-", "_") for s in stems}


LOCAL = _importable(TEMPLATE_FILES) | _importable(DRIVER_FILES) | {"audit", "run_board"}


def _modules(layer):
    """`{file stem: path}` for one directory's own .py files."""
    d = os.path.join(REPO, layer)
    return {f[:-3]: os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".py")}


def _imports(path):
    """The local modules `path` imports — from the import graph, never from prose."""
    tree = ast.parse(open(path).read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found & LOCAL


def test_the_shared_layer_never_reaches_into_the_driver():
    for name, path in _modules("template").items():
        into = _imports(path) & _importable(DRIVER_FILES)
        assert not into, f"template/{name}.py imports {sorted(into)} — driver-only modules"


def test_the_bot_driver_imports_only_the_shared_layer():
    allowed = _importable(TEMPLATE_FILES) | set(_modules("bots"))
    for name, path in _modules("bots").items():
        into = _imports(path)
        assert into <= allowed, (
            f"bots/{name}.py imports {sorted(into - allowed)} — the bot driver must not "
            f"depend on the kanban driver's own modules")


def test_every_module_is_classified():
    """A new module has to be one of the two layers, or the tests above never see it."""
    for layer, known in (("template", TEMPLATE_FILES), ("driver", DRIVER_FILES)):
        found = sorted(_modules(layer))
        assert found == sorted(known), (
            f"{layer}/ holds {found}; this test classifies {sorted(known)} — add the new "
            f"module to the layer it belongs to")
