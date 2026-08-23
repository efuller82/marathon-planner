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
- The desktop app exports the complete open plan as one deterministic local ZIP
  after validating and storing visible edits.
- Package schema version 1 contains a hashed manifest, importable plan JSON,
  authored-date iCalendar, local transfer instructions, and terrain-separated
  FIT files.
- Export validates member paths and generated filenames, writes atomically,
  replaces only recognized Marathon Planner packages, and preserves unrelated
  files and symbolic links.
- The full local gate compiles the project and runs 62 passing unit tests.
- CI is configured to run the same compilation and unit-test gate on pull
  requests.
- Physical Garmin-device compatibility remains unverified.

## This session

- Built issue #4 on `feature/4-plan-package-export` with a standard-library ZIP
  writer and desktop export action.
- Fixed archive member order, timestamps, permissions, and storage so identical
  plans produce identical ZIP bytes.
- Added a versioned manifest with SHA-256 inventory plus a complete version 1
  `plan.json` representation of the open user-authored plan.
- Added RFC 5545 all-day calendar events on each authored workout date, mapped
  to the matching ROAD and TRAIL FIT files without rescheduling.
- Added concise in-package instructions for terrain selection and account-free
  local USB transfer.
- Added atomic destination writes and guarded replacement for positively
  identified Marathon Planner packages only.
- Added synthetic archive, calendar, FIT-content, path-safety, replacement, and
  desktop-action coverage.

## Next

1. Start issue #5 from current `master` on `feature/5-usb-workout-install` and
   define the dry-run installation contract for a user-selected upcoming block.
2. Detect Garmin workout destinations conservatively and rotate only files
   positively identified as Marathon Planner output.
3. Keep physical-device compatibility explicitly unverified until an owner-run
   hardware test is available.

## Blockers

- None.
