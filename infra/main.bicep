// Azure infra for ai-apply.
// Deploy:
//   az group create -n ai-apply-rg -l australiaeast
//   az deployment group create -g ai-apply-rg -f infra/main.bicep \
//       -p namePrefix=aiapply pgAdminLogin=aiapply \
//          pgAdminPassword='<strong-password>' \
//          sessionSecret='<token>' secretsMasterKey='<fernet>'

@description('Prefix for resource names. Lowercase, 3-15 chars.')
param namePrefix string

@description('Azure region.')
param location string = resourceGroup().location

@description('Postgres admin login.')
param pgAdminLogin string

@secure()
@description('Postgres admin password.')
param pgAdminPassword string

@secure()
@description('FastAPI session secret (token_urlsafe(32)).')
param sessionSecret string

@secure()
@description('Fernet master key for legacy local secret store. Unused once SECRETS_BACKEND=azure-key-vault but kept for migration.')
param secretsMasterKey string

@description('App Service plan SKU.')
param appServiceSku string = 'B1'

@description('Postgres SKU name.')
param pgSkuName string = 'Standard_B1ms'

@description('Postgres tier.')
param pgTier string = 'Burstable'

var unique = uniqueString(resourceGroup().id)
var webAppName = '${namePrefix}-web-${unique}'
var planName = '${namePrefix}-plan'
var pgName = '${namePrefix}-pg-${unique}'
var pgDbName = 'aiapply'
var kvName = take('${namePrefix}kv${unique}', 24)
var laName = '${namePrefix}-la'
var aiName = '${namePrefix}-ai'

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: laName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: aiName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  sku: { name: appServiceSku }
  kind: 'linux'
  properties: { reserved: true }
}

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2023-12-01-preview' = {
  name: pgName
  location: location
  sku: { name: pgSkuName, tier: pgTier }
  properties: {
    administratorLogin: pgAdminLogin
    administratorLoginPassword: pgAdminPassword
    version: '16'
    storage: { storageSizeGB: 32 }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
  }
}

resource pgDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-12-01-preview' = {
  parent: pg
  name: pgDbName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// Firewall: allow Azure services. Tighten with VNet integration in v2.
resource pgFwAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-12-01-preview' = {
  parent: pg
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

resource web 'Microsoft.Web/sites@2023-12-01' = {
  name: webAppName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appCommandLine: 'bash startup.sh'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      http20Enabled: true
      appSettings: [
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'WEBSITES_PORT', value: '8000' }
        { name: 'PORT', value: '8000' }
        { name: 'WEB_CONCURRENCY', value: '2' }
        { name: 'SESSION_SECRET', value: sessionSecret }
        { name: 'SECRETS_MASTER_KEY', value: secretsMasterKey }
        { name: 'SECRETS_BACKEND', value: 'azure-key-vault' }
        { name: 'AZURE_KEY_VAULT_URL', value: kv.properties.vaultUri }
        { name: 'SESSION_HTTPS_ONLY', value: '1' }
        { name: 'TRUST_PROXY_HEADERS', value: '1' }
        {
          name: 'DATABASE_URL'
          value: 'postgresql+psycopg://${pgAdminLogin}:${pgAdminPassword}@${pg.properties.fullyQualifiedDomainName}:5432/${pgDbName}?sslmode=require'
        }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        // OAuth — set after deploy when callback URL is known:
        // GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_REDIRECT_URI
        // GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
        // MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, MS_REDIRECT_URI
      ]
    }
  }
  dependsOn: [ pgFwAzure, pgDb ]
}

// Grant Web App's managed identity access to Key Vault secrets.
// Role: Key Vault Secrets Officer = get/list/set/delete secrets.
var kvSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
resource webKvAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, web.id, kvSecretsOfficerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsOfficerRoleId)
    principalId: web.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output webAppHostname string = web.properties.defaultHostName
output keyVaultUri string = kv.properties.vaultUri
output postgresFqdn string = pg.properties.fullyQualifiedDomainName
output appInsightsConnectionString string = appInsights.properties.ConnectionString
