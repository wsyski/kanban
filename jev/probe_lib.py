"""Resolve the interpreter that can run THIS checkout, without depending on `hermes` on PATH.

`.hermes/bin/hermes` is a shell shim: it execs a specific bundled CPython (found by globbing
`<hermes-home>/tools/python-3.*/bin/python3`) with `-I` and `sys.path.insert(0, <repo>)`.
We do the same, because the repo's own venv lacks `ruamel` (hermes_yaml) and the system
python3 lacks it too — a probe under the wrong interpreter dies at `import hermes_yaml`.
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes"))
REPO = Path(os.environ.get("HERMES_REPO") or HERMES_HOME / "hermes-agent")


def find_python() -> str:
    """The bundled interpreter the `hermes` launcher uses; falls back to this process."""
    override = os.environ.get("KANBAN_PROBE_PYTHON")
    if override and Path(override).exists():
        return override
    hits = sorted(glob.glob(str(HERMES_HOME / "tools" / "python-3.*" / "bin" / "python3")))
    if hits:
        return hits[-1]
    return sys.executable


def reexec_if_needed(script: Path) -> None:
    """Re-exec this script under the bundled interpreter when we are not already there.

    FORWARD``sys.argv[1:]`` — the child is a fresh interpreter, so a flag dropped here is a flag
    the probe silently ignores (the `--config` short-circuit ran a full verdict sweep before this
    forwarding existed).
    """
    have = find_python()
    if os.path.realpath(sys.executable) != os.path.realpath(have) or not sys.flags.isolated:
        raise SystemExit(
            subprocess.call(
                [have, "-I", str(script), *sys.argv[1:]],
                env={**os.environ, "KANBAN_PROBE_REEXEC": "1"},
            )
        )


def bootstrap():
    """Mirror the launcher's preamble, then import the Hermes runtime.

    Returns the modules a probe needs. Import order matters: HERMES_HOME must be set before
    `hermes_bootstrap` loads `.env`, and the repo must be on sys.path before any hermes import.
    """
    os.environ.pop("PYTHONHOME", None)
    os.environ.pop("PYTHONPATH", None)
    sys.path.insert(0, str(REPO))
    os.environ.setdefault("HERMES_HOME", str(HERMES_HOME))
    import hermes_bootstrap  # noqa: F401  — loads .env + runtime setup, exactly as the launcher does
    from agent.auxiliary_client import get_text_auxiliary_client  # noqa: F401
    from hermes_cli.goals import judge_goal  # noqa: F401
    return get_text_auxiliary_client, judge_goal
