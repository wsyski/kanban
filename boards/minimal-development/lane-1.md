## Idea 1: roman-evaluator

Create one file, `boards/minimal-development/work/roman-evaluator.html`: a standalone
HTML page (no build step, no external dependencies, no server) implementing a
roman number evaluator. It contains:

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

Nothing else. No styling framework, no JavaScript libraries, no persistence,
no history beyond the current display rows, no arithmetic input, no
arabic-to-roman direction. Plain HTML, CSS and vanilla JavaScript in the one
file.

This idea is deliberately complete and unambiguous: it exercises the board
end to end with a small self-contained artefact. If a card finds itself with
a decision to make, the answer is the smallest thing that satisfies the lines
above.

### Done means

- `boards/minimal-development/work/roman-evaluator.html` exists and is the only file
  created for this idea.
- Opening the file directly in a browser (`file://`) works without a server.
- Evaluating `XIV` appends exactly one row `XIV = 14`; evaluating `IIII`
  shows an alert and appends nothing; Reset clears input and display.
