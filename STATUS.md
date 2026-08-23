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
- Each dated workout deterministically encodes to distinct ROAD and TRAIL FIT
  protocol 2.0/profile 21.00 files without changing the authored goal.
- FIT filenames, public workout identifiers, file numbers, timestamps, and
  bytes are stable and collision-safe within a plan.
- The full local gate compiles the project and runs 44 passing unit tests.
- CI is configured to run the same compilation and unit-test gate on pull
  requests.
- Physical Garmin-device compatibility remains unverified.

## This session

- Built issue #3 on `feature/3-fit-encoding` with an in-repository,
  standard-library FIT writer and no runtime dependency.
- Encoded Garmin-profile `file_id`, `workout`, and `workout_step` messages with
  deterministic headers, definition records, timestamps, identifiers, and
  checksums.
- Converted every supported distance unit to FIT centimetres and every
  supported time unit to FIT milliseconds using deterministic decimal
  rounding.
- Preserved the same goal across ROAD and TRAIL artifacts while identifying
  the selected authored terrain choice in device-facing labels.
- Added a synthetic FIT parser, CRC checks, round-trip assertions, stable-byte
  golden coverage, collision cases, UTF-8 bounds, and failure paths.
- Independently parsed a synthetic output with temporary, SHA-256-verified
  `fitdecode` 0.11.0; it recognized all three messages and decoded the goal.

## Next

1. Start issue #4 from current `master` on `feature/4-plan-package-export` and
   define the deterministic ZIP layout.
2. Export both FIT variants plus authored calendar material and concise local
   transfer instructions without rescheduling workouts.
3. Validate archive paths and replacement behavior with a synthetic package,
   then open one pull request and merge only after the full gate is green.

## Blockers

- None.
