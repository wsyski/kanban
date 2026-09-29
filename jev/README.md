# Connecting `jev-1.13` — what to try, and what will not work

You asked for this by name. Read the **bottom line** before spending time on either route.

## Bottom line

**`jev-1.13` is not a chat model, so it cannot be a goal judge on either provider.** This is not
a credentials or relay problem — it is the wrong *kind* of model. Verified live, 2026-09-29:

```
$ curl openrouter.ai/api/v1/chat/completions  -d '{"model":"jev-1.13", ...}'
{"error":{"message":"jev-1.13 is a decisions model and cannot be used with the
 chat/completions endpoint. Use the /api/alpha/decisions endpoint instead.","code":400}}
```

The Hermes goal judge reaches a model through the **chat/completions** path
(`agent/auxiliary_client.py` → the judge's client). A model that refuses that endpoint cannot
judge, whatever the rest of the wiring looks like. `docs/ANSWER-goal-judge.md` carries the full
evidence set.

Two further facts, so the routes below are read correctly:

- **`opencode-go` does not serve `jev-1.13` at all.** Live `GET /zen/go/v1/models` → 30 ids,
  **zero** matching `jev`. The id exists only on the **`opencode-zen`** relay.
- **You have no `OPENCODE_ZEN_API_KEY`.** `.env` holds `OPENCODE_GO_API_KEY` and
  `OPENROUTER_API_KEY` only, so nothing on the zen relay is reachable today.

## Route A — `opencode-go` : `jev-1.13`

**Try:** `jev/relay-inventory.py --grep jev` — reads the go relay's live model list.

**Result: the model is not there.**

```
== opencode-go ==  key OPENCODE_GO_API_KEY: present
  0 model(s):
```

If you still want to send the id to the go relay, it answers before the model is ever
considered — the relay demands a session key on every request:

```
$ curl opencode.ai/zen/go/v1/chat/completions -d '{"model":"jev-1.13", ...}'
400 {"type":"MissingSessionID",
     "message":"Request is missing x-opencode-session and cannot be routed efficiently."}
```

That `400` is **not** evidence about `jev`; every model on that relay returns it when called
without the header (verified for `qwen3.8-flash`, `glm-5.3-flash`, `kimi-k3`, and more). The goal
judge does send the header — `agent/opencode_affinity.py` injects `x-opencode-session` on
out-of-turn calls — so this specific error is not what blocks the judge. The missing model is.

**What would have to change for Route A to be worth retrying:** OpenCode would have to add a chat
(not decisions) `jev` model to the Go subscription. Nothing on your side moves that.

## Route B — `openrouter` : `jev-1.13`

**Try:** a real call, not a catalog lookup — the id is absent from OpenRouter's public list, and
it resolves anyway:

```bash
set -a; . ~/.hermes/.env; set +a
curl -s -X POST https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"jev-1.13","messages":[{"role":"user","content":"PONG"}],"max_tokens":8}'
```

**Result: `400` — wrong endpoint for this model** (the quoted error at the top).

- `GET /api/v1/models` (464 ids) lists **no** `jev-1.13`. The only `jev` entry is
  **`typesafe/jev-router`**, described as running "on **Jev**, TypeSafe's first System One
  model". So `jev-1.13` is an alias that resolves to the decisions backend, not a chat SKU.
- The endpoint it names, `POST /api/v1/alpha/decisions`, returned **`404 Not Found`** to
  `.../api/v1/alpha/decisions`. It is not reachable as documented.

**What would have to change for Route B:** TypeSafe would have to expose `jev` behind
chat/completions, or you would have to write a Hermes adapter that speaks the decisions API.
There is no decisions/`jev` endpoint support anywhere in Hermes today — nothing in `agent/`,
`hermes_cli/` or the catalogs references it. That adapter is a real project, not a config value,
and it still would not produce a chat completion for the judge to read.

## Why this matters more than it looks — the judge fails SILENTLY

`judge_goal` returns the verdict `continue` on **any** transport error
(`hermes_cli/goals.py`, the `except Exception` branch), and no evidence satisfies `continue`. So
an unreachable judge does not error out — it makes **every goal-mode card uncompletable and the
lane unwinnable**, with only `goal judge: API call failed` in the worker's
`~/.hermes/profiles/<p>/logs/agent.log` to say so. `board_schema` cannot catch it: a model id is
never validated against a catalog. This is exactly why goal mode is opt-in, and why you probe
before arming `"goal-cards"`.

## If you want a working judge anyway

The configured judge is verified working; leave it alone unless you have a reason:

```
resolved   : {'provider': 'opencode-go', 'model': 'qwen3.8-flash'}
managed pin: {'provider': 'opencode-go', 'model': 'qwen3.8-flash'}   (/etc/hermes/config.yaml)
```

`qwen3.8-flash` answers `done` for a finished claim and `continue` for an unfinished one in ~3–5 s.
`space-bunny-free` on the **go** relay also answers real chat completions.

The one edit you may actually want: **`glm-5.3-flash` and `longcat-2.5-preview-free` return
`ModelProtocolUnsupported` on the go relay** ("Model does not support this protocol") — avoid
those ids as auxiliary models.

> **Management layer.** `auxiliary.goal_judge` is pinned in `/etc/hermes/config.yaml`, and the
> managed overlay is merged LAST (`hermes_cli/config.py::_merge_managed_overlay`), deliberately
> inverting normal precedence. A per-profile value **cannot** override it, and
> `hermes config set auxiliary.goal_judge.model …` writes `~/.hermes/config.yaml`, which **loses**.
> Changing the judge means editing the root-owned managed file.

Run `jev/check-goal-judge.sh` after any such edit. Exit 0 = the judge answered; exit 1 = do not
file `"goal-cards"`.

## Not to be confused with: the `jev-*` plugin family

`jev-judge` (and `jev-router`, `jev-curator`, `hermes-switchyard`, …) are **plugins** from the
TypeSafe/`jev` ecosystem, not models. `jev-judge` is a **pre-tool gate**
(`pre_tool_call` + a `jev_ask` tool) that classifies *actions* — destructive behaviour,
exfiltration — and it has no relationship to `auxiliary.goal_judge`, which judges *goal
completion*. A plugin cannot make a decisions model produce chat completions.

Note the disclosure: several of these plugins send user text or redacted tool arguments to
TypeSafe/OpenRouter on your key by default.
