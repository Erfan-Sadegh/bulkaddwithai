param(
    [string]$StateRoot = (Join-Path $env:LOCALAPPDATA 'BulkAddWithAi-agent')
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null

$keys = @(
    'SENTRY_AUTH_TOKEN',
    'SENTRY_ORG',
    'SENTRY_PROJECTS',
    'CLARITY_API_TOKEN',
    'PRODUCTION_HEALTH_URL',
    'PRODUCTION_OBSERVABILITY_URL',
    'PRODUCTION_OBSERVABILITY_TOKEN',
    'GITHUB_TOKEN',
    'GITHUB_REPOSITORY'
)
$credentials = foreach ($key in $keys) {
    $value = Read-Host "$key (Enter means disabled)" -AsSecureString
    [PSCredential]::new($key, $value)
}
$target = Join-Path $StateRoot 'collector-secrets.clixml'
$credentials | Export-Clixml -LiteralPath $target
Write-Host "Collector settings saved with Windows user encryption: $target"
Write-Host 'These values can only be decrypted by this Windows user on this computer.'
