param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$ReportOnly,
    [switch]$Scheduled
)

$ErrorActionPreference = 'Stop'
$python = Join-Path $RepoRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment was not found at $python. Run backend setup first."
}

$stateRoot = Join-Path $env:LOCALAPPDATA 'BulkAddWithAi-agent'
$secretFile = Join-Path $stateRoot 'collector-secrets.clixml'
if (Test-Path -LiteralPath $secretFile) {
    $credentials = Import-Clixml -LiteralPath $secretFile
    foreach ($credential in $credentials) {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential.Password)
        try {
            $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
            if ($value) { [Environment]::SetEnvironmentVariable($credential.UserName, $value, 'Process') }
        }
        finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
    }
}

$arguments = @('-m', 'automation.runner', '--repo', $RepoRoot, '--state-dir', $stateRoot)
if ($ReportOnly) { $arguments += '--report-only' }
if ($Scheduled) { $arguments += '--scheduled' }

Push-Location $RepoRoot
try {
    & $python @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
