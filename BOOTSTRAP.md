# Bootstrap — one-time project initialization

You are reading this because this repository is a fresh copy of the
new-project scaffold. Your job in this session: turn the scaffold into a
real, running project system — interview the owner, make the decisions
concrete, set up GitHub, seed the backlog, and hand off. When you finish,
**delete this file**; its existence is what tells every session the project
is not initialized.

Work through the phases in order. Do not skip the interview even if the
owner's prompt seems complete — confirm what you inferred and ask only what
you cannot infer.

## Phase 1 — Understand the project

The owner has given (or will give) a prompt describing the project. Read it,
then interview to fill the gaps. Batch questions (use AskUserQuestion if
available; otherwise ask in plain text, few at a time). You need answers to
all of these — infer where you can, confirm inferences, ask the rest:

1. **Mission** — what is this, who is it for, what does "done enough to use"
   look like? (Becomes the AGENTS.md opening paragraph and the MVP milestone.)
2. **Stack** — language, framework, runtime. Propose a default fitting the
   mission if the owner has no preference; get explicit agreement.
3. **Hosting and deployment** — where does this run in production, if
   anywhere? What is the monthly cost ceiling? Must the agent ask before any
   action that adds cost?
4. **Data sensitivity** — does it touch personal data, minors, payments,
   health, credentials? What may never appear in code, tests, or logs? This
   drives SECURITY.md and can add gating issues (privacy review, auth review).
5. **Repository** — name, GitHub owner/org, public or private, default
   branch name.
6. **Working style** — anything the owner insists on (test coverage bar,
   accessibility, specific tools, things they explicitly do NOT want).

## Phase 2 — Propose, then get one approval

Before creating anything, present a single consolidated proposal:

- The stack and project layout (top-level directories and what goes where).
- The gate: the one command that must pass before any merge (lint +
  typecheck + test + build, whatever fits the stack).
- A milestone breakdown of the mission into 5–15 feature-sized issues,
  ordered, each small enough for one session and one PR. First issues should
  produce a walking skeleton: repo scaffold of the chosen stack, the gate
  wired into CI, a deployable hello-world if there is a deploy target.
- Anything from Phase 1 that creates a standing rule (cost, data, security).

Revise until the owner approves. One approval covers all of Phase 3.

## Phase 3 — Execute the setup

Order matters; each step assumes the previous ones.

1. **Git**: `git init` if needed (delete any `.git` inherited from the
   scaffold copy first), initial commit of the scaffold files, default
   branch named per the interview.
2. **Fill the templates**: replace every `{{PLACEHOLDER}}` in `AGENTS.md`
   and `SECURITY.md` with real content from Phases 1–2. Nothing in
   `{{...}}` form may survive bootstrap. Write the real `.gitignore` for
   the stack.
3. **Stack scaffold**: create the minimal project skeleton so the gate
   command actually runs and passes (a hello-world app with one real test
   beats an empty shell).
4. **CI**: replace `.github/workflows/ci.yml`'s placeholder job with the
   real gate for the stack, keeping the bootstrap-guard job. Keep external
   actions pinned to commit SHAs. Add a deploy workflow only if a deploy
   target exists and credentials can be wired safely (prefer OIDC; never
   commit secrets) — otherwise file an issue for it instead.
5. **GitHub**: check `gh auth status` first; if not authenticated, have the
   owner run `gh auth login` (needs the `project` scope for boards —
   `gh auth refresh -s project`). Then:
   - `gh repo create <owner>/<name> --private|--public --source . --push`
   - `gh project create --owner <owner> --title "<board name>"` — link it
     to the repo (`gh project link`). The default Todo / In Progress / Done
     statuses are the kanban columns; do not over-engineer fields.
   - Create the issues from the approved Phase 2 breakdown using the
     feature-template sections (problem, outcome, acceptance criteria,
     security notes), and add each to the board
     (`gh project item-add <number> --owner <owner> --url <issue-url>`).
   - Enable branch protection on the default branch requiring the CI check,
     if the plan (private repos need a paid plan) allows; otherwise note in
     STATUS.md that green-checks-before-merge is enforced by rule, not by
     GitHub.
6. **Handoff**: replace `STATUS.md` per the ritual in `AGENTS.md` — what is
   live (probably "nothing yet"), what bootstrap decided, and a "Next" list
   whose item 1 is the first backlog issue. **Delete `BOOTSTRAP.md`.**
   Commit everything (this initial setup may go straight to the default
   branch — it is the last commit allowed to). Push. End your final message
   with the first handoff prompt.

## Guardrails for this session

- Ask before anything that costs money or publishes anything publicly.
- If a step fails (gh scope missing, plan limitation, network), do not stall
  the whole bootstrap: record the gap as a GitHub issue or a STATUS.md
  blocker and keep going.
- Keep the file count you leave behind minimal — the scaffold's docs plus
  the stack skeleton. No extra plan/design markdown; that lives on issues.
