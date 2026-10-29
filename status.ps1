$ErrorActionPreference = 'Stop'
$taskKey = Join-Path $PSScriptRoot 'work-pc-to-codex-home_ed25519.txt'
$taskCommand = 'pct exec 103 -- runuser -u codex -- /home/codex/workspace/cripto_staff/.venv/bin/python /home/codex/workspace/cripto_staff/agent.py status'
$taskOutput = & ssh -T -i $taskKey -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=5 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 root@192.168.0.2 $taskCommand
if ($LASTEXITCODE -ne 0) { throw 'Server status request failed' }
$taskStatus = ($taskOutput -join "`n") | ConvertFrom-Json
if (-not $taskStatus.heartbeat_ms) { $taskStatus; exit 1 }
$taskAge = [math]::Round(([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - $taskStatus.heartbeat_ms) / 1000)
[pscustomobject]@{
    Mode = $taskStatus.mode
    HeartbeatAgeSeconds = $taskAge
    EquityUSDT = $taskStatus.equity_usdt
    PaperPnLUSDT = $taskStatus.pnl_usdt
    Position = $(if ($taskStatus.portfolio.position) { $taskStatus.portfolio.position.symbol } else { 'none' })
    LastError = $taskStatus.last_error
} | Format-List
if ($taskAge -gt 120) { Write-Warning 'Heartbeat is stale: the service may be stopped or unable to fetch prices.' }
