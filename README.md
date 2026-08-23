# New-project scaffold

A reusable starting kit for running a software project with an LLM agent
(Claude Code or similar): a session entry point, a kanban-driven task loop,
GitHub issue/PR/Actions integration, and a session-handoff ritual so every
session picks up exactly where the last one stopped.

## How to use it

1. Copy the **contents** of this folder into a new, empty project directory.
   (Do not copy a `.git` folder if one exists; the new project gets its own.)
2. Open your agent in that directory and give it one prompt describing the
   project — a sentence or a page, whatever you have. Even
   "read the repo and get started" works.
3. The agent finds `BOOTSTRAP.md`, interviews you to fill the gaps, sets up
   the repo, board, CI, and backlog, then deletes `BOOTSTRAP.md` and hands
   you the first real prompt.
4. From then on, every session is: paste the handoff prompt from the previous
   session (or just say "continue"), and the agent reads `STATUS.md`, takes
   the next task from the board, ships it, and hands off again — one prompt
   after another until the project is done.

## What's in the box

| File | Purpose |
| --- | --- |
| `CLAUDE.md` | Agent entry point; imports `AGENTS.md`. |
| `AGENTS.md` | The operating manual every session reads first. Placeholders are filled during bootstrap. |
| `BOOTSTRAP.md` | The one-time interview and setup path. Deleted when initialization completes. |
| `STATUS.md` | The session handoff. Replaced (never appended) at the end of every session. |
| `SECURITY.md` | Security posture template; filled during bootstrap, consulted before any sensitive work. |
| `.github/` | Issue templates, PR template, and a CI workflow placeholder that blocks PRs until bootstrap is complete. |
| `.gitignore` | Minimal seed; extended for the chosen stack during bootstrap. |

This scaffold itself stays generic — nothing in it assumes a language,
framework, or host. All of those decisions are made in the interview and
written into the project by the agent.
