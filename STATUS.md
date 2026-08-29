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
- **An interrupted installation whose workout files all reached the watch
  now finishes on its own** (issue #23 closed, PR #26 merged 2026-08-28).
  The "Recover interrupted installation" button no longer waits for a plan to
  be imported, and in that case needs no plan open — a different plan may even
  be open. An installation that still had files to copy is unchanged: it
  demands the same plan, week block, and terrain, and the same file contents
  byte for byte, and the app says so when pressed.
- The desktop app exports the complete open plan as one deterministic local
  ZIP with a hashed manifest. The USB and Forerunner 265 MTP installers
  preview and apply an explicit week block with device-bound ownership,
  rollback, and preservation of unrelated files. Issue #11 (mass-storage
  validation) remains blocked on hardware.
- Local MTP state is at schema version 2: it remembers workouts the watch has
  absorbed instead of forgetting them, and marks each recovery journal as an
  installation or a cleanup. A version 1 file written by an earlier release
  still loads and is upgraded the next time state is saved.
- The full gate compiles the project and runs 320 unit tests using only
  synthetic data; one Windows symbolic-link permission test skips.

## This session

- **Shipped issue #23 end to end.** The plan was posted on the issue before
  any code was written, as the owner asked. PR #26 merged on green checks and
  the card moved to Done.
- **What changed for the runner.** On 2026-08-25 a fully-completed
  installation could not be recovered, because recovery insisted on
  rebuilding the original workout files from an open plan and matching them
  exactly — and the file format had changed since. That journal had to be
  reviewed and archived by hand, leaving the files it had installed unowned.
  Now, when the record shows every file already reached the watch, recovery
  finishes from that record alone. The remaining work in that case is local
  bookkeeping and any deletions the install had already committed to, and
  the record describes both.
- **What stayed strict.** If any file was still being copied, nothing about
  recovery changed: the same plan, week block, and terrain, and the same file
  contents, are still required before the app touches the watch. Only
  workouts the app can prove it installed are ever deleted, and anything
  ambiguous still stops with a message that says what to do.
- **One deliberate widening, recorded on the issue.** The issue said "a
  journal in the copies-verified phase". The record also carries a coarse
  progress stamp written *after* the last file is marked done, so an install
  interrupted in that gap has every file on the watch but still carries the
  earlier stamp. Refusing it would recreate the exact permanent-refusal
  problem being fixed, so the app keys off "every file is marked done"
  instead.
- **A separate defect found and fixed while tracing this.** The final step of
  a normal installation was throwing away the app's memory of workouts the
  watch had absorbed — silently undoing the "remember what the watch took"
  behavior that shipped with the watch-cleanup work. It is fixed in its own
  commit with its own test, which fails without the fix.
- **A UI blocker found and fixed.** The "Recover interrupted installation"
  button had been disabled until a plan was imported, which would have made
  the whole no-plan-needed path unreachable. It is now live from startup,
  beside the other buttons that need no plan. Confirmed on the owner's
  display at 150% scaling with a screenshot, not tests alone.
- **Eleven new synthetic tests**, covering both journal states, the ownership
  outcome including an absorbed copy, ownership the journal never touched,
  an unrelated file left untouched, the absorbed-memory defect, and the app's
  two recovery routes. The full local gate passes: 320 tests, one skip.

## Next

1. **Owner decision: what to take next.** Nothing is in progress and the
   board has no unblocked feature card left. Everything else below is a
   small follow-up, an optional check, or housekeeping.
2. Owner decision: align the export package README wording with the BOTH
   install default (small follow-up, no issue filed).
3. **Optional owner check, not required by any issue.** The archived journal
   from 2026-08-25 — the one that could not be recovered and had to be
   reviewed by hand — is exactly what issue #23 was built for. Restoring it
   into the local MTP state folder and pressing "Recover interrupted
   installation" with no plan open is the most faithful real-watch test
   available for the new behavior.
4. Worth watching, no action yet: the app keeps a record of every workout the
   watch absorbs, and drops one only when it can see the workout is gone from
   the watch. This session fixed a defect where a normal install threw that
   record away, so the list will now actually grow. If it ever grows in a way
   that surprises the owner, revisit how records are retired.
5. Board housekeeping the owner may want: issue #11 still sits in the In
   Progress column while it is blocked on hardware and nobody is working it.
   Left alone this session rather than moved without asking.

## Blockers

- Issue #11 requires a mass-storage Garmin device; the available Forerunner
  265 exposes only MTP. No owner action can clear this without new hardware.
