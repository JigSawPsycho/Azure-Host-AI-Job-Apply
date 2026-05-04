# CLAUDE.md

Notes for an AI coding agent (Claude Code or otherwise) working in this repo.
Read this before making any change — it captures the invariants you can't pick
up just by skimming files.

## What the app is

Multi-tenant FastAPI app. Each signed-in user:

1. Picks a sign-in provider (GitHub / Google / email-via-Entra).
2. Provides a CV source: either upload `.md`/`.pdf`/`.docx` directly, or
   connect a GitHub repo and point at a CV directory.
3. Saves one or more **search criteria** (keywords, location, site).
4. Hits **Run**. The worker scrapes job boards, asks Claude to draft a
   cover letter per role using the user's CVs, and stores each draft as an
   `Application`.
5. Reviews drafts in the Apply UI: edit inline, mark-sent, or skip.

Two billing modes per user:

- `tokens` (default) — generations are debited from `User.token_balance_centitokens`
  and call Anthropic with `ANTHROPIC_HOST_API_KEY` (host-paid). Top-ups go through
  Stripe Checkout.
- `byok` — uses the user's own `anthropic_key` and never touches the balance.

## Top-level layout

```
main.py                      uvicorn entrypoint for local dev
pyproject.toml               deps (mirrored in requirements*.txt)
.env.example                 every required + optional env var, documented
Dockerfile + startup.sh      gunicorn config for App Service / containers
api/                         FastAPI handlers (one router per file)
  app.py                       create_app() — middleware, routers, static mount
  auth.py                      GitHub OAuth (dual: sign-in + connect-repo)
  google_auth.py               Google OIDC sign-in
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
  generate.py                  Anthropic call + output sanitisation
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
    ↓
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

## Data model essentials

All in `db/models.py`. Things that bite:

- **Email is the canonical account ID.** A user signs up under exactly
  one provider (`github` / `google` / `email`) and must use that same
  provider on subsequent logins. The check is in
  `api/auth_common.find_or_create_user`. GitHub is special: a user who
  signed up via Google/email may later **connect** GitHub for repo
  reads — that doesn't change their signup provider. Provider inference
  in `_infer_provider` checks `entra_oid` and `google_id` first
  precisely because of this.
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
   `tests/test_anonymity.py` will fail and the change is wrong.
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

## Local development

```bash
python -m venv .venv && source .venv/bin/activate    # Win: .venv\Scripts\activate
pip install -r requirements-dev.txt                  # runtime + pytest
cp .env.example .env
# Required:
#   SESSION_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
#   SECRETS_MASTER_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
#   GITHUB_CLIENT_ID + GITHUB_CLIENT_SECRET (from https://github.com/settings/developers)
python main.py        # http://127.0.0.1:8000
```

Other providers (Google, Entra) and Stripe are optional — their endpoints
return 501 when unconfigured rather than blowing up. The login page
surfaces that gracefully.

The first run creates `data/ai-apply.db` (SQLite) and `data/secrets.json`
(envelope-encrypted secret store sidecar). Both are git-ignored. Wipe
the directory to reset.

## Tests

```bash
pytest                              # full suite
pytest tests/test_billing.py -vv    # subset
pytest -k anonymity                 # by name
```

`tests/conftest.py` sets the env vars the app requires and points
`DATABASE_URL` at a per-process tempdir SQLite. **Don't read `.env`
in tests** and don't write fixtures that depend on a master key being
set externally.

When you change anything in `api/billing.py`, `worker/generate.py`, or
`api/runs.py`, run the relevant test file as a sanity check before
asking the user to verify.

## Where to start for common tasks

| Task | Start in | Notes |
|---|---|---|
| Add a new Anthropic model option | `api/models_const.py` | Add to `MODEL_OPTIONS`. Cost is per-letter centitokens. |
| Add a new sign-in provider | `api/auth_common.py` | Then a router file mirroring `google_auth.py`. Update `_infer_provider`, `provider_mismatch_redirect`. Add to `login.html`. |
| Add a scraper site | `worker/scraper/` (new client) + `worker/scrape.py:CLIENTS` + `db.models.Criteria.site` enum + `api/settings_routes.CriteriaIn.site` regex |
| Change the cover-letter contract | `worker/generate.py:COVER_LETTER_DIRECTIVE` | Mind the anonymity tests; never re-introduce a brand-name filter. |
| Add a new column on `User` | `db/models.py` + `db/session._ensure_user_columns` (idempotent ALTER) | Long-term: switch to Alembic. |
| Add a new application action | `api/applications_routes.py` | Mirror `mark-sent` / `skip` patterns. Keep the resolver `_resolve()` for ownership checks. |
| Surface a new setting in the UI | `api/settings_routes.SettingsOut` + `frontend/static/settings.js` | The UI uses fetch against `/api/settings`. |
| Move worker off BackgroundTasks | Replace `background.add_task(execute_run, run.id)` in `api/runs.py` with a queue enqueue. `worker.pipeline.execute_run` already opens its own DB session. |

## Don'ts

- Don't write directly to `User.token_balance_centitokens`. Use
  `credit_tokens` / `debit_tokens` so the ledger row is created.
- Don't assume `user.repo_link` exists. A user who signed up via Google
  may not have connected GitHub. Direct CV upload (`UploadedCV` table)
  is a parallel source — `worker/pipeline._run` checks both.
- Don't add markdown formatting to cover-letter outputs. The directive
  bans it and `_strip_markdown` would silently undo it anyway.
- Don't remove the `prompt=create` parameter on Entra signup
  (`api/email_auth.signup`) — it's how External ID lands users on the
  signup tab.
- Don't post-filter the model's output for the words "Claude" or
  "Anthropic". See invariant #2.
- Don't `git add -A`; the dev DB and secrets sidecar live under `data/`
  and the gitignore catches them, but local config dumps
  (`webapp-config*.json`) are also explicitly ignored — preserve those
  rules.

## Production deployment

Provisioned by `infra/main.bicep`. Reads:

- App Service (Linux Python) running `gunicorn` via `startup.sh`.
- Postgres Flexible Server — set `DATABASE_URL`.
- Key Vault — set `SECRETS_BACKEND=azure-key-vault` and
  `AZURE_KEY_VAULT_URL`. `DefaultAzureCredential` picks up the App
  Service managed identity.
- App settings: also set `SESSION_HTTPS_ONLY=1` and
  `TRUST_PROXY_HEADERS=1` (the middleware in `app.py` reads them).
- CI: `.github/workflows/acr-deploy.yml` does `az acr build` + restart
  on push to `main`. Federated identity, no client secret.

See `infra/README.md` for the full Bicep walkthrough.
