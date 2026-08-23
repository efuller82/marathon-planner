# Status

- **Updated:** 2026-08-23

## Live

- The public source repository is available at
  `https://github.com/efuller82/marathon-planner`.
- The "Marathon Planner" GitHub project contains the approved feature backlog
  in priority order.
- A local Tkinter editor runs with `python run.py`; users can add and remove
  ordered workout rows, validate authored weeks, and switch among imported
  weeks.
- The core model supports validated distance goals (`mi`, `km`, or `m`) and
  time goals (`sec`, `min`, or `hr`).
- Each workout preserves distinct ROAD and TRAIL choices under one
  user-authored goal.
- Version 1 local JSON plan import validates file type, size, exact schema,
  duplicate fields, dates, bounds, and domain values before replacing the open
  plan.
- The full local gate compiles the project and runs 35 passing unit tests.
- CI is configured to run the same compilation and unit-test gate on pull
  requests.

## This session

- Built issue #2 on `feature/2-safe-plan-import` using only the Python standard
  library.
- Documented the exact version 1 JSON shape for dated weeks, goals, and ROAD and
  TRAIL choices.
- Added bounded UTF-8 file loading and fail-closed validation for untrusted
  local files without logging plan contents.
- Added atomic UI replacement, an imported-week selector, and preservation of
  authored text, values, choices, and ordering.
- Added synthetic import and failure-path coverage and completed a withdrawn
  Tkinter end-to-end import smoke test.

## Next

1. Start issue #3 from current `master` on `feature/3-fit-encoding` and select a
   zero-cost, pinned FIT encoding approach.
2. Encode deterministic ROAD and TRAIL workout variants without changing the
   authored goal.
3. Add synthetic round-trip validation, then open one pull request and merge
   only after the full gate is green.

## Blockers

- None.
