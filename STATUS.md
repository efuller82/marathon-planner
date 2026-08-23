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
- The full gate compiles the project and runs 111 passing unit tests using only
  synthetic workout, filesystem, and MTP data. One symbolic-link safety test
  skips when the Windows account cannot create symbolic links.
- Physical Garmin-device compatibility remains explicitly unverified.
- Approved issue #11 tracks the owner-run physical mass-storage validation and
  is In Progress on the project board.
- Approved issue #12 tracks safe Windows MTP workout installation for the
  Forerunner 265 and is In Progress on the project board.

## This session

- Created `feature/12-forerunner-265-mtp-install` from fetched `master` and
  moved issue #12 to In Progress before changing implementation files.
- Added an immutable, bounded MTP transport/session protocol with separate
  discovery, enumeration, property, create, write, commit, identity, readback,
  and nonrecursive deletion boundaries.
- Added an in-memory synthetic MTP object graph with connection/session
  generations, deterministic transfer results, a call log, and before/after
  fault injection at every transport boundary.
- Added versioned ownership and forward-recovery journal records that validate
  exact schemas, bounds, unique case-folded filenames, persistent ownership,
  copy-before-cleanup ordering, and completed-copy identities.
- Added a local state store that derives locally salted device bindings without
  persisting raw binding inputs and atomically replaces ownership and journal
  JSON after flushing staged bytes.
- Kept raw transport and ownership identifiers out of record representations,
  left `usb_install.py` unchanged, and added 20 synthetic tests for the new
  boundaries and store; the full 112-test gate is green with one permission-
  dependent symlink test skipped.

## Next

1. Implement pure supported-device, destination, collision, consumed-object,
   and ownership planning through the bounded protocol; preview must make no
   mutating transport or local-state calls.
2. Implement exact-preview comparison plus durable copy/readback/ownership-
   before-cleanup application and forward recovery through the current journal.
3. Add the lazily imported WPD adapter behind a fake low-level facade, then add
   the separate Windows MTP UI path without changing mass-storage behavior.
4. Run the full gate, review and hash-pin the Windows-only COM dependency, open
   one PR, and keep the Forerunner 265 profile provisional.
5. Owner-run issue #12's minimal synthetic physical-device acceptance check;
   enable and document only the exact profile that passes before merge.
6. When a mass-storage Garmin is available, resume issue #11's separate
   physical validation.

## Blockers

- The available owner-provided Forerunner 265 uses MTP and does not expose the
  mounted filesystem required by the shipped mass-storage installer. A
  mass-storage Garmin is required to complete issue #11.
- Issue #12's physical compatibility cannot be confirmed until its planned MTP
  implementation is complete and the owner-run synthetic device check passes.
