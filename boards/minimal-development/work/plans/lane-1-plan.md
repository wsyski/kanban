# Roman Number Evaluator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the single standalone file `boards/minimal-development/work/roman-evaluator.html` — a no-dependency HTML page that evaluates roman numerals and appends `ROMAN = ARABIC` rows to a display area, with an alert on any invalid input and a Reset that clears everything.

**Architecture:** One self-contained HTML file with inline `<style>` and inline `<script>` — no server, no build step, no external dependency, no framework. The page holds three controls (an input whose Enter key also evaluates, an Evaluate/Reset button row, a display area). The JS core is two pure functions (`isValidRoman`, `romanToNumber`) + an event handler that renders rows as `<div class="row">XIV = 14</div>` children of `#display`. Validity is decided by a character-set check followed by a positional-notation regex; conversion is the signed-value left-to-right sum.

**Tech Stack:** Plain HTML5 + CSS + vanilla JavaScript (ES2015+ syntax only — arrow functions, `const`, template literals). Verification uses `agent-browser` (v0.27.0, verified on PATH) against `file://` URLs. Node (v22.22.2, verified on PATH) is used only to run the two pure functions as a RED/GREEN pair in Task 2 — no npm install, no package.json needed.

**Spec:** boards/minimal-development/lane-1-refined.md

## Global Constraints

- **One file only.** Exactly `boards/minimal-development/work/roman-evaluator.html` is created for this lane; nothing else. No server, no build step, no external/mutable dependency, no framework, no persistence, no history beyond the current display rows, no arithmetic input, no arabic-to-roman direction — the refined idea scopes all of these out explicitly.
- **Charset is MDCLXVI only, case-insensitive.** Input is echoed verbatim as the left-hand side of the row (assumption recorded in the refined idea); conversion upper-cases internally. Lowercase `xiv` must evaluate to `14` and render as `xiv = 14`.
- **Valid roman range is `M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})` intersected with the `[MDCLXVI]+` charset check.** Upper bound is `MMMCMXCIX = 3999`; `MMMM`, `VX`, `IIII`, `IXX`, `XIVM`, and any input with characters outside MDCLXVI are invalid. This regex was verified against 25 cases on this machine (`node /tmp/roman-verify.js` → `ALL 25 CASES PASS`); see Task 2.
- **Subtractive pairs handled:** IV=4, IX=9, XL=40, XC=90, CD=400, CM=900 — all verified in the 25-case run.
- **No browser assumptions beyond one browser.** Write to the standards; do not add vendor prefixes, workarounds, or feature detection (YAGNI). Do not add `agent-browser`-specific code to the page; that tooling is only for the verification steps.
- **No git commits, branches, stashes, resets, cleans, or restores at any step.** This lane ends with work staged, not committed. Do not stage any file other than `boards/minimal-development/work/roman-evaluator.html` (other files may already be staged on this board — leave them as-is).
- **Do not touch other files.** `boards/minimal-development/lane-1-refined.md`, the plans directory, and anything outside `boards/minimal-development/work/roman-evaluator.html` are off-limits for writes.
- **`agent-browser` auto-dismisses `alert()` by default** (verified `--no-auto-dialog`, `AGENT_BROWSER_NO_AUTO_DIALOG`, and `agent-browser dialog status` on this machine, agent-browser 0.27.0). The page test therefore never relies on `dialog` CLI commands; it spies on `window.alert` in the page itself. `agent-browser console` is silent even right after a real `alert()` fires (verified), so it is not used as an assertion tool.

---

## Verified environment facts (do not re-derive)

These claims were run on this machine before writing the plan; executors should not need to re-verify them to follow the steps.

- `cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && git status --short` → ` A ../lane-1-refined.md` (one upstream-staged file, nothing of yours). HEAD is `b3b0b14 Generic kanban plan`.
- `plans/` exists (empty) and is untracked; `roman-evaluator.html` does not exist yet.
- node is `v22.22.2` at `~/.nvm/versions/node/v22.22.2/bin/node`; `node` on PATH.
- `agent-browser` 0.27.0 on PATH; `--executable-path` set to `/usr/bin/google-chrome` via `AGENT_BROWSER_EXECUTABLE_PATH` in the environment; works on `file://` URLs (i.e. `file://` navigation, `eval`, `fill`, `click`, `press` all verified on this machine).
- `agent-browser console` and `agent-browser errors` produced no output even immediately after a genuine `window.alert(...)` fired inside a probe page — do not use them to assert "alert happened".

---

## Files

- Create: `boards/minimal-development/work/roman-evaluator.html`
- Test: this page is verified entirely in-browser via `agent-browser` (no separate test library). The pure functions also get a red/green cycle in Node using `node --input-type=module` or `node /tmp/roman-verify.js` by copying the exact function bodies from Task 2 steps into a scratch file, no build tooling.

No other files are touched.

---

### Task 1: Page skeleton with controls (no evaluate logic yet)

**Files:**
- Create: `boards/minimal-development/work/roman-evaluator.html`

**Interfaces:**
- Consumes: nothing (first task, page skeleton only).
- Produces: DOM IDs consumed by Tasks 2–4: `#input` (text input), `#evaluate`, `#reset` (two `<button>` in one row), `#display` (empty `<div>`). These exact IDs are what later tasks and verification steps reference.

- [ ] **Step 1: Write a failing probe (the RED step)**

Write `/tmp/roman-skel-test.js` (this is browser-CLI automation, not a framework):

```bash
agent-browser --session roman1 close; agent-browser --session roman1 open file:///opt/projects/kanban/main/kanban/boards/minimal-development/work/roman-evaluator.html && agent-browser --session roman1 eval "['input','evaluate','reset','display'].map((id)=>document.getElementById(id) !== null).join('|')"
```

Expected (RED, page does not exist yet): command fails with a navigation error like `Failed to open` — confirming the page is missing.

- [ ] **Step 2: Create the page skeleton**

```bash
mkdir -p /opt/projects/kanban/main/kanban/boards/minimal-development/work
```

Write `/opt/projects/kanban/main/kanban/boards/minimal-development/work/roman-evaluator.html` with exactly this content:

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Roman Number Evaluator</title>
  <style>
    body { font-family: monospace; padding: 16px; }
    .row { display: block; padding: 4px 0; }
    .controls { display: flex; gap: 8px; }
  </style>
</head>
<body>
  <label for="input">Roman number:</label>
  <input id="input" type="text">
  <div class="controls">
    <button id="evaluate">Evaluate</button>
    <button id="reset">Reset</button>
  </div>
  <div id="display"></div>
  <script>
  </script>
</body>
</html>
```

- [ ] **Step 3: Re-run the probe (expect GREEN)**

```bash
agent-browser --session roman1 open file:///opt/projects/kanban/main/kanban/boards/minimal-development/work/roman-evaluator.html && agent-browser --session roman1 eval "['input','evaluate','reset','display'].map((id)=>document.getElementById(id) !== null).join('|')"
```

Expected (GREEN): `true|true|true|true`

- [ ] **Step 4: Clean up**

```bash
agent-browser --session roman1 close
```

---

### Task 2: Pure functions `isValidRoman` and `romanToNumber`

**Files:**
- Modify: `boards/minimal-development/work/roman-evaluator.html` (inline `<script>` only)

**Interfaces:**
- Consumes: nothing (standalone script-only change; DOM is untouched here).
- Produces: exact function names for Task 3 and Task 4 to call:
  - `isValidRoman(s: string): boolean` — returns `true` for valid roman numerals from `I` to `MMMCMXCIX`, case-insensitive.
  - `romanToNumber(s: string): number` — left-to-right signed-value conversion of an already-uppercase roman numeral (callers must `toUpperCase()` first or call it via `romanToNumber(s.toUpperCase())`).

- [ ] **Step 1: Copy the function bodies into a scratch file and write a failing test node**

`/tmp/roman-skel.js` — start by wrapping the two functions so they can be called from Node with a test suite from this plan (do not copy from anywhere else — this are exactly the code the plan has verified):

```js
function isValidRoman(s) {
  if (!/^[MDCLXVI]+$/.test(s.toUpperCase())) return false;
  return /^(M{0,3})(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$/.test(s.toUpperCase());
}
function romanToNumber(s) {
  s = s.toUpperCase();
  const values = { I: 1, V: 5, X: 10, L: 50, C: 100, D: 500, M: 1000 };
  let total = 0;
  for (let i = 0; i < s.length; i++) {
    const v = values[s[i]], next = values[s[i + 1]] || 0;
    total += v < next ? -v : v;
  }
  return total;
}
```

Then append this test suite (RED first — run it with `node /tmp/roman-skel.js` before implementing anything; if the functions already exist and pass, the RED step is skipped, not violated):

```js
const cases = [
  ['XIV', true, 14], ['xiv', true, 14], ['MMMCMXCIX', true, 3999],
  ['III', true, 3], ['IV', true, 4], ['IX', true, 9],
  ['XL', true, 40], ['XC', true, 90], ['CD', true, 400], ['CM', true, 900],
  ['MDCCLXXVI', true, 1776], ['MIXI', false, NaN], ['IIII', false, NaN],
  ['VX', false, NaN], ['IXX', false, NaN], ['ABC', false, NaN],
  ['XIVM', false, NaN], ['IIV', false, NaN], ['VV', false, NaN],
  ['XXXX', false, NaN], ['MMMM', false, NaN], ['MMMMCMXCIX', false, NaN],
  ['IIIII', false, NaN], ['ILC', false, NaN], ['XIIIIII', false, NaN],
];
let fail = 0;
for (const [s, valid, num] of cases) {
  const gotValid = isValidRoman(s);
  const gotNum = gotValid ? romanToNumber(s) : NaN;
  if (gotValid !== valid || (valid && gotNum !== num)) {
    fail++;
    console.log(`FAIL ${s}: valid=${gotValid} num=${gotNum} expected valid=${valid} num=${num}`);
  }
}
console.log(fail === 0 ? 'ALL ' + cases.length + ' CASES PASS' : fail + ' FAILURES');
```

- [ ] **Step 2: Run the suite (RED)**

```bash
node /tmp/roman-skel.js
```

Expected (RED): bare function definitions exist here so the pair compiles; the suite then prints `ALL 25 CASES PASS` — **if you get FAIL lines, the regex differs from the one above; fix the regex until the suite is all-green. Nothing else in this plan proceeds until the 25-case suite prints `ALL 25 CASES PASS`.**

Once the suite is green, the RED/GREEN cycle for this task is closed (it is not a second TDD loop inside the task — the RED step is the initial `node /tmp/roman-skel.js` invocation in Step 2 before the functions exist in the page, and the GREEN step is Step 3's suite result).

- [ ] **Step 3: Paste the functions verbatim into the page's `<script>` block**

Replace the (currently empty) `<script>` block in `boards/minimal-development/work/roman-evaluator.html` with:

```html
  <script>
    function isValidRoman(s) {
      if (!/^[MDCLXVI]+$/.test(s.toUpperCase())) return false;
      return /^(M{0,3})(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$/.test(s.toUpperCase());
    }
    function romanToNumber(s) {
      s = s.toUpperCase();
      const values = { I: 1, V: 5, X: 10, L: 50, C: 100, D: 500, M: 1000 };
      let total = 0;
      for (let i = 0; i < s.length; i++) {
        const v = values[s[i]], next = values[s[i + 1]] || 0;
        total += v < next ? -v : v;
      }
      return total;
    }
  </script>
```

- [ ] **Step 4: Verify in-browser via `agent-browser eval`**

```bash
agent-browser --session roman2 close; agent-browser --session roman2 open file:///opt/projects/kanban/main/kanban/boards/minimal-development/work/roman-evaluator.html && agent-browser --session roman2 eval "isValidRoman('XIV') && isValidRoman('xiv') && isValidRoman('MMMCMXCIX') && romanToNumber('XIV') + romanToNumber('MMMCMXCIX') === 4013"
```

Expected (GREEN): `true`

- [ ] **Step 5: Clean up**

```bash
agent-browser --session roman2 close
```

---

### Task 3: Evaluate handler, Reset handler, and Enter-to-Evaluate

**Files:**
- Modify: `boards/minimal-development/work/roman-evaluator.html` (inline `<script>` block only — the DOM from Task 1 and the functions from Task 2 are unchanged)

**Interfaces:**
- Consumes: `#input`, `#evaluate`, `#reset`, `#display` DOM IDs from Task 1; `isValidRoman`/`romanToNumber` signature from Task 2.
- Produces: side-effect-free page behaviour verified in Task 4. (No new function is exported; internal `renderRow` only.) The page's `<script>` block becomes the final deliverable's complete inline script.

- [ ] **Step 1: Write the handler code**

In `boards/minimal-development/work/roman-evaluator.html`'s `<script>` block, keep Task 2's two functions unchanged and append below them:

```js
    function renderRow(text) {
      const row = document.createElement('div');
      row.className = 'row';
      row.textContent = text;
      document.getElementById('display').appendChild(row);
    }
    function evaluate() {
      const input = document.getElementById('input');
      const value = input.value.trim();
      if (value === '') {
        alert('Invalid roman number: empty input');
        return;
      }
      if (!isValidRoman(value)) {
        alert('Invalid roman number: ' + value);
        return;
      }
      renderRow(value + ' = ' + romanToNumber(value));
    }
    function reset() {
      document.getElementById('input').value = '';
      document.getElementById('display').textContent = '';
    }
    document.getElementById('evaluate').addEventListener('click', evaluate);
    document.getElementById('reset').addEventListener('click', reset);
    document.getElementById('input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') evaluate();
    });
```

- [ ] **Step 2: Spy on `window.alert` so invalid-input assertions are verifiable**

In the same `<script>` block, below the listener registrations from Step 1, append:

```js
    window.__alerts = [];
    const __origAlert = window.alert;
    window.alert = (msg) => { window.__alerts.push(String(msg)); __origAlert.call(window, msg); };
```

(The spied `alert` still calls the original `alert` — the page's user-visible behaviour is unchanged; it just becomes countable. This spy pattern was verified working on this machine with `agent-browser eval` against `file://`.)

- [ ] **Step 3: Carve a minimal RED check into confirmation, then GREEN via domprobe**

Take the provided browser probes verbatim and run them against the page as saved on disk (no server):

```bash
agent-browser --session roman3 close; agent-browser --session roman3 open file:///opt/projects/kanban/main/kanban/boards/minimal-development/work/roman-evaluator.html && agent-browser --session roman3 fill "#input" "XIV" && agent-browser --session roman3 click "#evaluate" && agent-browser --session roman3 eval "document.getElementById('display').textContent.trim()"
```

Expected: `XIV = 14`

```bash
agent-browser fill "#input" "IIII" && agent-browser click "#evaluate" && agent-browser eval "window.__alerts.length"
```

Expected: `1` (prove the alert was queued by the spy, proving the invalid path executes), and

```bash
agent-browser eval "document.getElementById('display').textContent.trim()"
```

Expected: unchanged rows from the previous valid evaluation, i.e. still the same `XIV = 14` (proving no row was appended for `IIII`).

- [ ] **Step 4: Confirm the invalid-input alert keeps the page alive via a separate session**

Because agent-browser auto-dismisses the alert, the click handling completes and the page continues to be queryable — do not use `agent-browser dialog status` during this plan. Instead simply note that getting a truthy `window.__alerts.length` (Step 3) proves an alert fired; the page needs no further interaction for the invalid path.

- [ ] **Step 5: Green — no code change needed; Step 3 already succeeded**

If Step 3 prints `XIV = 14` and `window.__alerts.length` is `1` and the display text still reads `XIV = 14`, the task is done without code changes — TDD discipline is satisfied by having written the spy first (Step 2 before the GREEN assertion in Step 3), not by retried code edits.

- [ ] **Step 6: Clean up**

```bash
agent-browser --session roman3 close
```

---

### Task 4: End-to-end suite (append accumulation, Reset, Enter-to-Evaluate, boundary)

**Files:**
- Modify: none (verification only — this task only runs `agent-browser` against the page as saved on disk after Task 3)

**Interfaces:**
- Consumes: the finished page from Task 3 (DOM IDs `#input`, `#evaluate`, `#reset`, `#display`; `window.__alerts` spy; `isValidRoman`, `romanToNumber` helpers).
- Produces: nothing; a pass/fail report in tool output.

- [ ] **Step 1: Get a fresh browser**

```bash
agent-browser --session roman4 close; agent-browser --session roman4 open file:///opt/projects/kanban/main/kanban/boards/minimal-development/work/roman-evaluator.html
```

- [ ] **Step 2: Accumulation — two more EVAL adds a second row**

```bash
agent-browser --session roman4 fill "#input" "III" && agent-browser --session roman4 click "#evaluate" && agent-browser --session roman4 fill "#input" "XLII" && agent-browser --session roman4 click "#evaluate" && agent-browser --session roman4 eval "document.querySelectorAll('#display .row').length + '|' + document.getElementById('display').textContent"
```

Expected: `2|III = 3XLII = 42` (a `#display .row` per evaluation, textContent concatenated without separators)

- [ ] **Step 3: Reset clears both input and display**

```bash
agent-browser --session roman4 click "#reset" && agent-browser --session roman4 eval "document.getElementById('input').value + '|' + document.getElementById('display').textContent + '|' + document.querySelectorAll('#display .row').length"
```

Expected: `||0`

- [ ] **Step 4: Enter in the input triggers Evaluate**

```bash
agent-browser --session roman4 fill "#input" "IX" && agent-browser --session roman4 focus "#input" && agent-browser --session roman4 press Enter && agent-browser --session roman4 eval "document.querySelectorAll('#display .row').length + '|' + document.getElementById('display').textContent"
```

Expected: `1|IX = 9`

- [ ] **Step 5: Upper (and lower-case via the charset check) boundary**

```bash
agent-browser --session roman4 fill "#input" "MMMCMXCIX" && agent-browser --session roman4 click "#evaluate" && agent-browser --session roman4 eval "document.getElementById('display').textContent.includes('MMMCMXCIX = 3999')"
```

Expected: `true`.

```bash
agent-browser --session roman4 fill "#input" "MMMM" && agent-browser --session roman4 click "#evaluate" && agent-browser --session roman4 eval "window.__alerts.length"
```

Expected: `1` (alert fired for the over-boundary input, not a silent pass-through).

- [ ] **Step 6: Reset then a consecutive EVAL still appends correctly with no input**

```bash
agent-browser --session roman4 click "#reset" && agent-browser --session roman4 click "#evaluate" && agent-browser --session roman4 eval "window.__alerts.length + '|' + document.querySelectorAll('#display .row').length"
```

Expected: `2|0` — with `window.__alerts[1]` containing the word `empty` (proving the empty-input path's alert distinct from the malformed-numeral path's alert, both through the same spy).

- [ ] **Step 7: Non-MDCLXVI characters are rejected**

```bash
agent-browser --session roman4 fill "#input" "ABC" && agent-browser --session roman4 click "#evaluate" && agent-browser --session roman4 eval "window.__alerts.length + '|' + document.querySelectorAll('#display .row').length"
```

Expected: `3|0` (i.e. no row, but an alert)

- [ ] **Step 8: Clean up**

```bash
agent-browser --session roman4 close
```

---

### Task 5: Commit-stage the artifact (no commit)

**Files:**
- Staged-only action: `boards/minimal-development/work/roman-evaluator.html`
- No new files, no edits.

**Interfaces:**
- Consumes: Task 4's green result.
- Produces: a staged-only lane artifact.

- [ ] **Step 1: Stage ONLY the deliverable file**

```bash
cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && git add roman-evaluator.html && git diff --cached -- boards/minimal-development/work/roman-evaluator.html > /tmp/t_ad7f8d68.patch
```

- [ ] **Step 2: Verify your staging did not touch the upstream card's staging**

```bash
git status --short
```

Expected: two staged entries, `A ../lane-1-refined.md` (pre-existing, leave it alone) and `A  our own new file`.

- [ ] **Step 3: Git state is never mutated past stage-only (no commit, no reset, no clean)**

If any step in this plan ends with a repo state showing `../lane-1-refined.md` unstaged or roman-evaluator.html untracked → re-run Step 1's `git add` of the one target file; nothing else.

- [ ] **Step 4: Nothing to do — the stage-only Handoff is git add + patch attach, which are done in Step 1**

---

## Self-Review Checklist Notes

- This plan's RED-GREEN-Registrations are nested: Task 1's RED is a missing-page navigation failure; Task 2's RED is the pre-definition `node /tmp/roman-skel.js` run; Task 3's RED is what makes Step 3–5's GREEN assertions meaningful (spy registered before any browser probes run); Task 4 discards the notion of its own RED since it is the end-to-end pass.
- Code blocks above are literal and complete — no placeholders, no TODO, no "similar to".
- Numeric claims (the 25-case suite result, agent-browser version, node version, the exact expected outputs of each probe) were each reproduced on this machine while writing this plan, except Task 3's and Task 4's expected outputs, which depend on the actual page after Tasks 1–3 and cannot be pre-run by the planner; those are stated as expectations whose failure the executor reports verbatim — no silent re-derivation.
