# ai-apply

Multi-tenant web app that scrapes job boards, asks Claude to draft a tailored
cover letter for each role using your CVs, and surfaces the drafts in a
review-and-send UI. Runs locally on SQLite or hosts on Azure (App Service +
Postgres + Key Vault).

> **For AI agents working on this code:** read [CLAUDE.md](CLAUDE.md) first —
> it captures the invariants (anonymity contract, token-billing idempotency,
> secret handling) that aren't obvious from skimming files.

## What it does

You sign in, point it at your CV files, define one or more job-search
criteria, and click **Run**. A background worker scrapes the boards you
selected, picks the best CV per listing, generates a cover letter via
Claude, and saves each one as a reviewable draft. You read each draft in
the Apply UI, edit it inline, then mark it sent (or skip). Drafts never
leave the app — there's no auto-submit.

Sites supported today:

- **Seek** (Australia + New Zealand)
- **Wanted** (Korea)

Sign-in providers:

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
              scrape  fetch  generate(Anthropic)
              boards  CVs    → save Application
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

### Billing

Two modes per user:

- **`tokens` (default)** — generation calls go to Anthropic with the
  host's `ANTHROPIC_HOST_API_KEY`. Each call debits centitokens from
  the user's balance (Haiku 0.25, Sonnet 1, Opus 5 tokens per letter).
  Top-ups go through Stripe Checkout; the webhook credits idempotently.
- **`byok`** — the user supplies their own `sk-ant-...` key. No tokens
  are debited. The key is stored envelope-encrypted (Fernet locally,
  Key Vault in prod).

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

Requires Python 3.11+.

```bash
git clone <this-repo>
cd Azure-Host-AI-Job-Apply

python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt                  # runtime + pytest

cp .env.example .env
```

Fill in `.env`. The two values you must generate yourself:

```bash
# SESSION_SECRET — any random URL-safe string
python -c "import secrets; print(secrets.token_urlsafe(32))"

# SECRETS_MASTER_KEY — Fernet key for the envelope-encrypted local secret store
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

For sign-in to work, register at least one OAuth provider:

- **GitHub** — https://github.com/settings/developers, callback
  `http://localhost:8000/auth/github/callback`. Set `GITHUB_CLIENT_ID`
  and `GITHUB_CLIENT_SECRET`.
- **Google (optional)** — https://console.cloud.google.com/apis/credentials,
  redirect `http://localhost:8000/auth/google/callback`, scopes
  `openid email profile`.
- **Entra (optional)** — App registration with web platform redirect
  `http://localhost:8000/auth/ms/callback`, ID tokens enabled.

Then start the app:

```bash
python main.py
# → http://127.0.0.1:8000
```

The first run creates `data/ai-apply.db` (SQLite) and `data/secrets.json`
(local secret store). Both are gitignored.

### First-time setup in the UI

1. Open `http://127.0.0.1:8000`, click **Continue with GitHub** (or
   another provider you configured) on the login page.
2. **Settings**:
   - Choose a billing mode. In `byok` mode, paste your Anthropic API
     key (`sk-ant-...`).
   - Pick a model.
   - Provide CVs — either upload `.md`/`.pdf`/`.docx` files, or
     enter `repo_full_name` (e.g. `octocat/cv`) and `cv_dir`.
   - Add at least one search criteria row.
3. **Run** — kicks the pipeline. The page polls `/api/runs/{id}` until
   the run finishes.
4. **Applications** — review each draft, edit inline, mark sent.

### Run the tests

```bash
pytest                              # full suite
pytest tests/test_billing.py -vv    # one file
pytest -k anonymity                 # by name
```

`tests/conftest.py` sets the env vars the app needs and points
`DATABASE_URL` at a per-process tempdir SQLite, so tests need no `.env`
and leave no state behind.

## Project layout

```
main.py                      uvicorn entrypoint for local dev
pyproject.toml               deps (mirrored in requirements*.txt)
.env.example                 every required + optional env var, documented
Dockerfile + startup.sh      gunicorn config for App Service / containers
api/                         FastAPI handlers (one router per file)
db/                          SQLAlchemy 2.0 models + engine + bootstrap
worker/                      Background pipeline (no FastAPI types)
  pipeline.py                  execute_run(run_id) — orchestrator
  scrape.py + scraper/         vendored Seek + Wanted clients
  generate.py                  Anthropic call + output sanitisation
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
  Service system-assigned managed identity.
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
