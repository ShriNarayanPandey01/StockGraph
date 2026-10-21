<#
.SYNOPSIS
    Spawns an interactive OpenCode CLI session in a separate visible terminal window and waits until completion.
.PARAMETER Model
    The model identifier in OpenCode format (e.g. opencode/deepseek-v4.1-flash-free).
.PARAMETER Prompt
    The initial prompt to pass to opencode.
#>
param(
    [string]$Model = "opencode/deepseek-v4.1-flash-free",
    [string]$Prompt = ""
)

$ErrorActionPreference = "Stop"

# Verify opencode is installed
$opencodeCmd = Get-Command opencode -ErrorAction SilentlyContinue
if (-not $opencodeCmd) {
    Write-Error "Error: 'opencode' command was not found in PATH. Please install opencode before running this skill."
    exit 1
}

$WorkDir = (Get-Location).Path
$tempDir = [System.IO.Path]::GetTempPath()
$guid = [System.Guid]::NewGuid().ToString("N")
$runnerScript = Join-Path $tempDir ("opencode_runner_" + $guid + ".ps1")
$sentinelFile = Join-Path $tempDir ("opencode_sentinel_" + $guid + ".done")
$pidFile = Join-Path $tempDir ("opencode_pid_" + $guid + ".pid")

# Clean sentinel and pid files if exist
if (Test-Path -LiteralPath $sentinelFile) {
    Remove-Item -LiteralPath $sentinelFile -Force
}
if (Test-Path -LiteralPath $pidFile) {
    Remove-Item -LiteralPath $pidFile -Force
}

# Build runner script executed inside the visible window
$escapedPrompt = $Prompt.Replace("'", "''")
$runnerContent = @"
try {
    `$PID | Set-Content -LiteralPath '$pidFile' -Force
    `$host.UI.RawUI.WindowTitle = "OpenCode Interactive Session ($Model)"
    Set-Location -LiteralPath '$WorkDir'
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host " Starting OpenCode Interactive Session" -ForegroundColor Cyan
    Write-Host " Model: $Model" -ForegroundColor Green
    Write-Host " Directory: $WorkDir" -ForegroundColor DarkGray
    Write-Host " Type /exit or close this window when finished." -ForegroundColor Yellow
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""

    `$p = '$escapedPrompt'
    if (`$p.Trim().Length -gt 0) {
        opencode -m '$Model' --prompt `$p
    } else {
        opencode -m '$Model'
    }

    if (`$LASTEXITCODE -and `$LASTEXITCODE -ne 0) {
        Write-Host "opencode exited with code `$LASTEXITCODE" -ForegroundColor Red
        Write-Host "Press Enter to close this window..." -ForegroundColor Red
        Read-Host
    }
}
catch {
    Write-Error `$_.Exception.Message
    Write-Host "Press Enter to close this window..." -ForegroundColor Red
    Read-Host
}
finally {
    New-Item -Path '$sentinelFile' -ItemType File -Force | Out-Null
}
"@

Set-Content -Path $runnerScript -Value $runnerContent -Encoding utf8

try {
    Write-Host "Spawning visible OpenCode terminal window..." -ForegroundColor Cyan

    # 'cmd.exe /c start' forces Windows to allocate a brand-new top-level visible console window (CREATE_NEW_CONSOLE)
    # This guarantees a visible window even when invoked from headless subshells or within Warp Terminal.
    cmd.exe /c start "OpenCode Interactive" powershell.exe -ExecutionPolicy Bypass -File "$runnerScript"

    # Wait for the session to finish (signaled via sentinel file or process exit)
    $runnerPid = $null
    while (-not (Test-Path -LiteralPath $sentinelFile)) {
        if (-not $runnerPid -and (Test-Path -LiteralPath $pidFile)) {
            try {
                $pidContent = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue
                if ($pidContent -match '^\d+$') {
                    $runnerPid = [int]$pidContent
                }
            } catch {}
        }
        if ($runnerPid) {
            $proc = Get-Process -Id $runnerPid -ErrorAction SilentlyContinue
            if (-not $proc) {
                # Process exited (e.g. user closed window with X button)
                break
            }
        }
        Start-Sleep -Milliseconds 500
    }
}
finally {
    if (Test-Path -LiteralPath $runnerScript) {
        Remove-Item -LiteralPath $runnerScript -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $sentinelFile) {
        Remove-Item -LiteralPath $sentinelFile -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $pidFile) {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "OpenCode interactive session completed and closed."
