# Status

- **Updated:** 2026-08-24

## Live

- The public source repository is available at
  `https://github.com/efuller82/marathon-planner`.
- The "Marathon Planner" GitHub project contains the approved feature backlog
  in priority order.
- A local Tkinter editor runs with `python run.py`; users can add and remove
  ordered workout rows, validate authored weeks, and switch among imported
  weeks.
- The redesigned desktop window (issue #14) sizes itself to the screen it opens
  on and keeps every action visible: column headings share one layout with the
  workout rows so they always line up, the workout list scrolls instead of
  pushing buttons off screen, and a full-width status bar wraps long safety
  messages.
- The window now has File and Help menus (Ctrl+O import, Ctrl+E export), a
  plain-language "How to use Marathon Planner" help dialog, Previous/Next week
  buttons, an open-plan summary line, and export/install buttons that stay
  disabled with an explanation until a dated plan is imported.
- The core model supports validated distance goals (`mi`, `km`, or `m`) and
  time goals (`sec`, `min`, or `hr`); each workout preserves distinct ROAD and
  TRAIL choices under one user-authored goal.
- Version 1 local JSON plan import validates file type, size, exact schema,
  duplicate fields, dates, bounds, and domain values before replacing the open
  plan.
- Each dated workout deterministically encodes to distinct ROAD and TRAIL FIT
  protocol 2.0/profile 21.00 files; names, identifiers, and bytes are stable
  and collision-safe within a plan.
- The desktop app exports the complete open plan as one deterministic local ZIP
  with a hashed manifest, importable plan JSON, authored-date iCalendar, local
  transfer instructions, and terrain-separated FIT files.
- The USB installer previews an explicit week block and terrain, applies only
  the confirmed exact preview, revalidates identity and SHA-256 ownership
  before each change, rolls back interrupted commits, preserves unrelated
  files, and never requests Garmin credentials.
- The full gate compiles the project and runs 98 passing unit tests using only
  synthetic workout and filesystem data.
- Physical Garmin-device compatibility remains explicitly unverified.
- Issue #12's separate branch (`feature/12-forerunner-265-mtp-install`, PR #13)
  holds the in-progress Windows MTP installation for the Forerunner 265; its
  owner-run physical acceptance check still has a FAIL result, so that PR
  remains open and unmerged. The main repository folder currently has that
  branch checked out with uncommitted diagnosis work — leave it in place.

## This session

- The owner reported the desktop app was hard to use: misaligned columns,
  action buttons and the install section pushed off screen on a 1280x800
  logical display, unreadable status messages, and no visible workflow.
- Created issue #14 and rebuilt the window layout on
  `feature/14-usable-editor` (from `master`, in a separate worktree at
  `../marathon-planner-ui` so the issue #12 checkout stayed untouched).
- Fixed alignment by giving the heading row and every workout row one shared
  column plan; verified with before/after screenshots.
- Fixed off-screen content: the app is now sharp on scaled Windows displays,
  sizes the window to the real screen, scrolls the workout list, and keeps
  the install section and a wrapping status bar always visible.
- Added menus, keyboard shortcuts, week Previous/Next buttons, a plan summary,
  a help dialog, and state-aware captions; safety behavior is unchanged (read-
  only previews, explicit confirmation, no credential requests, no new
  dependencies).
- All 98 tests pass, including new tests for the shared column plan, plan
  summary text, and week navigation guards.

## Next

1. Merge PR for issue #14 once checks are green, then close issue #14 and move
   its card to Done.
2. Rebase PR #13 (issue #12) onto the merged UI: re-add its MTP section as a
   second install path inside the "Install on your Garmin watch" area and
   restyle it to the new layout before continuing the physical-failure
   diagnosis in STATUS history on that branch.
3. Continue issue #12's read-only diagnosis of the repeatable physical write
   failure with synthetic data only, preserving the active recovery state.
4. Issue #11 (physical mass-storage validation) still awaits a mass-storage
   Garmin device.

## Blockers

- Issue #11 needs an owner-provided mass-storage Garmin; the available
  Forerunner 265 is MTP-only.
- Issue #12's owner-run synthetic acceptance check has a repeatable FAIL; PR
  #13 must not merge until a complete check passes.
