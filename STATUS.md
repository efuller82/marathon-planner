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
- **Every workout's on-watch name leads with its authored date** —
  "Apr 2 ROAD: …" and "Apr 2 TRAIL: …" (issue #17 closed, PR #20 merged
  2026-08-28 after the owner-run watch check passed).
- **Verified watch behavior (Forerunner 265, owner-run 2026-08-25): the
  watch lists both installed workouts under both the Run and the Trail Run
  activities — it does not sort trail-marked files under Trail Run only.
  The core road-vs-trail requirement is met through clearly named workouts
  carrying genuinely different pace bands, now with the date leading each
  name.**
- **The runner manages the watch's workouts from the app** (issue #18
  closed, PR #25 merged 2026-08-28 after the owner-run removal check passed).
  "Manage watch workouts" lists every workout the watch is holding. Workouts
  the app installed, dated before the block being kept, open already ticked
  for removal; everything else opens unticked and says the app did not
  install it. Any line can be ticked, so nothing on the watch is beyond the
  runner's reach. "See what's on the watch" shows the same workouts
  read-only with a shareable summary that carries no workout names. Removing
  revalidates each workout by content immediately before a single delete,
  confirms afterwards that it went, and journals every step so "Finish
  interrupted cleanup" can complete an interrupted run. Recorded runs are
  never listed, never removed, and never read.
- **Verified watch behavior (Forerunner 265, owner-run 2026-08-28): a
  workout the watch has absorbed stays visible as a file in
  `GARMIN/Workouts`, keeps the authored date at the front of its name, and
  keeps its exact bytes. That byte-for-byte match against a local record is
  the app's only proof that it installed a workout; a name is never enough,
  because the watch renames what it takes.**
- The desktop app exports the complete open plan as one deterministic local
  ZIP with a hashed manifest. The USB and Forerunner 265 MTP installers
  preview and apply an explicit week block with device-bound ownership,
  rollback, and preservation of unrelated files. Issue #11 (mass-storage
  validation) remains blocked on hardware.
- Local MTP state is at schema version 2: it remembers workouts the watch has
  absorbed instead of forgetting them, and marks each recovery journal as an
  installation or a cleanup. A version 1 file written by an earlier release
  still loads and is upgraded the next time state is saved.
- The full gate compiles the project and runs 309 unit tests using only
  synthetic data; one Windows symbolic-link permission test skips.

## This session

- **Shipped issue #18 end to end.** The owner widened it first: the app must
  show what is actually on the watch and let the runner remove any of it, not
  only what the app can prove it installed. The earlier acceptance criteria
  said the opposite, so the issue was rewritten before any code was written.
- **The owner-run investigation settled the design.** Absorbed workouts stay
  readable in `GARMIN/Workouts`; across roughly 85 folders and 570 files,
  workouts live only there and in the incoming folder. Two of the four
  workouts found still carried the authored date, and the other two never had
  one — they predate issue #17. The four sizes formed two pairs six bytes
  apart, exactly the length of the `"Apr 2 "` prefix, so the watch had been
  carrying the same two workouts twice, once from each install.
- **The owner-run removal check passed**, closing the last acceptance
  criterion. PR #25 merged on green checks and the card moved to Done.
- **What was learned and is worth keeping:** the watch preserves an imported
  workout's bytes exactly, so a content digest is a reliable identity anchor
  after the rename. The on-watch name gives only a month and day, never a
  year, so the removal defaults take the year from the app's own record and
  never infer one for a workout the app cannot vouch for.
- **One deliberate deviation, recorded on the issue.** Replacing a block is
  two confirmations rather than one: the incoming workouts must be on the
  watch before the app can list them beside what was already there and prove
  which is which. After an installation the app offers the removal list with
  the installed block's start date already applied.
- **The read-only survey now opens far less of the device.** It reads file
  contents only in the two folders that hold workouts, instead of opening
  every small file it met. The owner's watch has over five hundred unrelated
  files under GARMIN; none are opened any more.

## Next

1. Owner decision: prioritize issue #23 (let recovery finish a fully-verified
   install from the journal alone). It is the only feature left on the board
   that is not blocked on hardware. Nothing is in progress, so the next
   session should take it unless the owner names something else.
2. Owner decision: align the export package README wording with the BOTH
   install default (small follow-up, no issue filed).
3. Worth watching, no action yet: the app now keeps a record of every workout
   the watch absorbs, and drops one only when it can see the workout is gone
   from the watch. If that list ever grows in a way that surprises the owner,
   revisit how records are retired.

## Blockers

- Issue #11 requires a mass-storage Garmin device; the available Forerunner
  265 exposes only MTP. No owner action can clear this without new hardware.
