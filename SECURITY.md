# Security

This file records the deliberately small security posture of this local-only
application. The owner has not requested formal security-review sessions for
the planned desktop workflow.

## Invariants — these must always hold

1. Real runner plans are health-adjacent personal data. They remain on the
   user's machine and never appear in source, fixtures, tests, CI output,
   GitHub issues, or application logs.
2. `master` changes only through pull requests with green checks after the
   one-time bootstrap commit.
3. No credentials, session tokens, or account cookies are stored by the
   application or committed to the repository. CI uses no cloud credentials.
4. External downloads and GitHub Actions are pinned to a digest or commit SHA.
5. USB workout installation must not ask for a Garmin username or password and
   must only modify files that Marathon Planner can positively identify as its
   own.
6. Imported JSON, ZIP, calendar, and workout-plan files are untrusted input.
   Validate their type, size, paths, and schema before reading or extracting.
7. The application translates user-authored plans and never presents generated
   training load as medical or professional coaching advice.

## Scope changes

Local plan editing, export, and account-free USB installation do not require a
formal security-review session. Adding account authentication, cloud sync,
remote execution, public uploads, or third-party API credentials requires the
owner's explicit approval and a documented issue decision before implementation.

## Known gaps

- The mounted mass-storage installer has not yet been validated on a physical
  Garmin device (issue #11); the owner's available watch exposes only MTP.
- The Windows MTP path and its generated FIT workouts passed the owner-run
  physical Forerunner 265 check required by issue #12 on 2026-08-24. Other
  Garmin models, storage topologies, and operating systems remain unverified.
