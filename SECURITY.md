# Security

The single source for this repository's security posture. Read it before
touching authentication, user data, credentials, infrastructure, deployment,
or external input. Security-review outcomes are recorded as comments on the
feature's GitHub issue, not as new markdown files.

> Template note: filled in during bootstrap from the data-sensitivity
> interview. Delete placeholders that do not apply; add invariants the
> project's data demands. Keep the numbered-invariant form — sessions cite
> these by number.

## Invariants — these must always hold

1. {{DATA_INVARIANT: what data is sensitive here and where it may never
   appear — code, fixtures, tests, logs. If the project touches minors,
   payments, or health data, name the gating review that must pass before
   real data is allowed anywhere.}}
2. `{{DEFAULT_BRANCH}}` changes only via pull request with green checks.
3. No credentials in the repository, in config files, or in workflows.
   {{CI_AUTH: how CI authenticates to any cloud — prefer OIDC; name the
   role and what it can and cannot reach.}}
4. External downloads and GitHub Actions are pinned (SHA-256 / commit SHA).
5. {{DEPLOY_INVARIANT: the deploy identity's boundaries — e.g. "the deploy
   role never reaches application data." Delete if there is no deployment.}}
6. {{ADD_MORE: one invariant per hard-won rule. An invariant states what
   must hold and why it is deliberate, so a future session does not "fix"
   it.}}

## When a dedicated security session is mandatory

Before enabling any new surface that accepts external input or widens who
can see what: authentication, user-generated content, third-party APIs,
email/notification sending, payments. The session works from this file and
the diff under review; its outcome is recorded on the feature's issue.

## Known gaps

State honestly what has not been independently reviewed, and by whom
evidence was recorded. An empty section here is a claim — make sure it is
true.
