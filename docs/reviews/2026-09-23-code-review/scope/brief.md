# ocr-review brief — kanban (all-files, sequential)

Repo: /opt/projects/kanban/main/kanban (git, branch `main`, HEAD 59bc279 "Generic kanban plan")
Scope: `all-files` — the whole repository, resolved by `ocr scan --preview`. There is NO diff:
whole files are under review.

Resolution fact: 135 files total, 76 reviewable, 59 excluded (34 unsupported_ext, 25
user_exclude). 135 git files accounted for (76+59), 0 unmentioned, 0 untracked, no symlinks.

Manifest (reviewable, 76 paths): scope/manifest.txt
Test files inside the manifest (31 paths, handed to the test aspect explicitly): scope/tests.txt

Exclusions (holes in coverage, already accounted for — do NOT re-litigate them):
- unsupported_ext (34): all Markdown docs (AGENTS.md, CLAUDE.md, DESIGN.md, README.md,
  TIMELINE.md, boards/*/README.md, boards/*/lane-*.md, docs/**, template/roles/*.md,
  template/roles/*/SOUL.md), the diagrams driver/flow.drawio and driver/flow.mmd.
- user_exclude (25): `.opencodereview/rule.json` excludes `boards/*/work/**` — the sample board
  work products (boards/is-even/work/*, boards/roman-evaluator-java/work/**, 
  boards/roman-evaluator-js/work/**). This is the repo's own ocr config, not a defect.

Repo shape (from the 2026-09-19 split): template/ = shared modules both drivers import
(lanes, board_schema, card_render, driver_lock, card-bodies, roles); driver/ = the kanban
driver (run.py, file_lanes, run-audit, reports, *.sh); tests/ + ./test.sh at root
(test_layer_boundary.py holds the split).

Rules for this run:
- READ-ONLY. Do not modify the repo, do not run the driver, do not create boards or lanes.
  Static checks only (e.g. `bash -n`, `python3 -m py_compile`) are fine.
- Stay inside the manifest. Do not re-derive file selection, do not wander outside it.
- Review the whole file, not a diff. Cite `file_path:line_number` for every finding.
- Write your full report to your report file. Return only distilled findings in your final
  answer: each finding as SEVERITY (Critical|Important|Suggestion) — file:line — what is wrong
  — why it matters — one-line fix. Cap the returned list at the top 15 by severity; the full
  list lives in the report file.
