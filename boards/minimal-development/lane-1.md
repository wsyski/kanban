## Idea 1: roman-evaluator

Build a small browser page, entry point
`boards/minimal-development/work/roman-evaluator.html`, implementing a roman
number evaluator.

One set of files, two ways to launch it — with no change to any HTML, CSS or
JavaScript file between them. Google Chrome is the only browser that must
work.

1. From a web server: any static file server serving the `work/` directory,
   Chrome started normally. For example:

       python3 -m http.server 8000 --directory boards/minimal-development/work
       # then open http://localhost:8000/roman-evaluator.html

2. Locally from `file://`, no server, via `work/run.sh` — a shell script
   that is part of the deliverable. Chrome blocks ES module imports from
   `file://` by default, so the script starts it with
   `--allow-file-access-from-files` in a throwaway profile. The flag is
   ignored when Chrome is already running, and it lets any local page read
   local files, so it must never touch the everyday profile. The script:
   - finds its own directory, so it works from any current directory;
   - exits non-zero with a clear message if `google-chrome` is not on PATH;
   - creates a temporary profile directory and removes it when Chrome exits;
   - passes any extra arguments through to Chrome (so a card can run
     `./run.sh --headless --dump-dom` to check the page without a window).

   At its core it runs:

       google-chrome --allow-file-access-from-files \
         --user-data-dir="$profile" "$@" \
         "file://$dir/roman-evaluator.html"

Both launches work only if every path in the page and its modules is
relative (`./roman.js`, `./style.css`) — no absolute paths, no `file://` or
`http://` URLs, nothing that depends on how the page was opened.

The page contains:

- a text input field for a roman number,
- two buttons in one row below the input: **Evaluate** and **Reset**,
- a display area below the button row.

Behaviour:

- Clicking **Evaluate** reads the input as a roman number and appends a new
  row to the display area in the form `ROMAN = ARABIC` (for example
  `XIV = 14`). Each evaluation adds a new row; previous rows are kept.
- An invalid roman number produces an `alert()` containing an error message
  and appends no row. Invalid means: empty input, characters outside
  `MDCLXVI` (case-insensitive), or a malformed numeral (for example `IIII`,
  `VX`, `IXX`). Subtractive notation (`IV`, `IX`, `XL`, `XC`, `CD`, `CM`)
  must be handled; `MMMCMXCIX` (3999) is a valid upper bound.
- Clicking **Reset** clears both the input field and the display area.
- Pressing Enter in the input field triggers Evaluate (optional but
  preferred).

Structure:

- JavaScript lives in separate files written as ES modules (`import` /
  `export`), loaded by the page with `<script type="module">`. The roman
  parsing logic is its own module with no DOM access, so it can be tested
  alone.
- CSS lives in its own file.
- The JavaScript modules are unit-tested; the HTML page itself is not tested.

Technology preferences — the preferred stack is whatever already exists on
this workstation:

- Plain HTML, CSS and JavaScript; no JavaScript libraries in the page.
- Bootstrap is the preferred CSS framework, not a requirement: plain CSS is
  fine where it is simpler. If used, it is a local copy — no CDN, the page
  must work offline.
- Jest is the preferred test runner for the modules, testing the ES modules
  as they are — no bundling or build step for the page.
- Project-level packages (Jest, Bootstrap) may be fetched into the project by
  a package manager already on the workstation. A runtime or tool the
  workstation does not have is never installed and never silently swapped
  for something else: the lane names what is missing, recommends what to
  install, and fails.

Nothing else. No persistence, no history beyond the current display rows,
no arithmetic input, no arabic-to-roman direction.

This idea is deliberately complete and unambiguous: it exercises the board
end to end with a small self-contained artefact. If a card finds itself with
a decision to make, the answer is the smallest thing that satisfies the lines
above.

### Done means

- Everything for this idea lives under `boards/minimal-development/work/`:
  the entry page, its CSS and JS module files, the executable `run.sh`, the
  module tests, and the test tooling they need (package manifest, test config, installed packages).
  Those are deliverables, not scratch — nothing else is left behind.
- The unit tests pass, covering at least `XIV` → 14, `MMMCMXCIX` → 3999,
  and rejection of `IIII`, `VX`, `IXX`, empty input and a character outside
  `MDCLXVI`.
- `./run.sh` opens the page in Chrome from `file://` with no server
  running; `./run.sh --headless --dump-dom` prints the page's DOM and exits.
- In both launches above — served over HTTP, and from `file://` via
  `run.sh` — using the same unmodified files: evaluating `XIV` appends
  exactly one row `XIV = 14`; evaluating `IIII` shows an alert and appends
  nothing; Reset clears input and display.
