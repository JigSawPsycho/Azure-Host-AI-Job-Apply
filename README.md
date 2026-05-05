# ai-apply

Multi-tenant web app that scrapes job boards, asks Claude to draft a tailored
cover letter for each role using your CVs, and surfaces the drafts in a
review-and-send UI. Ships with two modes:

- **Local dev mode** — single-user, no auth, no Stripe. Optionally uses your
  Claude Code subscription for generation (no API key needed). Runs on
  SQLite. One command to start.
- **Hosted mode** — multi-tenant on Azure (App Service + Postgres + Key
  Vault). OAuth sign-in (GitHub / Google / Entra), Stripe-funded token
  billing, encrypted user secrets in Key Vault.

> **For AI agents working on this code:** read [CLAUDE.md](CLAUDE.md) first —
> it captures the invariants (anonymity contract, token-billing idempotency,
> secret handling, the local-vs-hosted gate) that aren't obvious from
> skimming files.

## What it does

You sign in (or in local mode, just open the app), point it at your CV
files, define one or more job-search criteria, and click **Run**. A
background worker scrapes the boards you selected, picks the best CV per
listing, generates a cover letter via Claude, and saves each one as a
reviewable draft. You read each draft in the Apply UI, edit it inline,
then mark it sent (or skip). Drafts never leave the app — there's no
auto-submit.

Sites supported today:

- **Seek** (Australia + New Zealand)
- **Wanted** (Korea)

Sign-in providers (hosted mode only):

- **GitHub OAuth** (also unlocks read access to a CV repo).
- **Google OIDC** (sign-in only).
- **Email/password via Microsoft Entra** (auth code flow). External ID
  and B2C tenants both work.

## How it works

```
┌─────────┐    ┌────────────────┐    ┌────────────────────────────┐
│ Browser │───▶│ FastAPI (api/) │───▶│ SQLAlchemy + SecretStore   │
└─────────┘    └────────────────┘    └────────────────────────────┘
                       │
                       │  POST /api/runs
                       ▼
              ┌──────────────────────┐
              │ BackgroundTask:      │
              │ worker.pipeline      │
              └──────────────────────┘
                  │     │     │
                  ▼     ▼     ▼
              scrape  fetch  generate
              boards  CVs    (Anthropic SDK or `claude` CLI)
                              → save Application
```

Per run, the worker (`worker/pipeline.execute_run`):

1. Loads the user's enabled `Criteria` rows.
2. Calls each scraper, dedupes against the user's `Job` table, trims to
   `max_jobs_per_run`.
3. Loads CVs from either the `uploaded_cv` table (direct upload) or the
   linked GitHub repo.
4. For each listing up to `max_drafts_per_run`, calls Claude with a
   strict system prompt that picks the best-fit CV and drafts the
   letter. Output is plain text only — no markdown, no meta-commentary.
5. Persists each draft as an `Application` row (status `unsent`).
6. In host-billed mode, debits the per-model cost from the user's
   token balance and writes a matching ledger entry.

The worker is deliberately framework-free so it can be moved to a queue
(Container Apps Job, Storage Queue, Celery) without touching the API.

### Billing modes

Three modes per user (`db.models.BillingMode`):

- **`tokens` (hosted default)** — generation calls go to Anthropic with
  the host's `ANTHROPIC_HOST_API_KEY`. Each call debits centitokens
  from the user's balance (Haiku 0.25, Sonnet 1, Opus 5 tokens per
  letter). Top-ups via Stripe Checkout; the webhook credits
  idempotently. **Disabled in local mode.**
- **`byok`** — the user supplies their own `sk-ant-...` key. No tokens
  debited. The key is stored envelope-encrypted (Fernet locally, Key
  Vault in prod). Available in both modes.
- **`system` (local only)** — generation is routed through the local
  `claude` binary (Claude Code) and uses your Claude subscription
  instead of an API key. The auto-created local user defaults to this
  mode. **Rejected in hosted mode.**

### Cover-letter contract

The system prompt in `worker/generate.py:COVER_LETTER_DIRECTIVE`:

- Bans markdown, headings, bullets, code blocks.
- Bans meta-commentary ("as an AI", "as a language model", "Here is
  the letter…", drafting notes, hedges).
- Allows the model to use the `<skip>reason</skip>` token when the
  candidate clearly fails a hard requirement.
- **Does not** ban the words "Claude" or "Anthropic" — those legitimately
  appear in cover letters for jobs at Anthropic or at companies that
  integrate Claude. The safety net is the human review in the Apply UI
  before mark-sent.

The model the user picks (Settings → model dropdown) is recorded on
each `Application` row as **internal metadata only** — never written
into `body_md` or anything employer-visible.

## Run it locally

Requires Python 3.11+. The fast path:

```bash
git clone <this-repo>
cd Azure-Host-AI-Job-Apply

python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt                  # runtime + pytest

python main.py
# → http://127.0.0.1:8000
```

That's it. On first boot the app:

- Auto-generates `SESSION_SECRET` and `SECRETS_MASTER_KEY` and persists
  them to `data/.dev-secrets.json` (gitignored).
- Creates `data/ai-apply.db` (SQLite) and `data/secrets.json`
  (envelope-encrypted user-secret sidecar).
- Detects local mode (no `SECRETS_BACKEND=azure-key-vault`), disables
  the OAuth providers, and auto-creates a single
  `local@dev.local` user. The login page redirects straight into the
  app — no sign-in screen.

You'll need one or two more things before a run actually works:

### Generation source

The auto-created user starts in **`system` billing mode**, which
shells out to the local Claude Code CLI:

1. Install Claude Code from <https://claude.com/claude-code>.
2. Run `claude` once and sign in.
3. (Optional) If `claude` isn't on your `PATH`, set
   `CLAUDE_CLI_PATH=/absolute/path/to/claude` in `.env`.

If you'd rather use an Anthropic API key directly, open
**Settings → Anthropic API**, switch the local-mode toggle to **"Use my
own Anthropic API key"**, paste an `sk-ant-...` key, and save. Either
mode works — only one needs to be set up.

### CV source

Open **Settings → Direct CV upload** and upload one or more
`.md`/`.pdf`/`.docx`/`.txt` files (250 KB per file, 5 MB total). This
is the easiest path in local mode because the GitHub OAuth flow is
disabled — there's no way to wire up a repo without sign-in.

### Run a search

1. **Settings → Search criteria** — add at least one row (keywords,
   location, site).
2. **Run** (top nav) — kicks the pipeline. The page polls
   `/api/runs/{id}` until the run finishes.
3. **Applications** (top nav) — review each draft, edit inline, mark
   sent.

### Run the tests

```bash
pytest                              # full suite
pytest tests/test_billing.py -vv    # one file
pytest -k anonymity                 # by name
```

`tests/conftest.py` sets the env vars the app needs and points
`DATABASE_URL` at a per-process tempdir SQLite, so tests need no `.env`
and leave no state behind.

## Local vs hosted: what's different

The same codebase runs in both modes. The flag is `api.env.is_local()`,
which is True whenever `SECRETS_BACKEND != "azure-key-vault"`.

| Concern | Local | Hosted |
|---|---|---|
| **Setup** | `pip install -r requirements-dev.txt && python main.py`. No env vars required. | Bicep-provisioned App Service + Postgres + Key Vault; OAuth client IDs in app settings; Stripe keys for billing. |
| **Sign-in** | None — auto-logged-in as `local@dev.local`. The login page bounces straight to the app. | GitHub / Google / Entra. Email is the canonical account ID; users are locked to their signup provider. |
| **Multi-tenant?** | No — one shared local user. | Yes — every signed-in user is fully isolated (jobs, applications, criteria, secrets). |
| **Secrets** | `SESSION_SECRET` + `SECRETS_MASTER_KEY` auto-generated into `data/.dev-secrets.json`. User-supplied secrets (Anthropic key, GitHub token) Fernet-encrypted into `data/secrets.json`. | Both must be set in App Service config. User-supplied secrets stored in Azure Key Vault via the App Service managed identity. |
| **Database** | SQLite at `data/ai-apply.db`. | Azure Database for PostgreSQL Flexible Server (set `DATABASE_URL`). |
| **Generation** | `system` mode (local `claude` CLI, your subscription) **or** `byok` (your own `sk-ant-...`). | `tokens` (host-paid via `ANTHROPIC_HOST_API_KEY`, debited from balance) **or** `byok`. |
| **Token billing** | Disabled. The Billing & Tokens settings panel is hidden. | Active. Three Stripe-backed packages (Starter / Standard / Bulk), webhook-credited idempotently. |
| **Stripe** | Not used. `/api/billing/checkout` returns 501 if hit. | Required for `tokens` mode top-ups. Webhook signs against `STRIPE_WEBHOOK_SECRET`. |
| **Background worker** | In-process FastAPI `BackgroundTasks`. Run state recovered on restart by `recover_orphaned_runs()`. | Same code path today; can be lifted to Container Apps Job / Storage Queue + Function without touching the API. |
| **Top-nav user panel** | "Local dev — no auth", no logout. | Provider name, email, log-out button. |
| **Billing pill** | "System Claude" or "Own API key" label, no balance. | Token balance + buy-more button, or "Using own API key". |

## Project layout

```
main.py                      uvicorn entrypoint for local dev
pyproject.toml               deps (mirrored in requirements*.txt)
.env.example                 every required + optional env var, documented
Dockerfile + startup.sh      gunicorn config for App Service / containers
api/                         FastAPI handlers (one router per file)
  env.py                       is_local() + ensure_local_secrets()
db/                          SQLAlchemy 2.0 models + engine + bootstrap
worker/                      Background pipeline (no FastAPI types)
  pipeline.py                  execute_run(run_id) — orchestrator
  scrape.py + scraper/         vendored Seek + Wanted clients
  generate.py                  Anthropic SDK call OR `claude` CLI subprocess
  extractors/                  md/txt/pdf/docx → plaintext
frontend/                    static HTML + vanilla JS (no build step)
infra/                       Bicep + deployment notes for Azure
tests/                       pytest; conftest.py sets env + temp SQLite
```

A more detailed map (and the design invariants that bind it together)
is in [CLAUDE.md](CLAUDE.md).

## Production deployment (Azure)

The architecture maps cleanly onto:

- **App Service (Linux, Python 3.11)** — runs gunicorn via `startup.sh`.
- **Azure Database for PostgreSQL Flexible Server** — set `DATABASE_URL`.
- **Key Vault** — set `SECRETS_BACKEND=azure-key-vault` and
  `AZURE_KEY_VAULT_URL`. `DefaultAzureCredential` picks up the App
  Service system-assigned managed identity. **`SECRETS_BACKEND=azure-key-vault`
  is also what flips the app out of local mode** — without it the
  hosted deployment would boot with auth disabled.
- **Container Apps Job** or **Storage Queue + Function** for
  out-of-process workers (the in-process `BackgroundTasks` is fine for
  v1, but `worker.pipeline.execute_run` is already self-contained so
  the swap is mechanical).

`infra/main.bicep` provisions all of the above.
`.github/workflows/acr-deploy.yml` builds a container and restarts the
Web App on push to `main`. See [infra/README.md](infra/README.md) for
the full walkthrough.

Production env hardening — set both:

- `SESSION_HTTPS_ONLY=1` (secure-cookie flag).
- `TRUST_PROXY_HEADERS=1` (honour `X-Forwarded-Proto` from App Service).

## Known risks

1. **Scraper TOS.** Multi-tenant load is more visible than single-user.
   Throttle and consider per-user proxies before scaling.
2. **Scanned PDFs.** `pdfplumber` extracts no text from image-only PDFs;
   the worker surfaces an error rather than feeding garbage to the LLM.
3. **Cost runaway.** `User.max_drafts_per_run` caps generations per run.
   Surface estimated token cost before kickoff in v2.
4. **Local-mode auth bypass on Azure.** If `SECRETS_BACKEND` is unset
   on a deployed App Service, the app boots in local-dev mode with
   auth disabled and a shared `local@dev.local` user. The Bicep
   template sets it correctly; verify in App Service → Configuration
   if you ever provision by hand.
