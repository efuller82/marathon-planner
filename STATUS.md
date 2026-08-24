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
- Physical Garmin-device compatibility remains explicitly unverified.
- Approved issue #11 tracks the owner-run physical mass-storage validation and
  is In Progress on the project board.
- Approved issue #12 tracks safe Windows MTP workout installation for the
  Forerunner 265 and remains In Progress. Its single pull request is open but
  must not merge until the owner-run synthetic watch check passes.

## This session

- Diagnosed issue #12's failed physical container check against Microsoft's
  WPD object rules. Microsoft defines a folder by its content type and permits
  `WPD_OBJECT_SIZE` when the folder exposes a resource, so container size
  metadata is not evidence that the object is a file.
- Narrowed the Windows adapter correction to accept only an exactly typed
  unsigned container resource size, retain the exact storage/folder content
  classification, and omit that resource size from the application-facing
  file-content size field. Wrong property types still fail closed.
- Added synthetic coverage for both storage and folder resource sizes and for
  rejection of a wrongly typed container size.
- Ran the complete compile/unit gate: 178 tests ran, 177 passed, and the existing
  Windows symbolic-link permission test skipped.
- Repeated a metadata-only physical traversal on one exact Garmin Forerunner
  265. It verified `Internal Storage/GARMIN/NewFiles` without opening device
  content streams, writing, deleting, or recording identifiers or raw sizes.
- Removed the one-shot local metadata helper. No local MTP ownership or recovery
  state was created. The open PR and profile remain provisional until the full
  synthetic workout acceptance check passes.

## Next

1. Repeat the full owner-run synthetic physical check from PR #13: preview,
   verified write, watch appearance/consumption, and missing-owned preview.
2. Record only Windows version family, model, sanitized topology shape, and
   pass/fail on issue #12; never record identifiers, ownership state, raw device
   metadata, or real runner data.
3. Merge only after every preview, verified write, watch
   appearance/consumption, and missing-owned check passes and a new PASS record
   is on issue #12.
4. Close issue #12 and move its project card to Done only after the green PR
   merges. Keep the profile provisional if any physical step fails.

## Blockers

- The available owner-provided Forerunner 265 uses MTP and does not expose the
  mounted filesystem required by the shipped mass-storage installer. A
  mass-storage Garmin is required to complete issue #11.
- Issue #12's metadata-only physical traversal now passes, but compatibility
  cannot be confirmed until the complete owner-run synthetic workout check
  passes.
