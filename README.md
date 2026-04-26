# ai-apply

Multi-tenant web app: each signed-in dev connects a GitHub repo of CV files,
configures search criteria, and clicks **Run** to scrape job boards and have
Claude draft cover letters per role. Drafts surface in a port of the
single-user Apply UI for review/edit/mark-sent. Optional PR delivery pushes
artefacts back to the user's repo.

This directory is structured to be lifted into its own repo with
`git subtree split --prefix=ai-apply` (or `git filter-repo
--subdirectory-filter ai-apply`) once the initial implementation has settled.
Nothing inside `ai-apply/` imports from outside `ai-apply/`.

## Layout

```
ai-apply/
  main.py                 ← uvicorn entrypoint for local dev
  pyproject.toml          ← deps
  .env.example            ← required config
  api/                    ← FastAPI handlers
    app.py                ← create_app()
    auth.py               ← GitHub OAuth (full)
    google_auth.py        ← Google OIDC (full; needs GOOGLE_CLIENT_ID)
    email_auth.py         ← email/password stubs — wire to your IdP
    secrets.py            ← envelope-encrypted secret store (local + KV stub)
    settings_routes.py    ← API key, model choice, repo, criteria
    runs.py               ← POST/GET runs
    applications_routes.py← list/edit/mark-sent (port of /api/mark-sent)
    models_const.py       ← Anthropic model dropdown catalogue
  worker/                 ← background pipeline (FastAPI BackgroundTask for now)
    pipeline.py           ← execute_run(run_id) orchestrator
    scrape.py             ← programmatic adapter around vendored scrapers
    github_repo.py        ← list+fetch CV files via GitHub API
    extractors/extract.py ← md / pdf / docx → plaintext
    generate.py           ← Anthropic call + anonymity enforcement
    scraper/              ← vendored copy of /scraper/ (lift-and-shift)
    prompts/              ← copy of /scripts/prompts/process-job.md
    writing_guides/       ← en.md, ko.md
  db/                     ← SQLAlchemy 2.0 models + engine
  frontend/               ← static pages + JS port of website/apply.*
    index.html, settings.html, run.html
    login.html, signup.html
    static/apply.{css,js}, settings.js, run.js, shell.{css,js}
    static/login.js, signup.js
```

## Local quickstart

```bash
cd ai-apply
python -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env
# fill in SESSION_SECRET, SECRETS_MASTER_KEY, and GitHub OAuth IDs
# Generate a master key:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

python main.py
# → http://127.0.0.1:8000
```

### Sign-in providers

The login page (`/login.html`) offers three options:

1. **GitHub OAuth** — fully wired. Register at
   https://github.com/settings/developers; callback
   `http://localhost:8000/auth/github/callback`. Set `GITHUB_CLIENT_ID`
   + `GITHUB_CLIENT_SECRET` in `.env`.
2. **Google OAuth (OIDC)** — fully wired. Register at
   https://console.cloud.google.com/apis/credentials; redirect URI
   `http://localhost:8000/auth/google/callback`; scopes `openid email
   profile`. Set `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET`.
   Returns 501 if not configured (so the button surfaces a clear error
   rather than redirecting into a broken consent screen).
3. **Email/password** — UI is built; backend endpoints in
   `api/email_auth.py` are stubs returning 501. Wire them to your
   identity provider (e.g. Azure AD B2C / Entra External ID). They
   should look up or create a `User` row by email and set
   `request.session["user_id"]`.

After signing in:

1. **Settings** → paste your Anthropic API key, choose a model, set
   `repo_full_name` (e.g. `octocat/cv`) + `cv_dir`.
2. Add at least one **search criteria** row.
3. **Run** → start. Polls `/api/runs/{id}` until done.
4. **Applications** → review/edit drafts, mark sent.

## Model selection

`api/models_const.py` lists the Anthropic models surfaced in the Settings
dropdown. Default is **Sonnet 4.6**. Selection is per-user; the chosen
model ID is recorded on each `application` row as **internal metadata
only** — never written into `body_md`, the PR title/description, commit
messages, or anything employer-visible.

The system prompt (`worker/generate.py:ANONYMITY_CLAUSE`) tells the model
to write in the candidate's first-person voice and avoid meta-commentary
("as an AI", "as a language model"). It does **not** ban the words
"Claude" or "Anthropic" — devs applying to Anthropic, or to companies
that integrate Claude, will have those words appear legitimately. The
safety net is the human-in-the-loop review on the Applications page
before mark-sent.

## Tests

```bash
pip install -e '.[dev]'
pytest
```

## Production deployment (Azure)

The architecture maps cleanly to:

- **App Service (Linux)** — the FastAPI app behind uvicorn/gunicorn.
- **Azure Database for PostgreSQL Flexible Server** — set `DATABASE_URL`.
- **Key Vault** — replace the `LocalSecretStore` in `api/secrets.py` with an
  Azure Key Vault implementation; `anthropic_key_ref` and
  `github_token_ref` already store opaque references, not plaintext.
- **Container Apps Job** or a **Storage Queue + Function** — replace
  `BackgroundTasks` in `api/runs.py` with a queued task. The
  `execute_run(run_id)` function is deliberately self-contained (no
  FastAPI types, opens its own DB session) so the swap is mechanical.
- **Front Door / Static Web Apps** — only needed if you split the
  static frontend out; today it's served by the same FastAPI app.

See `infra/README.md` for placeholder Bicep notes.

## Risks (from the plan)

1. Scraper TOS — multi-tenant load is more visible than a single user.
   Throttle and consider per-user proxies before scaling.
2. CV extraction silently fails on scanned PDFs. The worker shows an error
   rather than feeding garbage to the LLM.
3. Cost runaway — `MAX_JOBS_PER_RUN` in `worker/pipeline.py` caps per-run
   generation count. Surface estimated token cost before kickoff in v2.
