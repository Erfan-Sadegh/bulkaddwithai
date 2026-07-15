param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = 'BulkAddWithAI 3-Hour Agent',
    [string]$At = '03:17',
    [ValidateRange(1, 24)]
    [int]$EveryHours = 3,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$legacyTaskName = 'BulkAddWithAI Nightly Agent'
if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $legacyTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Scheduled task removed: $TaskName"
    exit 0
}

$runner = Join-Path $RepoRoot 'automation\run-nightly.ps1'
if (-not (Test-Path -LiteralPath $runner)) { throw "Runner not found: $runner" }
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    Write-Warning 'codex is not available on PATH. Report collection works, but fixes cannot be created.'
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Warning 'GitHub CLI (gh) is not available on PATH. Configure a fine-grained GITHUB_TOKEN with configure-secrets.ps1 before PR publishing.'
}

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -RepoRoot `"$RepoRoot`" -Scheduled" `
    -WorkingDirectory $RepoRoot
$atTime = [datetime]::ParseExact($At, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At $atTime `
    -RepetitionInterval (New-TimeSpan -Hours $EveryHours)
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries:$false `
    -AllowStartIfOnBatteries:$false
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
if ($TaskName -ne $legacyTaskName) {
    Unregister-ScheduledTask -TaskName $legacyTaskName -Confirm:$false -ErrorAction SilentlyContinue
}

$stateRoot = Join-Path $env:LOCALAPPDATA 'BulkAddWithAi-agent'
$dashboard = Join-Path $stateRoot 'dashboard\index.html'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'BulkAddWithAI Agent Dashboard.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $dashboard
$shortcut.WorkingDirectory = $stateRoot
$shortcut.Save()

Write-Host "Scheduled task installed every $EveryHours hours, anchored at $At."
Write-Host "Dashboard shortcut: $shortcutPath"
Write-Host "Every run may diagnose and prove issues with tests; product fixes always require explicit human instruction."
