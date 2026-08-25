# Status

- **Updated:** 2026-08-25

## Live

- The public source repository is available at
  `https://github.com/efuller82/marathon-planner`.
- The "Marathon Planner" GitHub project contains the approved feature backlog
  in priority order.
- A local Tkinter editor runs with `python run.py`; users can add and remove
  ordered workout rows, validate authored weeks, import version 1 and 2 local
  JSON plans, switch among weeks, and use the issue #14 window with menus,
  navigation, and plain-language help.
- Each dated workout deterministically encodes to collision-safe ROAD and
  TRAIL FIT files, and the desktop app exports the complete open plan as one
  deterministic local ZIP with a hashed manifest.
- The mass-storage USB installer previews and applies an explicit contiguous
  week block and terrain with device-bound ownership, rollback, and
  preservation of unrelated files. Physical mass-storage validation (issue
  #11) remains blocked on hardware.
- The Forerunner 265 MTP installation is merged and physically verified
  (issue #12 closed, PR #13 merged, owner-run acceptance passed 2026-08-24).
- **New, awaiting the owner-run watch check:** issue #16 pace targets are
  fully implemented on PR #19 (branch `feature/16-pace-targets`, CI green,
  card In Progress). A workout can carry an optional road pace
  (minutes:seconds per mile); the plan carries one user-authored
  road-to-trail adjustment and one alert buffer, each overridable per
  workout. ROAD files encode the road pace range and TRAIL files the trail
  range, so the watch alerts when the runner leaves the band. JSON schema
  version 2 adds the fields; version 1 plans import unchanged; paceless
  workouts keep byte-identical FIT files, filenames, and ownership digests
  (locked by the existing golden-hash test).
- The full gate compiles the project and runs 234 unit tests using only
  synthetic data; one Windows symbolic-link permission test skips.

## This session

- Posted the issue #16 implementation plan, built the whole feature on
  `feature/16-pace-targets` from the updated `origin/master`, and opened PR
  #19 with green checks.
- Design choices worth remembering: pace values are whole seconds everywhere
  in the model and schema (the editor translates m:ss text); exported
  plan.json stays version 1 when the plan has no pace rules so existing
  exports remain byte-identical, and becomes version 2 exactly when pace
  settings exist; the FIT identity digest gains pace fields only for paced
  workouts so already-installed paceless workouts keep their filenames and
  ownership records.
- Verified the wider editor layout (three new pace columns and the plan pace
  rules bar) with DPI-aware screenshots at the owner's 150 % scaling: empty,
  imported, and override-carrying weeks all render fully on screen.
- Coordinated with issue #17 by comment: the on-watch name is untouched and
  pace never enters it, so #17 can prepend the authored date cleanly.
- Wrote the owner-run watch check steps on issue #16 and created the local
  untracked fixture `acceptance-paced-synthetic.json` (synthetic 11:00/mi
  road pace, +90 trail, ±30 buffer; expected on-watch bands ROAD about
  10:30–11:30 and TRAIL about 12:00–13:00 per mile).
- Still uncommitted in this folder: the AGENTS.md owner-communication update
  (owner decision pending) and the untracked local synthetic fixtures
  `acceptance-synthetic.json` and `acceptance-paced-synthetic.json`.

## Next

1. Owner action: run the issue #16 watch check using the steps in the issue
   comment (import `acceptance-paced-synthetic.json`, install ROAD week 1 on
   the Forerunner 265, confirm the pace range and the off-pace alert, record
   model and pass/fail only). Exact next action after a PASS: merge PR #19 on
   green checks, close issue #16, move its card to Done. On a FAIL: record
   which step failed and diagnose read-only first.
2. Then issue #17 (authored date in each workout's on-watch name; small,
   encoding-only; the composition contract is already commented on the
   issue) and issue #18 (date-aware cleanup of app-installed workouts from
   the watch; depends on #17 and starts with an owner-run read-only
   investigation).
3. Owner decision: review the uncommitted AGENTS.md owner-communication
   update (`git diff AGENTS.md`) and either commit it as a
   documentation-only change or discard it.
4. Optional owner cleanup on the watch: delete the imported synthetic test
   workouts from the watch's Workouts list (issue #18 will automate this).

## Blockers

- Issue #16 cannot merge until the owner runs the watch check above.
- Issue #11 requires a mass-storage Garmin device; the available Forerunner
  265 exposes only MTP.
