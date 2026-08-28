# Status

- **Updated:** 2026-08-28

## Live

- The public source repository is available at
  `https://github.com/efuller82/marathon-planner`.
- The "Marathon Planner" GitHub project contains the approved feature backlog
  in priority order.
- A local Tkinter editor runs with `python run.py`; users can add and remove
  ordered workout rows, validate authored weeks, import version 1 and 2 local
  JSON plans, switch among weeks, and use the issue #14 window with menus,
  navigation, and plain-language help. A "Copy message" button in the status
  bar copies any shown message — errors included — to the clipboard in one
  click (issue #21, merged).
- Road and trail pace targets are merged and watch-verified (issue #16
  closed, PR #19 merged 2026-08-25). Terrain BOTH (the default) installs the
  road and trail version of every workout side by side.
- **Every workout's on-watch name now leads with its authored date** —
  "Apr 2 ROAD: …" and "Apr 2 TRAIL: …" (issue #17 closed, PR #20 merged
  2026-08-28 after the owner-run watch check passed).
- **Verified watch behavior (Forerunner 265, owner-run 2026-08-25): the
  watch lists both installed workouts under both the Run and the Trail Run
  activities — it does not sort trail-marked files under Trail Run only.
  The core road-vs-trail requirement is met through clearly named workouts
  carrying genuinely different pace bands, now with the date leading each
  name.**
- The desktop app exports the complete open plan as one deterministic local
  ZIP with a hashed manifest. The USB and Forerunner 265 MTP installers
  preview and apply an explicit week block with device-bound ownership,
  rollback, and preservation of unrelated files. Issue #11 (mass-storage
  validation) remains blocked on hardware.
- The full gate compiles the project and runs 272 unit tests using only
  synthetic data; one Windows symbolic-link permission test skips.

## This session

- **The owner widened issue #18.** The app must let the runner see what is
  actually on the watch and remove any of it — not only the workouts the app
  can prove it installed. The owner confirmed: everything on the watch is
  listed, and anything listed can be removed once ticked. Provenance now only
  sets the starting checkbox and the warning, never the permission. Workouts
  the app installed follow the date rule; everything else starts at KEEP with
  a plain warning that the app did not install it. Recorded runs stay out of
  scope in both directions — never listed, never deleted, contents never
  read. The issue body and acceptance criteria were rewritten to match, and
  the plan is recorded as a comment on issue #18.
- **Started issue #18 on branch `feature/18-watch-workout-cleanup`** (from
  current `master`, card moved to In Progress). The work is staged: the
  read-only half first, then removal, so the owner-run check happens before
  any deletion code exists.
- **Built and committed the read-only half.** The app has a new "See what's
  on the watch…" button that needs no plan open. It reads the watch and shows
  every workout it finds, with the name the watch displays, whether the file
  is marked road or trail, and where it sits. The window also shows a second
  summary that carries no workout names at all, so findings can be pasted
  into a public issue without disclosing what any workout is called.
- **Safety of the new reading path, in concrete terms.** It never writes,
  renames, or deletes. It does not enter the folders that hold recorded runs
  and other health records. It opens a file only when the name ends in `.fit`
  and the file is small enough to be a workout, then checks the file's own
  contents; anything that turns out not to be a workout is thrown away rather
  than kept. A damaged file is reported as unreadable and left alone.
- **Verified in the real app, not only in tests.** The app was launched
  against a synthetic watch holding four workouts the watch had "renamed",
  one workout still waiting in the incoming folder, one non-workout file, and
  a recorded-run folder. All four workouts were found and correctly named,
  the non-workout file was ignored, and the recorded-run folder was reported
  as not entered.
- **Design point found while building it:** the on-watch name carries the
  month and day but no year ("Apr 2"). Removal's "older than the incoming
  block" rule therefore needs a year from somewhere else. Recorded on issue
  #18 for the removal design.

## Next

1. **Owner action, and it gates everything else:** connect the Forerunner
   265, run `python run.py` from branch `feature/18-watch-workout-cleanup`,
   press "See what's on the watch…", then press "Copy shareable findings" and
   paste the result onto issue #18. That answers the question the whole
   feature rests on — whether workouts the watch has absorbed are still
   visible, and whether their names still start with the authored date.
2. After that evidence lands, build removal on the same branch: remember
   consumed workouts instead of forgetting them, add the keep/remove list
   with the agreed defaults, and reuse the existing delete-and-verify safety
   pattern. Then the owner-run cleanup check, then one pull request.
3. Issue #23 (let recovery finish a fully-verified install from the journal
   alone) is on the board for the owner to prioritize.
4. Owner decision: align the export package README wording with the BOTH
   install default (small follow-up, no issue filed).

## Blockers

- Issue #11 requires a mass-storage Garmin device; the available Forerunner
  265 exposes only MTP.
- Issue #18 cannot proceed past the read-only half until the owner runs the
  watch check in "Next" item 1.
