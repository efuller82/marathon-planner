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
- The full gate compiles the project and runs 176 unit tests using only
  synthetic workout, filesystem, MTP, UI, and Windows-connector data. One
  symbolic-link safety test skips when the Windows account cannot create links.
- Physical Garmin-device compatibility remains explicitly unverified.
- Approved issue #11 tracks the owner-run physical mass-storage validation and
  is In Progress on the project board.
- Approved issue #12 tracks safe Windows MTP workout installation for the
  Forerunner 265 and remains In Progress. Its single pull request is open but
  must not merge until the owner-run synthetic watch check passes.

## This session

- Reviewed the complete issue #12 change against `origin/master`, including the
  two earlier branch commits and all remaining Windows connector, desktop,
  dependency, documentation, and synthetic-test work.
- Confirmed the changes preserve the mounted-drive installer, keep device and
  runner identifiers out of public output, reject stale or ambiguous device
  state, verify copied bytes before ownership, and revalidate complete ownership
  before any one-object cleanup.
- Corrected the stale `SECURITY.md` known-gap entry: MTP ownership, rotation, and
  recovery are implemented with synthetic coverage, while physical Forerunner
  265 compatibility remains explicitly unverified.
- Rechecked the reviewed `comtypes` 1.4.16 hash lock and lazy-loading boundary;
  normal application imports and the synthetic gate remain dependency-free.
- Ran the complete compile/unit gate: 176 tests ran, 175 passed, and the existing
  Windows symbolic-link permission test skipped.
- The first pull-request run exposed Linux-only test setup assumptions: the CI
  runner has no Tk package and is not Windows. Corrected the synthetic UI and
  lazy-connector tests to supply those platform boundaries explicitly, then
  reran the complete local gate with the same passing result.
- Committed all remaining issue #12 branch work and opened its one pull request
  for CI and the owner-run physical acceptance check. The profile remains
  provisional and the pull request remains unmerged.

## Next

1. Owner-run issue #12's minimal synthetic physical-device acceptance check from
   the open pull request; do not use a real runner plan or record device IDs.
2. Record only the Windows version family, model, topology shape without IDs,
   and pass/fail on issue #12. Enable and document only the exact profile that
   passes; keep it provisional if any check fails.
3. Merge only after green pull-request checks and the owner check, then close
   issue #12 and move its project card to Done.
4. When a mass-storage Garmin is available, resume issue #11's separate
   physical validation.

## Blockers

- The available owner-provided Forerunner 265 uses MTP and does not expose the
  mounted filesystem required by the shipped mass-storage installer. A
  mass-storage Garmin is required to complete issue #11.
- Issue #12's physical compatibility cannot be confirmed until the owner-run
  synthetic device check passes.
