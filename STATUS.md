# Status

- **Updated:** 2026-08-24

## Live

- The public source repository is available at
  `https://github.com/efuller82/marathon-planner`.
- The "Marathon Planner" GitHub project contains the approved feature backlog
  in priority order.
- A local Tkinter editor runs with `python run.py`; users can add and remove
  ordered workout rows, validate authored weeks, import version 1 local JSON
  plans, and switch among weeks.
- The redesigned desktop window (issue #14) sizes itself to the screen, keeps
  columns aligned and every action visible, scrolls the workout list, wraps
  long status messages, and has File/Help menus, week navigation, an open-plan
  summary, and a plain-language help dialog.
- The model preserves each user-authored distance or time goal with distinct
  ROAD and TRAIL choices; it does not prescribe or silently alter training.
- Each dated workout deterministically encodes to collision-safe ROAD and TRAIL
  FIT protocol 2.0/profile 21.00 files, and the desktop app exports the
  complete open plan as one deterministic local ZIP with a hashed manifest.
- The mass-storage USB installer previews and applies an explicit contiguous
  week block and terrain with device-bound SHA-256 ownership, rollback, and
  preservation of unrelated files.
- Issue #12's branch is rebased onto the merged issue #14 editor. The
  Forerunner 265 MTP installation now appears as a second path inside the
  "Install on your Garmin watch" section, reusing the shared week block and
  terrain controls, restyled to the new layout, with preview and recovery
  buttons disabled until a dated plan is imported.
- MTP preview is read-only and fail-closed; application and recovery use
  exact-preview reconstruction, a durable forward journal, exact writes,
  committed identities, full readback, and ownership before cleanup. The
  Windows watch connector validates types and bounds, releases resources, and
  deletes only one proven object without recursion. It loads only when an MTP
  operation begins, and never requests Garmin credentials.
- **The repeatable physical write failure is diagnosed and corrected**
  (commit 74b18d3). The failed installs never reached the watch: the
  connector's file-kind identifiers are stored unbraced, but the Windows
  text-to-binary GUID conversion accepts only the braced form, so creating a
  workout file failed locally right after the journal reached its prepared
  stage. The connector now braces the text at the conversion boundary and
  fails closed on malformed text. The failure and the fix were both
  reproduced locally with no device attached, and every checked-in Windows
  interface declaration was verified against the real Windows type libraries
  (all match).
- The full gate compiles the project and runs 186 unit tests using only
  synthetic data (187 with the uncommitted working-folder experiment
  applied). One Windows symbolic-link test and, off Windows, the two new
  local-only GUID-conversion tests skip.
- Physical Garmin-device compatibility remains explicitly unverified. PR #13
  is green at head 74b18d3 and remains open and unmerged until a complete
  owner-run synthetic watch check passes.
- Approved issue #11 (owner-run physical mass-storage validation) remains In
  Progress and blocked on a mass-storage Garmin device.

## This session

- Rebased `feature/12-forerunner-265-mtp-install` (PR #13) onto the merged
  issue #14 editor, re-integrating the MTP install as a second path inside
  the redesigned "Install on your Garmin watch" section; verified the layout
  with DPI-aware screenshots in both the no-plan and imported states.
- Diagnosed the repeatable physical write failure read-only: both preserved
  failure journals stopped at the prepared stage with the copy never started,
  the declared-interface audit ruled out wrong-slot dispatch, and a local
  reproduction with no device attached isolated the unbraced-GUID text
  conversion in the connector's property-setting path.
- Applied the bounded correction with two Windows-only regression tests,
  reran the full gate (green), pushed, and recorded the sanitized diagnosis
  on issue #12. No device mutation occurred; the archived failure journals
  and local state were only read.
- The uncommitted working-folder experiment (device "supported format"
  pre-check plus a changed declared file kind) is preserved intact but is now
  known to be unnecessary — the failing request never reached the watch — and
  the pre-check could wrongly block a working watch. Recommendation on issue
  #12: discard it. An uncommitted AGENTS.md owner-communication update is
  also preserved in the working folder.

## Next

1. Owner action: rerun the full synthetic acceptance check on the physical
   Forerunner 265 (preview, verified write, watch appearance/consumption,
   missing-owned handling) from PR #13 head 74b18d3 or later, after deciding
   whether to discard the uncommitted working-folder experiment (recommended:
   discard, so the check runs exactly the committed connector).
2. Record the sanitized four-field result on issue #12. On PASS, mark the
   Forerunner 265 profile verified in docs and merge PR #13 on green checks;
   on FAIL, resume read-only diagnosis from the new journal without another
   device mutation.
3. Close issue #12 and move its card to Done only after the green PR merges.
4. Decide separately whether to commit the AGENTS.md owner-communication
   update (documentation-only change).

## Blockers

- The full acceptance check requires the owner and the physical Forerunner
  265; it must not run unattended.
- Issue #11 still requires a mass-storage Garmin device; the available
  Forerunner 265 exposes only MTP.
