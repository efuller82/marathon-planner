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
  navigation, and plain-language help. A "Copy message" button in the status
  bar copies any shown message — errors included — to the clipboard in one
  click (issue #21).
- Road and trail pace targets are merged and watch-verified (issue #16
  closed, PR #19 merged 2026-08-25). Each dated workout encodes to
  collision-safe ROAD and TRAIL FIT files with optional per-terrain pace
  alert bands, and terrain BOTH (the default) installs both versions side by
  side.
- **Verified watch behavior (Forerunner 265, owner-run 2026-08-25): the
  watch lists both installed workouts under both the Run and the Trail Run
  activities — it does not sort trail-marked files under Trail Run only.
  The core road-vs-trail requirement is met through clearly named workouts
  carrying genuinely different pace bands; the runner picks the one matching
  the terrain.**
- The desktop app exports the complete open plan as one deterministic local
  ZIP with a hashed manifest. The mass-storage USB installer and the
  verified Forerunner 265 MTP installer preview and apply an explicit
  contiguous week block with device-bound ownership, rollback, and
  preservation of unrelated files. Physical mass-storage validation (issue
  #11) remains blocked on hardware.
- **Awaiting the owner-run watch check for issue #17:** dated on-watch names
  are on PR #20 (branch `feature/17-dated-watch-names`, card In Progress).
  Every workout name starts with its authored date ("Apr 2 ROAD: Easy
  run"), so a runner can tell which workout belongs to which day. All file
  identities changed with the new bytes, so a re-install replaces older
  installed app files cleanly.
- The full gate compiles the project and runs 239 unit tests on this branch
  using only synthetic data; one Windows symbolic-link permission test
  skips.

## This session

- Issue #16 closed: the owner's re-run watch check passed via the
  anticipated fallback behavior (both workouts under both activities,
  distinct names and paces). Result recorded on the issue, PR #19 merged on
  green checks, card Done.
- Issue #17 implemented on PR #20 (awaiting the owner-run watch check
  posted on the issue): authored date prefixed to every on-watch name in
  fixed English month form, date and terrain always survive title
  shortening, all file identities changed so installers replace older
  installs cleanly, help updated, two new tests.
- **The owner hit "MTP recovery required" — an installation was interrupted
  and is safely journaled.** Before re-running the issue #17 watch check:
  reconnect the watch, select the same week block and terrain (BOTH, week
  1), and choose "Recover interrupted installation"; then continue the
  check. A reminder comment is on issue #17.
- That error had to be retyped by hand, so issue #21 was filed and shipped
  the same day (PR #22 merged): a "Copy message" button in the status bar
  copies the full current message (errors and results alike) to the
  clipboard, with brief "Copied" feedback. Verified with DPI-aware
  screenshots at 150% scaling: the long MTP recovery message and the button
  fit the owner's display, and the clipboard received the complete text.
- Noticed but not changed: the exported package's README still says
  "choose one terrain variant … do not install both", which predates the
  BOTH default. Candidate small follow-up, owner decision.

## Next

1. Owner action: recover the interrupted installation (reconnect the
   Forerunner 265, same week block and terrain BOTH, "Recover interrupted
   installation"), then run the issue #17 watch check in the latest issue
   #17 comment (install with BOTH; confirm both workout names start with
   "Apr 2" and the older undated copies are replaced; record model and
   pass/fail only). After a PASS: merge PR #20 on green checks, close issue
   #17, move its card to Done. On a FAIL: record which step failed and
   diagnose read-only first.
2. Then issue #18 (date-aware cleanup of app-installed workouts; its
   positive identification of app files builds on the dated identities from
   #17).
3. Owner decision: review the still-uncommitted AGENTS.md
   owner-communication section (`git diff AGENTS.md`) and either commit it
   as a documentation-only change or discard it.
4. Owner decision: whether to align the export package README wording with
   the BOTH install default in a small follow-up.

## Blockers

- Issue #17 cannot merge until the owner recovers the interrupted
  installation and runs the issue #17 watch check.
- Issue #11 requires a mass-storage Garmin device; the available Forerunner
  265 exposes only MTP.
