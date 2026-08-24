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
- Issue #12's branch has a bounded MTP protocol/fake, atomic local ownership and
  forward-recovery records, and a provisional Garmin Forerunner 265 profile for
  the exact `Internal Storage/GARMIN/NewFiles` topology.
- MTP preview is read-only. It requires one strict supported-device match,
  unambiguous containers and inventory, persistent identities, and full
  readback of every present owned object. It plans only `COPY` and
  `REMOVE OWNED`; changed ownership and unrelated collisions fail closed.
- MTP application and recovery use exact-preview reconstruction, a durable
  forward journal, exact writes, committed identities, full readback, ownership
  before cleanup, and complete revalidation before each nonrecursive delete.
- The Windows watch connector validates exact property and result types, bounds
  device-supplied lists, text, buffers, and files, verifies every transfer and
  readback, releases connection resources, and deletes only one proven object
  without recursion.
- The optional Windows connection code loads only when an MTP operation begins.
  Importing the application and running synthetic tests requires no `comtypes`;
  missing optional support disables only MTP with actionable status text.
- Optional Windows MTP support uses the MIT-licensed `comtypes` 1.4.16 universal
  wheel from a SHA-256-locked, wheel-only requirements file. It has no required
  transitive dependency or recurring service cost.
- The desktop exposes MTP as a separate Windows action using the existing
  explicit week block and ROAD/TRAIL selection. It never falls back to the
  mounted-drive installer or guesses a device path.
- The MTP window displays the exact sanitized dry run and selection, requires a
  second explicit confirmation, rejects changed visible plan bytes, and routes
  an unresolved or interrupted journal to a separately invoked recovery action.
- MTP local ownership and journal files default to local Windows application
  data. Preview does not create them; missing Windows/optional support disables
  only MTP with actionable status text.
- The full gate compiles the project and runs 178 unit tests using only
  synthetic workout, filesystem, MTP, UI, and Windows-connector data. One
  symbolic-link safety test skips when the Windows account cannot create links.
- Physical Garmin-device compatibility remains explicitly unverified. The full
  owner-run issue #12 acceptance check currently has a FAIL result, so the
  Forerunner 265 profile remains provisional.
- Approved issue #11 tracks the owner-run physical mass-storage validation and
  is In Progress on the project board.
- Approved issue #12 tracks safe Windows MTP workout installation for the
  Forerunner 265 and remains In Progress. Its single pull request is open but
  must not merge until a complete owner-run synthetic watch check passes.

## This session

- Windows version family: Windows 10
- Model: Forerunner 265
- Sanitized topology shape: `Internal Storage/GARMIN/NewFiles`
- Full owner-run synthetic acceptance result: FAIL
- The provisional profile remains unverified. PR #13 remains open and unmerged.
- Posted the same four-field sanitized result to issue #12. No identifiers,
  ownership metadata, raw device metadata, or real runner data were recorded.

## Next

1. Owner: complete the application's local manual-review path for the failed
   synthetic copy before any retry; preserve the recovery state until that
   review is complete.
2. After the owner confirms the manual review is complete, decide on issue #12
   whether the physical failure needs a connector correction or a fresh full
   acceptance run.
3. Merge only after preview, verified write, watch appearance/consumption, and
   missing-owned handling all pass and issue #12 has a new sanitized PASS
   record.
4. Close issue #12 and move its project card to Done only after the green PR
   merges. Keep the profile provisional while any physical step has not passed.

## Blockers

- The available owner-provided Forerunner 265 uses MTP and does not expose the
  mounted filesystem required by the shipped mass-storage installer. A
  mass-storage Garmin is required to complete issue #11.
- Issue #12's full owner-run synthetic check has a FAIL result. Owner manual
  review is required before another attempt; compatibility cannot be confirmed
  until a later complete check passes.
