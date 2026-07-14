param(
    [string]$StateRoot = (Join-Path $env:LOCALAPPDATA 'BulkAddWithAi-agent'),
    [ValidateSet(
        'SENTRY_AUTH_TOKEN', 'SENTRY_ORG', 'SENTRY_PROJECTS', 'CLARITY_API_TOKEN',
        'PRODUCTION_HEALTH_URL', 'PRODUCTION_OBSERVABILITY_URL',
        'PRODUCTION_OBSERVABILITY_TOKEN', 'GITHUB_TOKEN', 'GITHUB_REPOSITORY'
    )]
    [string]$Only,
    [string]$ValueFromEnvironment
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
$target = Join-Path $StateRoot 'collector-secrets.clixml'
$saved = [ordered]@{}
if (Test-Path -LiteralPath $target) {
    foreach ($credential in @(Import-Clixml -LiteralPath $target)) {
        $saved[$credential.UserName] = $credential
    }
}

$selectedKeys = if ($Only) { @($Only) } else { $keys }
foreach ($key in $selectedKeys) {
    if ($ValueFromEnvironment) {
        $plainValue = [Environment]::GetEnvironmentVariable($ValueFromEnvironment, 'Process')
        if (-not $plainValue) { throw "Environment variable $ValueFromEnvironment is empty." }
        $value = ConvertTo-SecureString $plainValue -AsPlainText -Force
    }
    else {
        $value = Read-Host "$key (Enter means disabled)" -AsSecureString
    }
    $saved[$key] = [PSCredential]::new($key, $value)
}

$credentials = foreach ($key in $keys) {
    if ($saved.Contains($key)) { $saved[$key] }
}
$credentials | Export-Clixml -LiteralPath $target
Write-Host "Collector settings saved with Windows user encryption: $target"
Write-Host 'These values can only be decrypted by this Windows user on this computer.'
