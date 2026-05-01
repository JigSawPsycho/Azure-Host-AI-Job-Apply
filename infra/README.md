# Azure deployment

`main.bicep` provisions:

- App Service Plan (Linux) + Web App (Python 3.11) w/ system-assigned managed identity
- PostgreSQL Flexible Server + `aiapply` database
- Key Vault (RBAC mode) + role assignment giving the Web App `Key Vault Secrets Officer`
- Log Analytics workspace + Application Insights
- Sets all required app settings (`SESSION_SECRET`, `DATABASE_URL`,
  `SECRETS_BACKEND=azure-key-vault`, `AZURE_KEY_VAULT_URL`,
  `APPLICATIONINSIGHTS_CONNECTION_STRING`, `SESSION_HTTPS_ONLY=1`,
  `TRUST_PROXY_HEADERS=1`)

## Prereqs

- Azure CLI logged in: `az login`
- Subscription selected: `az account set -s <sub-id>`

## Deploy infra

```bash
az group create -n ai-apply-rg -l australiaeast

SESSION_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
SECRETS_MASTER_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
PG_PASS='<choose-strong>'   # 8-128 chars, 3 of 4 categories

az deployment group create \
  -g ai-apply-rg \
  -f infra/main.bicep \
  -p namePrefix=aiapply \
     pgAdminLogin=aiapply \
     pgAdminPassword="$PG_PASS" \
     sessionSecret="$SESSION_SECRET" \
     secretsMasterKey="$SECRETS_MASTER_KEY"
```

Outputs include `webAppHostname` — that's your prod URL.

## Configure OAuth (after first deploy)

The OAuth callback URLs must match the deployed hostname. For each
provider, register/update an app and set the corresponding env vars on
the Web App:

```bash
HOST="https://<webAppHostname>"
az webapp config appsettings set -g ai-apply-rg -n <web-app-name> --settings \
  GITHUB_CLIENT_ID=...        GITHUB_CLIENT_SECRET=...        GITHUB_REDIRECT_URI=$HOST/auth/github/callback \
  GOOGLE_CLIENT_ID=...        GOOGLE_CLIENT_SECRET=...        GOOGLE_REDIRECT_URI=$HOST/auth/google/callback \
  MS_TENANT_ID=...  MS_CLIENT_ID=...  MS_CLIENT_SECRET=...    MS_REDIRECT_URI=$HOST/auth/ms/callback
```

Update the same redirect URIs in:

- GitHub: <https://github.com/settings/developers>
- Google: <https://console.cloud.google.com/apis/credentials>
- Entra: App registration → Authentication → Web platform redirect URIs

## CI deployment

`.github/workflows/azure-deploy.yml` deploys on push to `main`. Required
GitHub secrets / vars:

- `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` — federated
  credential on a service principal (OIDC, no client secret).
- repo variable `AZURE_WEBAPP_NAME` — the bicep output `webAppHostname`'s
  prefix (i.e. the resource name, not the FQDN).

Setup federated identity once:

```bash
az ad sp create-for-rbac --name "ai-apply-deploy" \
  --role contributor --scopes /subscriptions/<sub>/resourceGroups/ai-apply-rg
# Then add a federated credential pointing at this repo's main branch.
```

## DB schema

`api/app.py:create_app()` calls `init_db()` on boot, which runs
`Base.metadata.create_all`. First deploy creates tables automatically.
For schema changes post-launch, add Alembic.

## Worker

Background generation runs in-process via FastAPI `BackgroundTasks`.
For multi-worker scale, replace with a queue-driven Container Apps Job
(see `worker.pipeline.execute_run` — already self-contained).

## Verify

```bash
curl https://<webAppHostname>/healthz   # → {"ok":true}
```

Sign in via /login.html, complete settings, kick a run.
