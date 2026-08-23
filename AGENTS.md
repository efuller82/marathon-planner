# Agent guidance

> **Not initialized yet?** If `BOOTSTRAP.md` exists at the repo root, this
> project has not been set up. Stop reading this file, read `BOOTSTRAP.md`,
> and follow it. Everything below applies only after bootstrap is complete.

{{PROJECT_NAME}} — {{ONE_PARAGRAPH_MISSION: what this is, who it serves, and
what is live today vs. in progress. Keep it to 3–4 lines; a fresh session
should understand the project's purpose from this paragraph alone.}}

## Start every session

1. Read `STATUS.md` — what is live, where work left off, the exact next
   action. Trust its "Next" list unless the owner's prompt overrides it.
2. Feature status lives **only** on the GitHub Projects board and its issues
   (`gh issue list`; board: "{{BOARD_NAME}}"). There is no markdown status
   mirror. Do not create one.
3. Before touching auth, user data, credentials, infrastructure, deployment,
   or external input: read `SECURITY.md`.

## Layout

| Path | What it is |
| --- | --- |
| {{FILL_DURING_BOOTSTRAP: one row per top-level directory. Say what each is AND what is special about it — what deploys, what is machine-checked, what must not be touched without a runbook.}} | |

## Commands

- `{{GATE_COMMAND}}` — the full gate CI runs. Green here means safe to merge.
- `{{DEV_COMMANDS: how to run the project locally, one line each.}}`

## Rules

- One GitHub issue and board card per feature. One branch
  (`feature/<issue>-<short-name>`) from a current `{{DEFAULT_BRANCH}}`.
  **One pull request.** Merge only on green checks. Never commit to
  `{{DEFAULT_BRANCH}}` directly.
- Work the board top-down: take the highest-priority item that is not
  blocked. If the owner's prompt names a task, that wins. Move the card as
  the work moves (In progress when you branch, Done when the PR merges).
- {{DEPLOY_RULE: how changes reach production, and which paths trigger it.
  If deployment is not set up yet, say so and name the issue that tracks it.}}
- {{COST_RULE: ask before any action that adds recurring cost; state the cost
  class in any plan. Adjust to the owner's answer from bootstrap.}}
- {{DATA_RULE: what data is sensitive and what may never appear in code,
  fixtures, tests, or logs. From the bootstrap interview.}}
- Keep documentation minimal: this file, `STATUS.md`, `SECURITY.md`, and
  code-adjacent docs the owner asks for. Do not add new doc files, plan
  documents, session logs, or validation machinery unless the owner asks.
  Design discussion belongs on the feature's GitHub issue.

## End every session (the handoff)

Do this after each completed task, and always before stopping:

1. **Replace** the contents of `STATUS.md` (never append) with: what is live,
   what this session did and learned, a numbered "Next" list with the exact
   next action first, and any blockers that are owner actions.
2. Make the board and issues reflect reality — close what shipped, comment
   decisions and review outcomes on the issue they belong to.
3. End your final message with a **handoff prompt**: one copy-paste line the
   owner can open the next session with, naming the next task. Example:
   `Continue {{PROJECT_NAME}}: Next item 1 in STATUS.md — <task>.`
