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
- The full gate compiles the project and runs 239 unit tests using only
  synthetic data; one Windows symbolic-link permission test skips.

## This session

- **Cleared the blocker and shipped issue #17.** Archived the reviewed
  journal from the interrupted 2026-08-25 install by renaming it in place to
  `journal.reviewed-copies-verified-20260825.json`, after re-confirming it
  recorded both copies as completed and verified. New installs are unblocked.
- **The owner ran the Forerunner 265 check and it passed.** Preview listed
  exactly two planned object changes (2 COPY, 0 REMOVE OWNED); the install
  applied; both dated workouts appear on the watch. PR #20 merged on green
  checks, issue #17 closed, card moved to Done.
- **Answered the owner's question about leftover workouts.** Older workouts
  remaining on the watch is expected, not a defect: this install removed
  nothing, the app deletes only objects it can positively prove it installed,
  and the watch absorbs and renames copied files on disconnect — after which
  the app can no longer identify them. Those entries leave the local
  ownership record as CONSUMED with no device change. Recorded on issue #17
  and cross-referenced to issue #18, which already names this constraint.
- **Independent confirmation the dated names shipped:** the two workouts
  encoded 6 bytes larger than the 2026-08-25 versions — exactly the length of
  the `"Apr 2 "` prefix. Evidence added to issue #18 to seed its read-only
  investigation step.
- Committed the previously uncommitted AGENTS.md owner-communication section
  as documentation only (it already governed behavior; leaving it in the
  working tree risked losing it). Revert this PR's AGENTS.md hunk if it was
  meant to be discarded.
- Committed the two synthetic acceptance fixtures
  (`acceptance-synthetic.json`, `acceptance-paced-synthetic.json`) that were
  sitting untracked. Rationale: the 2026-08-25 diagnosis stalled precisely
  because the plan file used for an install could not be reproduced later.
  Version-controlling the acceptance fixtures removes that failure mode, and
  issue #18 needs an owner-run check against the same data. Both contain only
  synthetic 2030 dates, names, and distances.

## Next

1. Start issue #18 (clean up the app's installed workouts from the watch,
   keeping chosen ones). Its first acceptance criterion gates the rest: an
   owner-run, read-only investigation of how the watch stores imported
   workouts — whether the embedded dated name survives the watch's rename is
   the key unknown, because that string is the only identity anchor issue #17
   guarantees cannot be truncated away. Open a branch from current `master`,
   move the card to In Progress, and plan before writing deletion code.
2. Issue #23 (let recovery finish a fully-verified install from the journal
   alone) is on the board for the owner to prioritize.
3. Owner decision: align the export package README wording with the BOTH
   install default (small follow-up, no issue filed).
4. Open puzzle, answer only if the owner remembers: were any workout values
   edited in the app before the 2026-08-25 installs? That would explain why
   the journaled bytes from that day match no reproducible encoding of the
   fixture. Blocking nothing; the journal is archived and the question is now
   only historical.

## Blockers

- Issue #11 requires a mass-storage Garmin device; the available Forerunner
  265 exposes only MTP.
