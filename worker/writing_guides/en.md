# Professional Writing Guide

Notes to self (Claude) for writing cover letters, CVs, and website copy in this
repo. Read before editing anything under `cover-letters/`, `cv/`, or `website/`.

## Keep internal-only details out

Professional materials are read by recruiters, hiring managers, and the public.
They do not care about the internal bookkeeping of how the work got tracked.
Omit anything that only makes sense inside the team that shipped it.

Do **not** mention:

- Ticket / issue / story numbers (e.g. `JIRA-1234`, `#456`, `PROJ-789`)
- Sprint names, sprint numbers, or release train identifiers
- Internal project codenames that were never public
- Branch names, commit hashes, or PR numbers
- Internal tool names that need insider context to understand
- Team-internal acronyms and jargon that aren't industry-standard
- Dashboard / wiki / Confluence links
- Names of internal stakeholders who aren't public figures

## Write about impact instead

Translate internal references into outcomes a stranger can evaluate:

- Bad: "Closed JIRA-1423 to refactor the auth module."
- Good: "Refactored the authentication module, cutting login latency by 40%."

- Bad: "Delivered epic FOO-22 during Q3 sprint 4."
- Good: "Led a quarter-long initiative to migrate 12 services to the new
  platform, shipped on schedule."

## Quick checklist before saving

1. Would a reader outside the company understand every reference?
2. Does each bullet describe impact, scope, or skill — not process artifacts?
3. Have I removed every ticket ID, sprint tag, and internal codename?
4. Do all factual claims match the guardrails below?

If any answer is no, rewrite before committing.

## Factual accuracy guardrails

Recurring corrections to apply across all materials (CVs, cover letters,
LinkedIn, website). If you find yourself writing something that contradicts
these, the writing is wrong, not the guardrail.

### MDM authentication system

The MDM auth system is a **server-built** system. Michael implemented the
**device-side consumption** only - the Android backend and Unity VR client
code that calls the server-side auth APIs built by the Enterprise Portal
team.

- **Do not** write "designed and built an authentication system", "built a
  configurable organisation-level auth system", or anything implying
  end-to-end authorship of the auth system.
- **Do** write "implemented the client-side / device-side consumption of the
  organisation-level auth system" or "built the client-side auth flows
  against server-side APIs built by portal developers".
- Supported login modes (anonymous, ID-based, username/password, SSO) are
  modes the backend supports; Michael consumed them on the client. Mention
  the modes only in the context of client-side consumption, never as modes
  he designed.
- Michael did "barely anything" on the backend side of auth. Assume no
  server-side auth ownership unless told otherwise.

### MDM remote app installation / ADB

ADB is used for device **enrollment** only, via the Windows Provisioning
Tool. ADB is **not** the mechanism for remote app installation. Do not pin
remote app installation to ADB anywhere.
