# Status

- **Updated:** 2026-08-23

## Live

- The public source repository is available at
  `https://github.com/efuller82/marathon-planner`.
- The "Marathon Planner" GitHub project contains the approved feature backlog
  in priority order.
- A local Tkinter editor runs with `python run.py`; users can edit and validate
  authored weeks, import version 1 local JSON plans, and switch among weeks.
- The model preserves each user-authored distance or time goal with distinct
  ROAD and TRAIL choices; it does not prescribe or silently alter training.
- Each dated workout deterministically encodes to collision-safe ROAD and TRAIL
  FIT protocol 2.0/profile 21.00 files.
- The desktop app exports the complete open plan as one deterministic local ZIP
  with a hashed manifest, importable plan JSON, authored-date iCalendar, local
  transfer instructions, and terrain-separated FIT files.
- The mass-storage USB installer previews and applies an explicit contiguous
  week block and terrain. It reconstructs the exact preview, revalidates
  device-bound SHA-256 ownership, rolls interrupted commits back, and preserves
  unrelated files.
- The issue #12 branch has a bounded MTP protocol/fake, atomic local ownership
  and forward-recovery records, and the provisional Garmin Forerunner 265
  profile for exact `Internal Storage/GARMIN/NewFiles` topology.
- MTP preview is read-only. It requires one strict supported-device match,
  unambiguous containers and inventory, persistent identities, and full
  readback of every present owned object. It plans only `COPY` and
  `REMOVE OWNED`; changed ownership and unrelated collisions fail closed.
- Initial MTP preview holds a new local binding salt only in memory. Confirmed
  application persists that exact salt, reconstructs the exact live-session
  preview, and durably writes a `PREPARED` journal before its first device
  mutation.
- MTP application copies deterministic bytes, resolves committed identities,
  verifies every copy by full readback, checkpoints forward progress, commits
  verified ownership before cleanup, and deletes only an old object whose
  destination, persistent identity, name, size, and full digest are revalidated.
- MTP forward recovery resumes durably verified copies and partial cleanup on
  the exact salted device binding. Uncheckpointed or ambiguous commits are
  never adopted, deleted, retried, or cleared automatically.
- The full gate compiles the project and runs 135 unit tests using only
  synthetic workout, filesystem, and MTP data. One symbolic-link safety test
  skips when the Windows account cannot create symbolic links.
- Physical Garmin-device compatibility remains explicitly unverified.
- Approved issue #11 tracks the owner-run physical mass-storage validation and
  is In Progress on the project board.
- Approved issue #12 tracks safe Windows MTP workout installation for the
  Forerunner 265 and is In Progress on the project board.

## This session

- Added confirmed MTP application with exact-preview reconstruction against
  the original live session and stale ownership/inventory rejection before a
  journal or device write.
- Added exact preview-salt persistence, create-only `PREPARED` journals,
  same-transaction checkpoints, copy identity resolution, bounded full
  readback, and durable `INDETERMINATE` marking after unresolved mutations.
- Added forward recovery that verifies the profile, salted device binding,
  destination, desired byte contract, live copied objects, and current
  ownership before resuming.
- Added ownership reconstruction that preserves other device catalogs, records
  only exact desired verified objects, drops consumed prior records, and is
  committed before any cleanup starts.
- Added idempotent cleanup that retains old ownership until deletion, finds old
  objects by persistent identity,
  revalidates their complete ownership proof immediately before nonrecursive
  deletion, resolves ambiguous post-delete results, and preserves changed or
  replaced objects with the journal still durable.
- Added core application/recovery tests for persisted ordering, stale preview
  rejection, ambiguous copy commit recovery, ownership-before-cleanup,
  cleanup tampering, safe rotation, exact salt persistence, and unresolved
  journal protection.
- Ran the full gate: 134 tests passed and the permission-dependent symbolic-link
  test skipped.

## Next

1. Add exhaustive issue #12 fault tests for every create/write/commit/identity/
   readback boundary, every local checkpoint, stale preview variant,
   indeterminate commit, partial cleanup, device reconnect, and repeated
   idempotent recovery.
2. Add the lazily imported WPD adapter behind a fake low-level facade, then add
   the separate Windows MTP UI path without changing mass-storage behavior.
3. Run the full gate, review and hash-pin the Windows-only COM dependency, open
   one PR, and keep the Forerunner 265 profile provisional.
4. Owner-run issue #12's minimal synthetic physical-device acceptance check;
   enable and document only the exact profile that passes before merge.
5. When a mass-storage Garmin is available, resume issue #11's separate
   physical validation.

## Blockers

- The available owner-provided Forerunner 265 uses MTP and does not expose the
  mounted filesystem required by the shipped mass-storage installer. A
  mass-storage Garmin is required to complete issue #11.
- Issue #12's physical compatibility cannot be confirmed until its WPD adapter
  and UI path are complete and the owner-run synthetic device check passes.
