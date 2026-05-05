# CLAUDE.md

Notes for an AI coding agent (Claude Code or otherwise) working in this repo.
Read this before making any change — it captures the invariants you can't pick
up just by skimming files.

## What the app is

Multi-tenant FastAPI app with two distinct deployment modes:

- **Hosted** (Azure App Service + Postgres + Key Vault). Every user signs in
  via GitHub / Google / email-via-Entra, lives behind their own session,
  and pays for generations either with tokens (Stripe-funded host-paid
  Anthropic calls) or by supplying their own Anthropic key.
- **Local dev** (anything where `SECRETS_BACKEND != "azure-key-vault"`).
  All OAuth providers are disabled, `current_user` auto-creates a single
  shared `local@dev.local` user, token billing is disabled, and a third
  billing mode — `system` — shells out to the local `claude` CLI to use
  the developer's Claude subscription instead of an API key.

The mode toggle is `api/env.is_local()` (driven by `SECRETS_BACKEND`).
Routers and the worker check it directly; treat it as the canonical
"local vs prod" gate. The frontend gets the same flag from
`GET /api/config` and adapts the login page, billing pill, and settings UI.

The user flow is the same in both modes:

1. (Hosted only) Pick a sign-in provider.
2. Provide a CV source: either upload `.md`/`.pdf`/`.docx` directly, or
   connect a GitHub repo and point at a CV directory.
3. Save one or more **search criteria** (keywords, location, site).
4. Hit **Run**. The worker scrapes job boards, asks Claude to draft a
   cover letter per role using the user's CVs, and stores each draft as
   an `Application`.
5. Review drafts in the Apply UI: edit inline, mark-sent, or skip.

Three billing modes (`db.models.BillingMode`):

- `tokens` (hosted default) — debits `User.token_balance_centitokens`
  and calls Anthropic with `ANTHROPIC_HOST_API_KEY`. Top-ups via Stripe.
  **Rejected by `PUT /api/billing/mode` when local.**
- `byok` — uses the user's own `anthropic_key_ref`. No balance touched.
  In local mode the API allows switching to byok before a key is saved
  (optimistic) so users aren't chicken-and-egg-locked.
- `system` (local only) — generation calls shell out to the `claude`
  binary (Claude Code) via `worker.generate._invoke_claude_cli`. Uses
  the developer's subscription. **Rejected by `PUT /api/billing/mode`
  when not local.** Default for the auto-created local-dev user.

## Top-level layout

```
main.py                      uvicorn entrypoint for local dev
pyproject.toml               deps (mirrored in requirements*.txt)
.env.example                 every required + optional env var, documented
Dockerfile + startup.sh      gunicorn config for App Service / containers
api/                         FastAPI handlers (one router per file)
  app.py                       create_app() — middleware, routers, static mount
  env.py                       is_local() + ensure_local_secrets() (dev-only auto-gen)
  auth.py                      GitHub OAuth + local-mode current_user bypass
  google_auth.py               Google OIDC sign-in (404 in local mode)
  email_auth.py                Microsoft Entra (auth code flow) sign-in
  auth_common.py               find_or_create_user + provider-lock helpers
  secrets.py                   SecretStore: LocalSecretStore | AzureKeyVaultSecretStore
  models_const.py              Anthropic model catalogue + token packages
  settings_routes.py           /api/settings, /api/settings/criteria
  cvs_routes.py                /api/cvs (direct upload alternative to GitHub)
  runs.py                      POST/GET /api/runs — kicks BackgroundTasks
  applications_routes.py       /api/applications (list / edit / mark-sent / skip)
  billing.py                   Stripe Checkout + webhook + ledger endpoints
  token_ledger.py              credit_tokens / debit_tokens helpers
  startup.py                   recover_orphaned_runs() — boot-time sweep
db/                          SQLAlchemy 2.0 layer
  models.py                    every ORM model (User, Job, Application, Run, ...)
  session.py                   engine, SessionLocal, init_db()
worker/                      Background pipeline (no FastAPI types)
  pipeline.py                  execute_run(run_id) — the orchestrator
  scrape.py                    adapter around vendored scraper clients
  github_repo.py               list+fetch CVs via GitHub Contents API
  generate.py                  Anthropic SDK call OR `claude` CLI subprocess
  extractors/extract.py        md/txt/pdf/docx → plaintext
  scraper/                     vendored Seek (au/nz) + Wanted (kr) clients
  prompts/process-job.md       legacy reference prompt (the live system prompt
                               lives in generate.COVER_LETTER_DIRECTIVE)
  writing_guides/              en.md, ko.md — appended to the system prompt
frontend/                    static HTML + vanilla JS (no build step)
  index.html, run.html, settings.html, login.html, signup.html
  static/                      shell.{css,js}, apply.{css,js}, settings.js, etc.
infra/                       Bicep + deployment notes for Azure
tests/                       pytest; conftest.py sets env + temp SQLite
```

## Request → response → side effect

```
Browser (settings.html / run.html / index.html)
    ↓
api/app.py (SessionMiddleware, optional ProxyHeadersMiddleware)
    ↓
Router files in api/        ← always require Depends(current_user)
    ↓                          (local mode: auto-creates local@dev.local user)
SQLAlchemy session (db/session.SessionLocal)  +  SecretStore (api/secrets)
    ↓
For runs only: BackgroundTasks.add_task(execute_run, run.id)
    ↓
worker/pipeline.execute_run() opens its own session and:
    scrape() → seen-set dedupe → trim to user.max_jobs_per_run
        → fetch CVs (uploaded table or GitHub) → loop generate_cover_letter()
        → debit tokens (host-billed mode only) → save Application row
```

`execute_run` is intentionally framework-free so it can be moved to a
queue (Container Apps Job, Storage Queue + Function, Celery) without
touching the API. **Do not import FastAPI types into worker/.**

## Local vs hosted: the gate is `api.env.is_local()`

`is_local()` returns True when `SECRETS_BACKEND != "azure-key-vault"`.
That single boolean drives every behavioural difference:

| Concern | Local (`is_local()`) | Hosted |
|---|---|---|
| `SESSION_SECRET` / `SECRETS_MASTER_KEY` | Auto-generated and persisted to `data/.dev-secrets.json` on first boot if unset (`api/env.ensure_local_secrets`) | Must be set in app settings; missing `SESSION_SECRET` raises at startup |
| `current_user` dependency | Returns the `local@dev.local` user (auto-created with `billing_mode=system`); writes its id into the session | Reads `request.session["user_id"]`; 401 if missing |
| GitHub `/auth/github/login` + `/callback` | 404 "GitHub auth disabled in local mode" | Standard OAuth flow |
| Google `/auth/google/login` + `/callback` | 404 "Google auth disabled in local mode" | Standard OIDC flow |
| Entra email auth | Still wired, but unused (the local auth bypass returns first) | Standard auth-code flow |
| Login page (`/login.html`) | Hits `/api/config`, sees `local: true`, replaces window with `/` | Renders provider buttons |
| Top-nav user panel | Shows "Local dev — no auth", no logout button | Shows provider name + logout |
| Billing pill | "System Claude" or "Own API key" label, no balance/buy | Token balance + buy-more, or "Using own API key" |
| `PUT /api/billing/mode` `tokens` | 400 "token billing is disabled in local dev" | Allowed (default) |
| `PUT /api/billing/mode` `byok` | Allowed even if no key saved yet | Requires `anthropic_key_ref` |
| `PUT /api/billing/mode` `system` | Allowed | 400 "system mode is only available in local dev" |
| Stripe `/api/billing/checkout` | 501 if `STRIPE_SECRET_KEY` unset (same as hosted-without-Stripe) | Standard Checkout flow |
| Worker generation | Branches on `BillingMode`: `system` → `_invoke_claude_cli` (no key needed); `byok` → Anthropic SDK with user's key; `tokens` → host key + balance debit | `system` is rejected before reaching the worker |
| Settings page sections | `data-host-only` Billing & Tokens section is hidden; the Anthropic API section gains a local-only sub-control to toggle byok ↔ system | Standard layout |

If you add a new behaviour that should differ between modes, gate it on
`is_local()` and add a row above. Don't introduce a second mode flag.

## Data model essentials

All in `db/models.py`. Things that bite:

- **Email is the canonical account ID.** A user signs up under exactly
  one provider (`github` / `google` / `email`) and must use that same
  provider on subsequent logins. The check is in
  `api/auth_common.find_or_create_user`. GitHub is special: a user who
  signed up via Google/email may later **connect** GitHub for repo
  reads — that doesn't change their signup provider. Provider inference
  in `_infer_provider` checks `entra_oid` and `google_id` first
  precisely because of this. The local-dev shared user has
  `email="local@dev.local"`, `entra_oid="local-dev"`,
  `billing_mode=system` — don't reuse those values for anything else.
- **Tokens are stored as integer centitokens** (`×100`). Never use
  floats internally. Convert at the API boundary via
  `centitokens_to_tokens` / `tokens_to_centitokens` in `models_const.py`.
- **Per-model cost** lives in `MODEL_OPTIONS` (and the derived
  `COST_BY_MODEL`). Adding/removing a model means updating that tuple
  only — `ALLOWED_MODEL_IDS` and the dropdown payload derive from it.
- **`Application.generated_with_model` is internal metadata.** It must
  never appear in `body_md`, the UI surface to the candidate-to-employer
  flow, or anywhere employer-visible. The Apply UI does show it as a
  small "generated by" label, which is fine — that's the candidate
  reviewing their own draft.
- **`Job.raw`** is the full `JobListing.to_dict()` payload from the
  scraper. The applications API surfaces title/company/location/url
  out of `raw` — don't add new top-level columns; add to
  `JobListing` and re-scrape if you need new fields.

## The non-negotiables (security/UX invariants)

1. **Secrets never live in the DB as plaintext.** API keys and GitHub
   tokens are stored via `SecretStore`; only the opaque ref string
   (`local:anthropic-42`, `kv:anthropic-42`) is stored on the user row.
   When changing a key, `delete()` the old ref before `put()`-ing the
   new one (see `settings_routes.update_settings` for the pattern).
2. **The model is told to write in the candidate's first-person voice.**
   The contract lives in `worker/generate.py:COVER_LETTER_DIRECTIVE`.
   It bans meta-commentary ("as an AI", "as a language model") **but
   does NOT ban the words "Claude" or "Anthropic"** — devs applying to
   Anthropic, or to companies that integrate Claude, will mention those
   legitimately. Do not add a post-filter blocking those strings;
   `tests/test_anonymity.py` will fail and the change is wrong. The
   `system`-mode CLI path in `_invoke_claude_cli` shares the same
   system prompt — don't fork the contract.
3. **The model also cannot return markdown.** `_strip_markdown` is the
   safety net; the directive is the contract. Any new instruction added
   to the system prompt should not contradict either.
4. **Stripe webhook crediting is idempotent.** The unique constraint
   on `TokenPurchase.stripe_session_id` plus the conditional
   `pending → paid` UPDATE in `_credit_for_session` is what makes
   Stripe replays + concurrent `/checkout/verify` race safe. Don't
   refactor that flow without re-running `test_webhook_credit_is_idempotent`.
5. **Background tasks live in the API process.** If the worker dies
   mid-run the row is stranded. `api/startup.recover_orphaned_runs`
   sweeps live-status `Run`s on every boot. Anything that can transition
   a run into a non-terminal state must be reachable from `_LIVE` in
   that file.
6. **`init_db()` is not Alembic.** It calls `Base.metadata.create_all`
   and runs the tiny in-place column adds in `_ensure_user_columns`.
   For real schema changes (renames, drops, type changes, FKs), add
   Alembic and stop adding lines to that helper. New nullable columns
   on `user` can still go through `_ensure_user_columns` short-term.
7. **Don't bypass the auth gate in routers.** Always
   `Depends(current_user)`. In local mode the dependency itself does
   the bypass; routers shouldn't have their own `is_local()` checks
   for "let anyone in." Only billing/auth-flow endpoints check
   `is_local()` to gate behaviour, never to gate access.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate    # Win: .venv\Scripts\activate
pip install -r requirements-dev.txt                  # runtime + pytest
python main.py                                       # http://127.0.0.1:8000
```

That's it for the bare minimum — `ensure_local_secrets()` writes
`SESSION_SECRET` and `SECRETS_MASTER_KEY` into `data/.dev-secrets.json`
on first boot, the local-mode auth bypass logs you in as
`local@dev.local`, and the auto-created user lands in `system` billing
mode.

Two extra steps before you can actually run a pipeline:

1. **Generation.** Either:
   - Install Claude Code (`https://claude.com/claude-code`), run
     `claude` once to sign in, and stick with the default `system`
     mode; or
   - Switch to `byok` in Settings → Anthropic API and paste an
     `sk-ant-...` key. Set `CLAUDE_CLI_PATH` if the binary isn't on
     `PATH`.
2. **CVs.** Either upload files via Settings → Direct CV upload, or
   connect a GitHub repo. Note that the local-mode user has no GitHub
   token (the OAuth flow is disabled), so direct upload is the path
   that works out of the box.

If you want the hosted-mode experience locally (real OAuth, token
billing), set `SECRETS_BACKEND=azure-key-vault` is *not* an option — it
requires a real Key Vault. Use a separate dev tenant for OAuth, set
`SESSION_SECRET` and `SECRETS_MASTER_KEY` manually, and provide
provider client IDs/secrets in `.env`. The `is_local()` check still
returns True (because `SECRETS_BACKEND != "azure-key-vault"`), so OAuth
endpoints will still 404 — there's no half-way "local with real auth"
mode today. If you need one, propose adding a dedicated env flag
rather than overloading `SECRETS_BACKEND`.

The first run creates `data/ai-apply.db` (SQLite), `data/secrets.json`
(envelope-encrypted user-secret sidecar), and `data/.dev-secrets.json`
(the auto-generated session/master key pair). All three are
git-ignored. Wipe the directory to reset.

## Tests

```bash
pytest                              # full suite
pytest tests/test_billing.py -vv    # subset
pytest -k anonymity                 # by name
```

`tests/conftest.py` sets the env vars the app requires and points
`DATABASE_URL` at a per-process tempdir SQLite. **Don't read `.env`
in tests** and don't write fixtures that depend on a master key being
set externally. Tests run with the default local-ish environment
(`SECRETS_BACKEND` unset → `is_local()` True), so any test that needs
the hosted code path must `monkeypatch.setenv("SECRETS_BACKEND",
"azure-key-vault")` (or, more cheaply, monkeypatch `api.env.is_local`).

When you change anything in `api/billing.py`, `worker/generate.py`, or
`api/runs.py`, run the relevant test file as a sanity check before
asking the user to verify.

## Where to start for common tasks

| Task | Start in | Notes |
|---|---|---|
| Add a new Anthropic model option | `api/models_const.py` | Add to `MODEL_OPTIONS`. Cost is per-letter centitokens. |
| Add a new sign-in provider | `api/auth_common.py` | Then a router file mirroring `google_auth.py`. Update `_infer_provider`, `provider_mismatch_redirect`. Add to `login.html`. Don't forget the `_block_if_local()` guard at the top of each route. |
| Add a scraper site | `worker/scraper/` (new client) + `worker/scrape.py:CLIENTS` + `db.models.Criteria.site` enum + `api/settings_routes.CriteriaIn.site` regex |
| Change the cover-letter contract | `worker/generate.py:COVER_LETTER_DIRECTIVE` | Mind the anonymity tests; never re-introduce a brand-name filter. Both the SDK path and the `claude` CLI path read this same string. |
| Add a new column on `User` | `db/models.py` + `db/session._ensure_user_columns` (idempotent ALTER) | Long-term: switch to Alembic. |
| Add a new application action | `api/applications_routes.py` | Mirror `mark-sent` / `skip` patterns. Keep the resolver `_resolve()` for ownership checks. |
| Surface a new setting in the UI | `api/settings_routes.SettingsOut` + `frontend/static/settings.js` | The UI uses fetch against `/api/settings`. If the setting is hosted-only, mark the section with `data-host-only` so the local-mode toggle hides it. |
| Add a billing mode | `db.models.BillingMode` enum + branches in `api/runs.start_run`, `api/billing.set_mode`, `worker/pipeline._run` | Decide local-only vs hosted-only and gate `set_mode` accordingly. |
| Move worker off BackgroundTasks | Replace `background.add_task(execute_run, run.id)` in `api/runs.py` with a queue enqueue. `worker.pipeline.execute_run` already opens its own DB session. |

## Don'ts

- Don't write directly to `User.token_balance_centitokens`. Use
  `credit_tokens` / `debit_tokens` so the ledger row is created.
- Don't assume `user.repo_link` exists. A user who signed up via Google
  may not have connected GitHub. The local-dev user **never** has one.
  Direct CV upload (`UploadedCV` table) is a parallel source —
  `worker/pipeline._run` checks both.
- Don't add markdown formatting to cover-letter outputs. The directive
  bans it and `_strip_markdown` would silently undo it anyway.
- Don't remove the `prompt=create` parameter on Entra signup
  (`api/email_auth.signup`) — it's how External ID lands users on the
  signup tab.
- Don't post-filter the model's output for the words "Claude" or
  "Anthropic". See invariant #2.
- Don't add new "is local?" logic by reading env vars directly — call
  `api.env.is_local()` so there's one source of truth.
- Don't shell out to `claude` outside `worker/generate._invoke_claude_cli`
  and `worker/pipeline._claude_cli_logged_in`. The CLI is a runtime
  dependency only in `system` mode; everywhere else, the absence of
  the binary should not break anything.
- Don't `git add -A`; the dev DB, secrets sidecar, and
  `data/.dev-secrets.json` live under `data/` and the gitignore catches
  them, but local config dumps (`webapp-config*.json`, `.azureenv`) are
  also explicitly ignored — preserve those rules.

## Production deployment

Provisioned by `infra/main.bicep`. Reads:

- App Service (Linux Python) running `gunicorn` via `startup.sh`.
- Postgres Flexible Server — set `DATABASE_URL`.
- Key Vault — set `SECRETS_BACKEND=azure-key-vault` and
  `AZURE_KEY_VAULT_URL`. `DefaultAzureCredential` picks up the App
  Service managed identity. **`SECRETS_BACKEND=azure-key-vault` is
  also what flips `is_local()` to False — without it, the app boots in
  local-dev auth-bypass mode even on Azure.**
- App settings: also set `SESSION_HTTPS_ONLY=1` and
  `TRUST_PROXY_HEADERS=1` (the middleware in `app.py` reads them).
- CI: `.github/workflows/acr-deploy.yml` does `az acr build` + restart
  on push to `main`. Federated identity, no client secret.

See `infra/README.md` for the full Bicep walkthrough.
