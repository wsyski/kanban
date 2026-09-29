#!/usr/bin/env python3
"""Inventory the models an OpenCode relay actually offers, and flag the free / judging ones.

Facts this settles, which a docs read cannot:
  * which relay serves a given model id (opencode-go and opencode-zen differ — `jev-1.13*`
    exists ONLY on zen),
  * that free-tier ids on the relays are refused outside the OpenCode client
    (`403 FreeTierError`), so a "-free" id is not a usable auxiliary model,
  * that a relay request with no `x-opencode-session` is refused (`400 MissingSessionID`)
    regardless of model — the goal judge sends one (agent/opencode_affinity.py).

Usage:
  jev/relay-inventory.py                     # both relays, all ids
  jev/relay-inventory.py --free              # only ids containing "free"
  jev/relay-inventory.py --grep jev,spark    # only ids matching any comma-separated token
  jev/relay-inventory.py --ping <model-id>   # direct chat/completions call, prints the raw body
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_lib

RELAYS = {
    "opencode-go": ("https://opencode.ai/zen/go/v1", "OPENCODE_GO_API_KEY"),
    "opencode-zen": ("https://opencode.ai/zen/v1", "OPENCODE_ZEN_API_KEY"),
}


def _load_env_file() -> None:
    """A relay key may live only in .env, which is not exported into a bare shell."""
    env = Path(probe_lib.HERMES_HOME) / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _get(url: str, key: str | None) -> tuple[int, str]:
    """GET via curl, not urllib.

    The relays sit behind Cloudflare, which answers urllib's default TLS/UA fingerprint with
    `403 error code 1010`; curl gets through. A probe must use the transport that works, or its
    "model not listed" answer is really "the probe was blocked".
    """
    cmd = ["curl", "-s", "-m", "25", "-w", "\n%{http_code}", url]
    if key:
        cmd += ["-H", f"Authorization: Bearer {key}"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=40).stdout
    except Exception as e:  # noqa: BLE001
        return 0, str(e)
    body, _, status = out.rpartition("\n")
    return (int(status) if status.isdigit() else 0), body


def list_models(base: str, key: str | None) -> list[str]:
    status, body = _get(f"{base}/models", key)
    if status != 200:
        print(f"    /models -> http {status}: {body[:160]}")
        return []
    try:
        return [m["id"] for m in json.loads(body).get("data", [])]
    except Exception as e:  # noqa: BLE001
        print(f"    /models parse failed: {e}")
        return []


def ping(base: str, key: str | None, model: str, session: bool = True) -> None:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
        "max_tokens": 16,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if session:
        headers["x-opencode-session"] = "hermes-judgeprobe-0001"
    req = urllib.request.Request(f"{base}/chat/completions", data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"  http {r.status}: {r.read().decode()[:300]}")
    except urllib.error.HTTPError as e:
        print(f"  http {e.code}: {e.read().decode()[:300]}")
    except Exception as e:  # noqa: BLE001
        print(f"  error: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--free", action="store_true", help="only ids containing 'free'")
    ap.add_argument("--grep", help="comma-separated tokens; keep ids matching any")
    ap.add_argument("--ping", metavar="MODEL", help="call this model on each relay and print the body")
    args = ap.parse_args()

    _load_env_file()
    tokens = [t.strip().lower() for t in (args.grep or "").split(",") if t.strip()]

    for name, (base, keyname) in RELAYS.items():
        key = os.environ.get(keyname)
        print(f"\n== {name} ==  key {keyname}: {'present' if key else 'MISSING'}")
        if args.ping:
            ping(base, key, args.ping)
            continue
        ids = list_models(base, key)
        if not ids:
            continue
        if args.free:
            ids = [i for i in ids if "free" in i.lower()]
        if tokens:
            ids = [i for i in ids if any(t in i.lower() for t in tokens)]
        print(f"  {len(ids)} model(s):")
        for i in ids:
            print(f"    {i}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
