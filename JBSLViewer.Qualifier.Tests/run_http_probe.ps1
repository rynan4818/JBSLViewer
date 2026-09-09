param([int]$WebPort = 18380, [int]$ScorePort = 18381)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$python = Join-Path $workspace 'mock_servers/score_manager/.venv/Scripts/python.exe'
$executable = Join-Path $PSScriptRoot 'bin/Release/JBSLViewer.Qualifier.Tests.exe'
$runDirectory = Join-Path $PSScriptRoot ('artifacts/http-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
$settings = @{
    JBSL_MOCK_OFFLINE_DIR = (Join-Path $workspace 'mock_servers/jbsl_web_proxy/fixtures/upstream')
    JBSL_MOCK_UPSTREAM = "http://127.0.0.1:$WebPort"
    JBSL_MOCK_ALLOW_HTTP_LOOPBACK = 'true'
    JBSL_MOCK_RATE_LIMIT = 'false'
    JBSL_MOCK_DB = (Join-Path $runDirectory 'score.sqlite3')
    JBSL_MOCK_REPLAY_DIR = (Join-Path $runDirectory 'replays')
}
$previous = @{}
$started = @()
try {
    foreach ($name in $settings.Keys) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process'); [Environment]::SetEnvironmentVariable($name, $settings[$name], 'Process') }
    $started += Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'mock_servers.jbsl_web_proxy.jbsl_web_proxy_server:create_app', '--factory', '--host', '127.0.0.1', '--port', "$WebPort") -WorkingDirectory $workspace -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runDirectory 'web.out.log') -RedirectStandardError (Join-Path $runDirectory 'web.err.log')
    $started += Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'mock_servers.score_manager.score_manager_server:create_app', '--factory', '--host', '127.0.0.1', '--port', "$ScorePort") -WorkingDirectory $workspace -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runDirectory 'score.out.log') -RedirectStandardError (Join-Path $runDirectory 'score.err.log')
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($started.Where({ $_.HasExited }).Count -gt 0) { throw 'A mock process exited during startup. See artifacts logs.' }
        try { Invoke-WebRequest "http://127.0.0.1:$WebPort/__mock__/state" -UseBasicParsing -TimeoutSec 1 | Out-Null; Invoke-WebRequest "http://127.0.0.1:$ScorePort/healthz" -UseBasicParsing -TimeoutSec 1 | Out-Null; $ready = $true; break } catch { Start-Sleep -Milliseconds 200 }
    }
    if (!$ready) { throw 'Mock startup timed out.' }
    & $executable integration "http://127.0.0.1:$ScorePort" "http://127.0.0.1:$WebPort" 2>&1 | Tee-Object -FilePath (Join-Path $runDirectory 'probe.log')
    if ($LASTEXITCODE -ne 0) { throw "HTTP probe failed: $LASTEXITCODE" }
    Write-Output "HTTP artifacts: $runDirectory"
} finally {
    foreach ($process in $started) { if (!$process.HasExited) { Stop-Process -Id $process.Id -ErrorAction SilentlyContinue } }
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}
