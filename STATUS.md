# Status

- **Updated:** 2026-08-23

## Live

- The public source repository is available at
  `https://github.com/efuller82/marathon-planner`.
- The "Marathon Planner" GitHub project contains the approved feature backlog
  in priority order.
- A local Tkinter weekly editor runs with `python run.py`; users can add and
  remove ordered workout rows and validate each authored week.
- The core model supports validated distance goals (`mi`, `km`, or `m`) and
  time goals (`sec`, `min`, or `hr`).
- Each weekly workout preserves distinct ROAD and TRAIL choices under one
  user-authored goal.
- The full local gate compiles the project and runs 17 passing unit tests.
- CI is configured to run the same compilation and unit-test gate on pull
  requests.

## This session

- Renewed GitHub CLI authentication and the narrow GitHub Projects scopes.
- Published the repository publicly, created the project board, and seeded
  issues #1 through #5 for editing, safe import, FIT encoding, package export,
  and USB installation.
- Built issue #1 on `feature/1-weekly-plan-editor`: added ordered week/workout
  models, form translation, paired choice validation, and the Tkinter row
  editor.
- Added headless domain/editor/UI-action tests and verified the actual Tkinter
  widget flow with a withdrawn-window smoke test.
- Tightened numeric validation so non-finite goals cannot enter a plan.

## Next

1. Start issue #2 from current `master` on
   `feature/2-safe-plan-import` and define the versioned local JSON plan shape.
2. Validate file type, size, schema, and values before atomically replacing the
   open weekly plan.
3. Add synthetic import tests, then open one pull request and merge only after
   the full gate is green.

## Blockers

- None.
