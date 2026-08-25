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
- Road and trail pace targets are merged and watch-verified (issue #16
  closed, PR #19 merged 2026-08-25). Each dated workout encodes to
  collision-safe ROAD and TRAIL FIT files with optional per-terrain pace
  alert bands, and terrain BOTH (the default) installs both versions side by
  side.
- **Verified watch behavior (Forerunner 265, owner-run 2026-08-25): the
  watch lists both installed workouts under both the Run and the Trail Run
  activities — it does not sort trail-marked files under Trail Run only.
  The core road-vs-trail requirement is met through clearly named workouts
  ("ROAD: …" / "TRAIL: …") carrying genuinely different pace bands; the
  runner picks the one matching the terrain.**
- The desktop app exports the complete open plan as one deterministic local
  ZIP with a hashed manifest. The mass-storage USB installer and the
  verified Forerunner 265 MTP installer preview and apply an explicit
  contiguous week block with device-bound ownership, rollback, and
  preservation of unrelated files. Physical mass-storage validation (issue
  #11) remains blocked on hardware.
- **Awaiting the owner-run watch check for issue #17:** dated on-watch names
  are on PR #20 (branch `feature/17-dated-watch-names`, card In Progress).
  Every workout name now starts with its authored date ("Apr 2 ROAD: Easy
  run"), so a runner can tell which workout belongs to which day. All file
  identities changed with the new bytes, so a re-install replaces older
  installed app files cleanly.
- The full gate compiles the project and runs 238 unit tests using only
  synthetic data; one Windows symbolic-link permission test skips.

## This session

- The owner re-ran the revised issue #16 watch check: both workouts were
  installed and appeared, with the watch listing both under both Run and
  Trail Run. That is the second of the two behaviors the revised check
  anticipated and passes the requirement (distinct names, distinct paces).
  Recorded the result on issue #16, merged PR #19 on green checks, issue
  closed and its card moved to Done automatically.
- The TRAIL files keep their trail-run activity marker: it is harmless on
  the Forerunner 265 and may help models that do sort by activity.
- Implemented issue #17 (PR #20): the encoder prefixes every on-watch
  workout name with the authored date in fixed English month form ("Apr 2"),
  so the bytes never depend on the computer's language settings. The date
  and terrain lead the name, so shortening a long title can never drop
  them. Every file identity gained a name-format marker so filenames change
  with the bytes and installers replace older installed files instead of
  refusing them. In-app help updated; two new tests plus refreshed golden
  hashes (238 green). No schema change; version 1 and 2 plans import
  unchanged.
- Noticed but did not change: the exported package's README still says
  "choose one terrain variant … do not install both", which predates the
  BOTH default from issue #16. Candidate small follow-up, owner decision.

## Next

1. Owner action: run the issue #17 watch check in the latest issue #17
   comment (import `acceptance-paced-synthetic.json`, terrain BOTH, week 1,
   install on the Forerunner 265; confirm both workout names start with
   "Apr 2" and older app-installed test workouts show as replaced; record
   model and pass/fail only). After a PASS: merge PR #20 on green checks,
   close issue #17, move its card to Done. On a FAIL: record which step
   failed and diagnose read-only first.
2. Then issue #18 (date-aware cleanup of app-installed workouts; its
   positive identification of app files builds on the dated identities from
   #17).
3. Owner decision: review the still-uncommitted AGENTS.md
   owner-communication section (`git diff AGENTS.md`) and either commit it
   as a documentation-only change or discard it.
4. Owner decision: whether to align the export package README wording with
   the BOTH install default in a small follow-up.

## Blockers

- Issue #17 cannot merge until the owner runs its watch check.
- Issue #11 requires a mass-storage Garmin device; the available Forerunner
  265 exposes only MTP.
