# Status

- **Updated:** 2026-08-23

## Live

- A local Tkinter desktop shell runs with `python run.py`.
- The core model supports validated distance goals (`mi`, `km`, or `m`) and
  time goals (`sec`, `min`, or `hr`).
- The full local gate compiles the project and runs four passing unit tests.
- CI is configured to run the same compilation and unit-test gate on pull
  requests.
- The repository is initialized locally on `master`. It is not yet published.

## This session

- Bootstrapped the new-project scaffold for Marathon Planner.
- Established the product boundary: translate user-authored plans without
  prescribing or silently changing training load.
- Chose a local, standard-library Python/Tkinter stack with zero hosting cost.
- Made mileage- and time-based workout goals first-class domain values.
- Decided that one full-plan ZIP will contain ROAD/TRAIL FIT variants, calendar
  material, and instructions; a later rolling installer will respect Garmin's
  on-device workout limit without requiring Garmin credentials.
- Excluded Garmin-to-Garmin sharing from the planned workflow.

## Next

1. Owner action: run `gh auth login -h github.com`; the saved token for
   `efuller82` is invalid.
2. Create the public `efuller82/marathon-planner` GitHub repository, push
   `master`, create the "Marathon Planner" project board, and seed the approved
   feature issues in priority order.
3. Start the first feature branch and build the weekly plan editor with
   distance/time goals and paired ROAD/TRAIL choices.

## Blockers

- GitHub publishing, the project board, and feature issues require renewed
  GitHub CLI authentication.
