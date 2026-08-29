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
- The full gate compiles the project and runs 309 unit tests using only
  synthetic data; one Windows symbolic-link permission test skips.

## This session

- **The owner widened issue #18 and it is now built.** The app must let the
  runner see what is actually on the watch and remove any of it — not only
  the workouts the app can prove it installed. The issue body, acceptance
  criteria and plan were rewritten to match, and everything below is on
  branch `feature/18-watch-workout-cleanup` (draft PR #25, card In Progress).
- **The owner ran the watch check and it answered the question the whole
  feature rested on.** Workouts the Forerunner 265 has absorbed are still
  visible as files, in `GARMIN/Workouts`. Their names still start with the
  authored date, and their contents are unchanged: the two workouts the app
  installed on 2026-08-28 measure 224 and 233 bytes locally and measure
  exactly the same on the watch. The watch was also carrying the same two
  workouts twice — once from the 2026-08-25 install under undated names, once
  from 2026-08-28 under dated ones. That is the problem this issue exists to
  fix, caught in the field.
- **The proof of ownership is now defined and implemented.** A workout counts
  as installed by this app only when a file on the watch matches a local
  record by exact byte count and content digest. A name is never enough,
  because the watch renames what it takes.
- **Local records stop forgetting.** Until now the app dropped its record of
  a workout the moment the watch absorbed it. It now remembers it, so the
  workout stays recognizable later. Existing local state written by an
  earlier release still loads and is upgraded the next time it is saved.
- **"Manage watch workouts" is built.** It lists every workout on the watch.
  Ones this app installed, dated before the block being kept, open already
  ticked for removal; everything else opens unticked and says plainly that
  the app did not install it. Any line can be ticked, so nothing is beyond
  the runner's reach. Recorded runs are never listed and never removed.
- **Removing is as careful as installing.** Each workout is re-read and its
  contents checked immediately before it is deleted, the folder is re-listed
  afterwards to confirm it went, and every step is written down so an
  interrupted cleanup can be finished with "Finish interrupted cleanup".
- **After an installation the app offers the same list**, already set to keep
  the block just installed and everything after it. It is a second
  confirmation rather than one step, because the new workouts have to be on
  the watch before the app can show them beside what was already there.
- **The read-only survey now opens far less.** The owner's watch holds over
  five hundred unrelated files under GARMIN. None of them are opened any
  more; the app reads file contents only in the two folders where workouts
  actually live.
- **Verified in the real app, not only in tests.** The cleanup window was
  driven against a synthetic watch holding four workouts: the two dated
  before the boundary opened ticked, the one dated after opened unticked, and
  the one the app had no record of opened unticked and labeled "not installed
  by this app".

## Next

1. **Owner action, and it is the last acceptance criterion:** connect the
   Forerunner 265 and run `python run.py` from branch
   `feature/18-watch-workout-cleanup`. Press "Manage watch workouts…", check
   that the list matches what the watch shows, tick the two older undated
   workouts from the 2026-08-25 install, confirm, and check on the watch that
   exactly those two are gone and the newer dated pair remain. Report the
   model and pass or fail. Nothing is removed until you confirm, and the
   window says so.
2. On a pass, mark the last acceptance criterion done, take PR #25 out of
   draft, merge on green checks, close issue #18 and move the card to Done.
3. Issue #23 (let recovery finish a fully-verified install from the journal
   alone) is on the board for the owner to prioritize.
4. Owner decision: align the export package README wording with the BOTH
   install default (small follow-up, no issue filed).

## Blockers

- Issue #11 requires a mass-storage Garmin device; the available Forerunner
  265 exposes only MTP.
- Issue #18 cannot close until the owner runs the removal check in "Next"
  item 1.
