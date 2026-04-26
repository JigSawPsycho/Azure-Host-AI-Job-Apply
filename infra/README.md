# Infra

Placeholder for Azure deployment templates. Not built yet — when you do build
them, the moving parts you'll need are:

- **App Service (Linux, Python 3.11+)** running:
  `gunicorn -k uvicorn.workers.UvicornWorker 'api.app:create_app()' --workers 2`
- **Azure Database for PostgreSQL Flexible Server**, exposed via
  `DATABASE_URL=postgresql+psycopg://…`
- **Key Vault** for per-user Anthropic keys + GitHub tokens. Replace
  `LocalSecretStore` in `api/secrets.py` with an Azure KV-backed one;
  the existing `anthropic_key_ref` / `github_token_ref` columns already
  hold opaque references.
- **Storage Account + Queue** (or **Container Apps Job**) for the
  worker. Today the worker runs as a FastAPI `BackgroundTasks` callable —
  fine for dev, single-process. Swap by enqueuing `(run_id,)` and having a
  worker process call `worker.pipeline.execute_run(run_id)` from the queue.
- **App Insights** for traces/logs.

The `execute_run` function is deliberately self-contained (no FastAPI
imports, opens its own `SessionLocal`) so moving it to a queued worker is
purely an ops change.

## Suggested Bicep modules

- `db.bicep` — Postgres flexible server + firewall rule for App Service VNet
- `app.bicep` — App Service plan + Linux web app + managed identity
- `kv.bicep` — Key Vault + access policy granting the web app's identity
  `get`/`set`/`delete` on secrets
- `storage.bicep` — Storage account + queue
- `main.bicep` — composes the above

Each module is a couple of dozen lines. Hold off on writing them until
the local-dev flow is exercised end-to-end with at least one test user.
