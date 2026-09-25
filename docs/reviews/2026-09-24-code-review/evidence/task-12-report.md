# Task 12 report — the generated schema and `validate` agree

**Status:** complete. Steps 1–5 of the brief executed in order, in the repo root
`/opt/projects/kanban/main/kanban`, on branch `main`, nothing committed, nothing
staged outside the three files named in the brief.

## Pre-state check (before any edit)

`git hash-object` of the three targets matched the brief's patch `index` "before"
blobs exactly, so the brief's patch context was measured against this tree:

| file | blob | brief's before-hash |
|---|---|---|
| `template/board_schema.py` | `a5c5e21c9c23…` | `a5c5e21` ✔ |
| `tests/test_board_schema.py` | `75e57f3fc507…` | `75e57f3` ✔ |
| `template/board.schema.json` | `98b09dbd03a6…` | `98b09db` ✔ |

Both patches (`git apply --check`) reported clean, and both applied with no
`git apply` first-hunk failure — **no drift, nothing applied by hand**. The only
diagnostic from `git apply` was cosmetic: the `board_schema.py` hunk's index line
claims mode `100755` while the tree and index both carry `100644` (verified with
`git ls-files -s`), so the warning changes no content and no mode.

## Step 1 — tests written

`git apply` of the brief's `tests/test_board_schema.py` hunk: applied cleanly
(+97 lines, one hunk). Ten new items: the `CORPUS` list, six tests and the pins.

## Step 2 — measured red

`/usr/bin/python3 -m pytest -q tests/test_board_schema.py` (exit 1):

```
3 failed, 80 passed in 0.60s
```

Exactly the brief's "3 red" and the three named red tests. Each failed for the
claimed reason, verbatim from the run:

1. `test_validate_and_the_generated_schema_agree` —
   `jsonschema.exceptions.ValidationError: 'lanes' is a required property`,
   `Failed validating 'required' in schema … On instance: {'slug': 'b'}`. This is
   the review's Important 2 in the schema's direction: `validate` accepts a
   manifest with no `lanes` (default 1 in the option table) and the schema
   refused it.
2. `test_the_refusals_are_refused_on_both_sides` —
   `AssertionError: assert []` for `validate({'slug': 'b', 'auto-gates':
   ['Gi', 'Gi']})`; `_kind_error`'s `gates` branch checked the code set but not
   duplicates, so validate accepted what the schema's `uniqueItems` refused.
3. `test_write_schema_reports_an_unwritable_target` —
   `AssertionError: Traceback (most recent call last) … FileNotFoundError:
   [Errno 2] No such file or directory: '…/no-such-dir/board.schema.json'`
   out of `write_schema`'s `open(path, "w")` (errors S16).

The four pins the brief names all passed in the red run: the kinds invariant
(`test_every_option_kind_has_a_schema_entry`), the shipped-boards corpus
(`test_every_shipped_manifest_is_schema_valid` — 7 boards found, matching the
"seven boards" claim), stale (`test_check_schema_calls_a_stale_file_stale`) and
round-trip (`test_write_schema_round_trips`). No test failed for a reason other
than the one the brief predicts, so no finding against this task.

`jsonschema` is present for both interpreters (`/usr/bin/python3` 3.14.4 reads
`/usr/lib/python3/dist-packages/jsonschema` 4.26.0; the session `python3` 3.14.7
has 4.26.0 too), so the `importorskip` never short-circuits — 83 tests collected
and reported, not 81 with two skipped.

## Step 3 — implementation and schema regeneration

`git apply` of the brief's two-file hunk: `template/board_schema.py` applied
cleanly (+47/−33 across six hunks), `template/board.schema.json` applied cleanly
(+45/−33). Generator first, then the regenerated file, per the global constraint:

* `python3 template/board_schema.py --check-schema` immediately after the patch:
  `… template/board.schema.json is current` (exit 0).
* `python3 template/board_schema.py --write-schema` → `wrote …`, exit 0, and
  `sha256` of the file **unchanged** (`84d402f1a0d4cc…` before and after), i.e.
  the patch's schema hunks already are byte-for-byte the generator's output and
  the regeneration is a no-op — no hidden second authority crept in.
* `python3 template/board_schema.py --check-schema` afterwards: `is current`,
  exit 0.

What the generated schema now says (read back from `json_schema()`):

* **no `required`** — `lanes` defaults to 1, so `{"slug": "b"}` is accepted by
  both sides.
* `"patternProperties": {"^\\$": {}}` — a `$`-prefixed meta-key (`$schema`,
  `$comment`, `$id`) is allowed alongside `additionalProperties: false`, exactly
  as `validate` skips `key.startswith("$")`.
* `max-runtime`: `"pattern": "^\\s*(?:\\d+(?:\\.\\d+)?\\s*[hms]\\s*)+$"` — the
  duration language Task 11 widened `_DURATION_RE` to, so `"1h 30m"` is accepted
  by both.
* `targets`: `"uniqueItems": true` plus items
  `"pattern": "^(/|~$|~/)"` — the same three shapes `_kind_error("paths", …)`
  accepts, and duplicates refused on both sides.
* every `text`-kind option (`name`, `model`, `provider`, `model_override`,
  `provider_override`) carries `"pattern": "\\S"`, so a whitespace-only value is
  refused on both sides — the minLength-only schema was the other half of
  Important 2.
* the per-lane `default` moved *out* of the `oneOf` branches and onto the option,
  and each array branch's description now says "exactly `lanes` entries" (the one
  rule JSON Schema cannot state; `validate` keeps it).
* generator side: `unchecked` and the two dead `_kind_error` branches for `path`
  are gone; `_KIND_SCHEMA` and `_kind_error`'s known kinds are now one set, and
  `paths`/`gates`/`cards` each refuse a duplicate.

## Step 4 — green, and the whole suite

```
$ /usr/bin/python3 -m pytest -q tests/test_board_schema.py
83 passed in 0.54s          (exit 0)

$ PYTHON=/usr/bin/python3 ./test.sh
748 passed in 28.28s        (exit 0, 0 skipped)
```

Both match the brief (`PASS`; **748 passed**, 0 skipped — run as uid 1000, not
root, so the Task-2 "1 skipped" root branch does not apply).

## Step 5 — staged

`git add template/board.schema.json template/board_schema.py
tests/test_board_schema.py` then `git status --short`; the three files show as
`M` in the index with no unstaged remainder. The 20 files Tasks 0–11 staged were
left exactly as they were (this task's `git add` touches only its own three; two
of them, `board_schema.py` and `test_board_schema.py`, were already staged by
earlier tasks and are re-staged with this task's content). Nothing under
`docs/superpowers/plans/`, no `boards/**/work`, `boards/**/runs`, `TIMELINE.md`
or `boards/*/README.md` was touched. **No commit.**

## Concerns

* None blocking. The three red failures were all the brief's predicted ones for
  the predicted reasons, and both patches applied with zero drift, so this task
  produced no finding of its own.
* `validate` remains the authority for the two rules JSON Schema cannot state
  (`lanes`-length arrays, and `0m`/`0s` collapsing to "no budget"); the schema's
  `$comment` still declares that, so an editor can accept a manifest
  `board_schema.py` later refuses — by design, not by drift.
* The patch's `100755` index line for `board_schema.py` disagrees with the tree's
  `100644` (a brief-only cosmetic inaccuracy; content — the thing that matters —
  matched the stated blob exactly).
