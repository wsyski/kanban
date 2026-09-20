# ocr-review brief — kanban (all-files, parallel)

Repo: /opt/projects/kanban/main/kanban (git, branch `main`)
Scope: `all-files` — the whole repository, resolved by `ocr scan --preview`. There is NO diff:
whole files are under review.
Resolution fact: 132 files total, 50 reviewable, 82 excluded (42 unsupported_ext, 39
default_path, 1 too_large). 132 git files accounted for, 0 unmentioned, no symlinks.

Manifest (reviewable, 50 paths): /home/wos/.hermes/profiles/coder/cache/scratch/ocr-review-kanban/manifest.txt
Test files dropped by ocr as default_path (39 paths, handed to the test aspect explicitly):
/home/wos/.hermes/profiles/coder/cache/scratch/ocr-review-kanban/tests.txt

Exclusions (holes in coverage, already accounted for — do NOT re-litigate them):
- unsupported_ext (42): all Markdown docs, the flow.drawio/flow.mmd diagrams, driver/flow.mmd,
  template/card-bodies/*.txt, template/roles/*/SOUL.md, template/roles/README.md
- default_path (39): every test source (tests/**, boards/*/work/**/src/test/**, *.test.js)
- too_large (1): boards/roman-evaluator-js/work/package-lock.json

Repo shape (from the 2026-09-19 split): template/ = shared modules both drivers import
(lanes, board_schema, card_render, driver_lock, card-bodies, roles); driver/ = the kanban
driver (run.py, file_lanes, run-audit, reports, *.sh); bots/ = the second driver.

Rules for this run:
- READ-ONLY. Do not modify the repo, do not run the driver, do not create boards or lanes.
  Static checks only (e.g. `bash -n`, `python3 -m py_compile`) are fine.
- Stay inside the manifest. Do not re-derive file selection, do not wander outside it.
- Review the whole file, not a diff. Cite `file_path:line_number` for every finding.
- Write your full report to your report file. Return only distilled findings in your final
  answer: each finding as SEVERITY (Critical|Important|Suggestion) — file:line — what is wrong
  — why it matters — one-line fix. Cap the returned list at the top 15 by severity; the full
  list lives in the report file.
