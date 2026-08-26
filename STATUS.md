# Status

- **Updated:** 2026-08-25 (late evening)

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
- **Verified watch behavior (Forerunner 265, owner-run 2026-08-25): the
  watch lists both installed workouts under both the Run and the Trail Run
  activities — it does not sort trail-marked files under Trail Run only.
  The core road-vs-trail requirement is met through clearly named workouts
  carrying genuinely different pace bands.**
- The desktop app exports the complete open plan as one deterministic local
  ZIP with a hashed manifest. The USB and Forerunner 265 MTP installers
  preview and apply an explicit week block with device-bound ownership,
  rollback, and preservation of unrelated files. Issue #11 (mass-storage
  validation) remains blocked on hardware.
- **Awaiting the owner-run watch check for issue #17:** dated on-watch names
  are on PR #20 (branch `feature/17-dated-watch-names`, CI green, card In
  Progress). The check is blocked on one owner action first — see Next.
- The full gate compiles the project and runs 239 unit tests on this branch
  using only synthetic data; one Windows symbolic-link permission test
  skips.

## This session

- **Diagnosed the failed MTP recovery (read-only).** The journal from the
  interrupted 2026-08-25 install is healthy: both copies (one road, one
  trail file) are recorded as completed AND verified on the watch — only
  the app's final local bookkeeping never ran (watch disconnected right
  after the check). Recovery correctly refused because it re-encodes the
  open plan and demands byte-for-byte equality with the journal, and the
  journaled bytes are not reproducible today: not from the current fixture
  through any code version or app path, and not from any pace/buffer
  combination in the model's legal range (exhaustively searched). The
  installed workout's text or goal content differed from today's fixture
  file; the same content was installed consistently twice that day (the
  journaled road file is byte-identical to the one in the ownership
  record), and no alternate plan file exists on the machine. Full findings
  are on issue #17.
- Resolution chosen: the documented "safe manual review" convention —
  archive the journal by renaming it to
  `journal.reviewed-copies-verified-20260825.json` in
  `%LOCALAPPDATA%\MarathonPlanner\mtp`. **The session was not permitted to
  touch the state directory, so this rename is now the single blocking
  owner action.**
- Known follow-on risk, accepted: the two installed files stay unowned. On
  this watch that is normally moot (it absorbs installed files on
  disconnect). If the next preview says "A previously owned MTP object has
  a different persistent identity", the watch did not absorb the re-copied
  road file — record that on issue #17 for the next session.
- Filed issue #23 (backlog, owner to prioritize): let recovery finish a
  fully-verified install from the journal alone, so an encoder upgrade
  between install and recovery can never strand a journal again.

## Next

1. Owner action (one command, then the check): rename the journal —
   `Rename-Item "$env:LOCALAPPDATA\MarathonPlanner\mtp\journal.json" "journal.reviewed-copies-verified-20260825.json"`
   — then run the issue #17 watch check from this branch (import
   `acceptance-paced-synthetic.json`, terrain BOTH, week 1, preview should
   list two dated files to copy; confirm both names start with "Apr 2";
   record model and pass/fail on issue #17). After a PASS: merge PR #20 on
   green checks, close issue #17, move its card to Done. On a FAIL: record
   which step failed and diagnose read-only first.
2. Then issue #18 (date-aware cleanup of app-installed workouts; builds on
   the dated identities from #17). Issue #23 (recovery hardening) is on the
   board for the owner to prioritize.
3. Owner decision: the still-uncommitted AGENTS.md owner-communication
   section (`git diff AGENTS.md`) — commit as documentation-only or
   discard.
4. Owner decision: align the export package README wording with the BOTH
   install default (small follow-up).
5. Open puzzle, answer only if the owner remembers: were any workout
   values (title, choices, goal, paces) edited in the app before the
   2026-08-25 installs? That would explain why the journaled bytes differ
   from the fixture file. Not blocking anything.

## Blockers

- Issue #17's watch check is blocked until the owner archives the reviewed
  journal (Next, step 1).
- Issue #11 requires a mass-storage Garmin device; the available Forerunner
  265 exposes only MTP.
