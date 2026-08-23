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
- The full gate on `master` compiles the project and runs 62 passing unit tests.
- USB installation and physical Garmin-device compatibility are not live and
  remain explicitly unverified.

## This session

- Started issue #5 from current `master` on
  `feature/5-usb-workout-install` and moved its board card to In progress.
- Added a preview-only USB installation contract for an explicit one-based
  start week, contiguous week count, and ROAD or TRAIL selection.
- Device detection now requires one bounded Garmin `GarminDevice.xml`, a valid
  device ID, and one unambiguous existing `NewFiles` FIT destination; unsafe,
  missing, symbolic-link, and malformed paths fail closed.
- Defined device-bound ownership metadata with exact schema, safe relative FIT
  paths, byte counts, and SHA-256 digests. Duplicate fields, non-finite values,
  traversal, wrong-device manifests, unrelated collisions, and modified owned
  files are rejected.
- Dry runs list copies, verified replacements, verified removals, and ownership
  metadata changes. Missing previously owned files are treated as already
  consumed by the device; unrelated files are preserved.
- Added desktop controls for start week, block size, terrain, device-root
  selection, and a scrollable preview that states no files were changed.
- Added synthetic-filesystem and headless desktop coverage. The feature-branch
  gate compiles the project and runs 80 passing unit tests.
- No USB mutation function exists yet, so this milestone cannot write, replace,
  or remove any device file and never requests Garmin credentials.

## Next

1. On `feature/5-usb-workout-install`, implement confirmation-gated application
   of the exact dry-run contract, revalidating device identity and ownership
   immediately before each change.
2. Make staged writes failure-safe, update the ownership manifest last, and add
   synthetic interruption, collision, tampering, and unrelated-file tests.
3. Open the issue's single pull request only after the full install acceptance
   criteria are complete and the local gate remains green.
4. Keep physical-device compatibility explicitly unverified until an owner-run
   Garmin hardware test is available.

## Blockers

- None.
