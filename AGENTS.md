# Agent guidance

Marathon Planner is a local Python desktop application for runners and coaches
to enter or import user-authored training plans, create distinct road and trail
workout choices, and package Garmin-compatible workouts for simple handoff.
The desktop shell and core run-goal model are live; editing and export features
are being built incrementally.

## Start every session

1. Read `STATUS.md` for what is live, where work stopped, and the exact next
   action. Trust its "Next" list unless the owner's prompt overrides it.
2. Feature status lives only on the GitHub Projects board and its issues
   (`gh issue list`; board: "Marathon Planner"). There is no markdown status
   mirror. Do not create one.
3. Before touching credentials, Garmin accounts, deployment, or imported plan
   files, read `SECURITY.md`.

## Layout

| Path | What it is |
| --- | --- |
| `src/marathon_planner/` | Application package: domain models, local services, and Tkinter UI. |
| `tests/` | Standard-library unit tests using synthetic workout data only. |
| `.github/` | Issue and pull-request templates plus the machine-checked CI gate. |
| `run.py` | Local desktop launcher. |

## Commands

- `python run.py` — launch the desktop application locally.
- `python -m compileall -q src tests run.py && python -m unittest discover -s tests -v` — the full gate CI runs.

## Rules

- One GitHub issue and board card per feature. One branch
  (`feature/<issue>-<short-name>`) from a current `master`. **One pull
  request.** Merge only on green checks. Never commit to `master` directly.
- Work the board top-down: take the highest-priority item that is not blocked.
  If the owner's prompt names a task, that wins. Move the card as the work
  moves (In progress when branching, Done when the PR merges).
- There is no hosted deployment. Releases remain local until a dedicated
  packaging/release issue is approved and completed.
- Ask before any action that creates a recurring or paid cost. The default
  project cost is zero.
- Real runner plans are health-adjacent personal data. They remain local and
  may never appear in source, fixtures, tests, CI logs, or GitHub issues. Use
  synthetic names, dates, distances, times, and paces in public artifacts.
- The application must never request Garmin credentials for USB installation.
- The planner preserves user-authored training choices. It may validate and
  translate a plan, but it does not prescribe training load or silently alter
  workouts.
- Keep documentation minimal: this file, `STATUS.md`, `SECURITY.md`, and
  code-adjacent documentation the owner asks for. Do not add plan documents,
  session logs, or validation machinery unless requested. Design discussion
  belongs on the feature's GitHub issue.

## End every session

1. Replace `STATUS.md` (never append) with what is live, what this session did
   and learned, a numbered "Next" list with the exact next action first, and
   blockers that require owner action.
2. Make the board and issues reflect reality: close what shipped and record
   decisions on the relevant issue.
3. End the final response with a copy-paste handoff prompt naming the next task.
