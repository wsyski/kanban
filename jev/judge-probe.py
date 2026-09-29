#!/usr/bin/env python3
"""Probe the GOAL JUDGE end to end: what is configured, what answers, and what verdicts.

Answers the question "can this model serve as the goal judge?" with a live call rather than a
catalog lookup, because a judge that resolves but cannot answer wedges every goal-mode card
(the failure is silent: `judge_goal` fails open to `continue`, so every completion is rejected
and the lane is unwinnable — see DESIGN.md, *The goal judge*).

Usage:
  jev/judge-probe.py                 # probe the CONFIGURED judge (status + two verdicts)
  jev/judge-probe.py --models A B     # probe specific model ids on the configured provider
  jev/judge-probe.py --provider P --models A B
  jev/judge-probe.py --config         # print the resolved judge config and where it comes from

Exit 0 when the configured judge answered; 1 otherwise (so a board/CI check can gate on it).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_lib

if not os.environ.get("KANBAN_PROBE_REEXEC"):
    probe_lib.reexec_if_needed(Path(__file__).resolve())

get_text_auxiliary_client, judge_goal = probe_lib.bootstrap()

GOAL = "Write a file at /tmp/pong.txt containing exactly: PONG"
CLAIMS = (
    ("honest done", "I created /tmp/pong.txt with the exact content PONG."),
    ("honest partial", "Still working: the test suite currently fails on 3 cases."),
)


def resolved_config() -> dict:
    """The judge config as the runtime actually resolves it, plus the managed overlay."""
    from hermes_cli.config import load_config
    from hermes_cli import managed_scope

    cfg = load_config() or {}
    jc = ((cfg.get("auxiliary") or {}).get("goal_judge") or {})
    managed = None
    try:
        managed = managed_scope.load_managed_config()
    except Exception:
        pass
    mj = ((managed or {}).get("auxiliary") or {}).get("goal_judge") or {}
    return {
        "resolved": {"provider": jc.get("provider"), "model": jc.get("model")},
        "managed_pin": {"provider": mj.get("provider"), "model": mj.get("model")} or None,
        "managed_path": str(managed_scope.get_managed_dir()) if hasattr(managed_scope, "get_managed_dir") else "/etc/hermes",
    }


def probe_verdicts(label: str) -> bool:
    """Run the two-verdict discrimination test. Returns True when the judge answered at all."""
    print(f"\n== {label} ==")
    answered = False
    for name, claim in CLAIMS:
        t = time.time()
        verdict, reason, parse_failed, wait, transport_failed = judge_goal(GOAL, claim, timeout=60)
        answered = answered or not transport_failed
        print(f"  [{name:14s}] verdict={verdict!r:12s} transport_failed={transport_failed} "
              f"parse_failed={parse_failed} ({time.time() - t:.1f}s)")
        print(f"                   reason={reason[:110]!r}")
    return answered


def probe_models(provider: str, models: list[str]) -> bool:
    """Direct-call each model through the client the judge would use."""
    from agent.auxiliary_client import resolve_provider_client

    client, _ = resolve_provider_client(provider, model=models[0])
    if client is None:
        print(f"no auxiliary client for provider {provider!r} (missing credentials?)")
        return False
    ok = False
    print(f"\n== direct call: provider={provider} ==")
    for mid in models:
        try:
            r = client.chat.completions.create(
                model=mid, max_tokens=24, temperature=0,
                extra_headers={"x-opencode-session": "hermes-judgeprobe-0001"},
                messages=[{"role": "user", "content": "Reply with exactly: PONG"}],
            )
            text = (r.choices[0].message.content or "").strip()
            print(f"  {mid:32s} OK   -> {text[:40]!r}")
            ok = True
        except Exception as exc:  # noqa: BLE001 — a probe reports, it does not raise
            body = getattr(exc, "body", None) or str(exc)
            print(f"  {mid:32s} FAIL {type(exc).__name__}: {str(body)[:150]}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", help="probe this provider instead of the configured one")
    ap.add_argument("--models", nargs="*", default=[], help="model ids to call directly")
    ap.add_argument("--config", action="store_true", help="print the resolved judge config only")
    args = ap.parse_args()

    info = resolved_config()
    print("goal judge config")
    print(f"  resolved   : {info['resolved']}")
    print(f"  managed pin: {info['managed_pin']}  ({info['managed_path']}/config.yaml)")
    print("  NOTE: the managed overlay is merged LAST (hermes_cli/config.py::_merge_managed_overlay),")
    print("        so a managed pin overrides every per-profile auxiliary.goal_judge value.")

    if args.config:
        return 0

    if args.models:
        provider = args.provider or info["resolved"].get("provider") or ""
        return 0 if probe_models(provider, args.models) else 1

    client, model = get_text_auxiliary_client("goal_judge")
    print(f"\n  client     : {type(client).__name__ if client else None} model={model!r} "
          f"base_url={getattr(client, 'base_url', None)}")
    if client is None:
        print("  NO AUXILIARY CLIENT — the judge would fail open to 'continue' on every card.")
        return 1
    return 0 if probe_verdicts(f"verdicts on {model}") else 1


if __name__ == "__main__":
    raise SystemExit(main())
