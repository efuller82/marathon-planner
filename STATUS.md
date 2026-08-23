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
- The desktop USB installer previews an explicit contiguous week block and
  ROAD or TRAIL selection before asking for confirmation.
- Confirmed USB application regenerates the exact preview, revalidates Garmin
  identity and device-bound SHA-256 ownership before each change, stages new
  bytes, rolls back interrupted commits, and updates ownership metadata last.
- USB installation never requests Garmin credentials and preserves unrelated
  files. Missing previously owned workouts are treated as already consumed by
  the device.
- The full gate compiles the project and runs 92 passing unit tests using only
  synthetic workout and filesystem data.
- Physical Garmin-device compatibility remains explicitly unverified.

## This session

- Completed issue #5 application on `feature/5-usb-workout-install` without
  changing the established dry-run contract.
- Added a warning confirmation dialog that applies only the preview the user
  saw; cancellation writes nothing, and stale plan/device/filesystem state
  requires a new preview.
- Staged FIT and manifest bytes on the destination filesystem before commit,
  reserved verified rollback copies for replacements and removals, and made
  the ownership manifest the final committed update.
- Rechecked device identity, destination, prior manifest bytes, target absence,
  and owned-file size/digest immediately before each applicable change.
- Added rollback safeguards that refuse to overwrite or remove a file that
  appeared or changed during recovery.
- Added synthetic tests for confirmation, exact-preview expiry, post-staging
  collisions and manifest tampering, manifest-last ordering, successful
  application, and interrupted copy, replacement, and rotation recovery.

## Next

1. On a physical Garmin mass-storage device, owner-run a small synthetic-plan
   preview/install/consume/rotate check and record any compatibility defect in
   a new approved issue before changing the unverified compatibility claim.
2. If the hardware check succeeds, record the tested model and observed result
   without including real runner plan data or device identifiers.
3. Approve and add the next feature to the project board before starting
   another feature branch; the current five-item backlog is otherwise complete.

## Blockers

- Physical-device compatibility requires an owner-provided Garmin device and
  remains outside automated verification.
