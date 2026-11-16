# Starts only missing local services; never kills unrelated processes.
$ErrorActionPreference = "Stop"
$demoRoot = $PSScriptRoot
$agentRoot = Split-Path -Parent $demoRoot
Set-Location -LiteralPath $demoRoot
$demoPython = Join-Path $demoRoot '.venv\Scripts\python.exe'
$agentPython = Join-Path $agentRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $demoPython)) { throw 'Run the Python setup in CONNECT_TO_LOCAL_AGENT.md first.' }
if (-not (Test-Path -LiteralPath (Join-Path $demoRoot '.env'))) { throw 'Missing .env; see CONNECT_TO_LOCAL_AGENT.md.' }
$viteScript = Join-Path $demoRoot 'web\node_modules\vite\bin\vite.js'
if (-not (Test-Path -LiteralPath $viteScript)) { throw 'Run npm install in web first.' }
$started = @()
function Test-Service([string]$Url) {
    try { return (Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { return $false }
}
function Wait-Service([string]$Url, $Process) {
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        if (Test-Service $Url) { Write-Host "Ready: $Url" -ForegroundColor Green; return }
        if ($Process.HasExited) { throw "Service exited. Check the *.log files in $demoRoot." }
        if ($attempt % 5 -eq 0) { Write-Host "Waiting for $Url (backend model loading can take several minutes)..." }
        Start-Sleep -Seconds 1
    }
    throw "Service did not become ready: $Url"
}
try {
    Write-Host 'Checking Ollama and local services. Keep this terminal open.'
    if (-not (Test-Service 'http://127.0.0.1:11434/api/version')) { throw 'Ollama is not reachable. Start Ollama first.' }
    if (-not (Test-Service 'http://127.0.0.1:8002/health')) {
        Write-Host 'Starting Local Agent on port 8002...'
        $agent = Start-Process -FilePath $agentPython -ArgumentList @('-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8002') -WorkingDirectory $agentRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $demoRoot 'local-agent.stdout.log') -RedirectStandardError (Join-Path $demoRoot 'local-agent.stderr.log')
        $started += $agent
        Wait-Service 'http://127.0.0.1:8002/health' $agent
    }
    if (-not (Test-Service 'http://127.0.0.1:8003/health')) {
        Write-Host 'Starting AIMW API on port 8003...'
        $api = Start-Process -FilePath $demoPython -ArgumentList 'start_api.py' -WorkingDirectory $demoRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $demoRoot 'api.stdout.log') -RedirectStandardError (Join-Path $demoRoot 'api.stderr.log')
        $started += $api
        Wait-Service 'http://127.0.0.1:8003/health/ready' $api
    }
    if (-not (Test-Service 'http://127.0.0.1:5174')) {
        Write-Host 'Starting frontend on port 5174...'
        $web = Start-Process -FilePath (Get-Command node.exe).Source -ArgumentList @('"' + $viteScript + '"', '--host', '127.0.0.1', '--port', '5174', '--strictPort') -WorkingDirectory (Join-Path $demoRoot 'web') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $demoRoot 'web.stdout.log') -RedirectStandardError (Join-Path $demoRoot 'web.stderr.log')
        $started += $web
        Wait-Service 'http://127.0.0.1:5174' $web
    }
    Write-Host 'Dashboard: http://127.0.0.1:5174' -ForegroundColor Green
    Write-Host 'Login: admin@aimw.local / aimw-demo-2026 (configured in .env)'
    Write-Host 'Keep this terminal open. Ctrl+C stops only services started by this launcher.'
    while ($true) { Start-Sleep -Seconds 1 }
} finally {
    foreach ($service in $started) {
        if (-not $service.HasExited) { Stop-Process -Id $service.Id -ErrorAction SilentlyContinue }
    }
}
