"""The suite's own contract: every test file runs ON ITS OWN.

Three files imported `card_render` before inserting template/ on sys.path, so they
collected only when an earlier file (alphabetically) had already done it — and every
one-file `pytest tests/<file>` step in a plan died with ModuleNotFoundError (measured
2026-09-24: test_chain_log, test_open_lane, test_refinement_option).
"""
import ast
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = {os.path.splitext(n)[0] for layer in ("template", "driver")
          for n in os.listdir(os.path.join(REPO, layer)) if n.endswith(".py")}


def test_no_test_file_imports_an_engine_module_before_it_can_find_it():
    offenders = []
    for name in sorted(os.listdir(os.path.join(REPO, "tests"))):
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        with open(os.path.join(REPO, "tests", name)) as f:
            tree = ast.parse(f.read())
        path_ready = False
        for node in tree.body:
            text = ast.unparse(node)
            # sys.path.insert, or loading a driver CLI by path — run-audit.py and its
            # siblings insert their own directories when executed
            if "sys.path.insert" in text or "exec_module" in text:
                path_ready = True
            if isinstance(node, ast.Import) and not path_ready:
                offenders += [f"{name}: {a.name}" for a in node.names if a.name in ENGINE]
    assert not offenders, offenders


def test_every_file_the_engine_opens_is_closed_by_a_with():
    """`open(p).read()` leaves the handle to the garbage collector and the platform's
    default encoding; the idea and refined files are UTF-8 prose (review Suggestion 3,
    code S3). Every `open(` in the engine sits in a `with` now — this keeps it so."""
    bare = []
    for layer in ("template", "driver"):
        for name in sorted(os.listdir(os.path.join(REPO, layer))):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(REPO, layer, name)) as f:
                tree = ast.parse(f.read())
            managed = {id(item.context_expr) for node in ast.walk(tree)
                       if isinstance(node, ast.With) for item in node.items}
            bare += [f"{layer}/{name}:{node.lineno}" for node in ast.walk(tree)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                     and node.func.id == "open" and id(node) not in managed]
    assert not bare, bare
