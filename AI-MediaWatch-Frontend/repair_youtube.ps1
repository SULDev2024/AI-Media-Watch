# Updates downloader dependencies only; does not start application services.
param([switch]$StopBackend)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$repairPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$repairUv = Join-Path $PSScriptRoot '.bootstrap\Scripts\uv.exe'
if (-not (Test-Path -LiteralPath $repairPython)) { throw 'AIMW Python environment is missing. Complete the project setup first.' }
if (-not (Test-Path -LiteralPath $repairUv)) {
    $repairUv = (Get-Command uv -ErrorAction Stop).Source
}
$repairBackendProcesses = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" | Where-Object {
    $_.ExecutablePath -and (
        $_.ExecutablePath -ieq $repairPython -or
        $_.ExecutablePath -ieq (Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe')
    )
})
if ($repairBackendProcesses.Count -gt 0) {
    if (-not $StopBackend) {
        throw 'The AIMW Python environment is in use. Stop the launcher with Ctrl+C, then run .\repair_youtube.ps1 -StopBackend to stop any remaining AIMW backend processes.'
    }
    foreach ($repairBackendProcess in $repairBackendProcesses) {
        Write-Host "Stopping AIMW Python process $($repairBackendProcess.ProcessId)..."
        Stop-Process -Id $repairBackendProcess.ProcessId -ErrorAction Stop
        Wait-Process -Id $repairBackendProcess.ProcessId -Timeout 15 -ErrorAction SilentlyContinue
    }
}
Write-Host 'Updating the YouTube downloader and its matching JavaScript solver...'
& $repairUv pip install --python $repairPython --upgrade --no-deps 'yt-dlp'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Share the terminal output above so the installation error can be diagnosed.' }
# Install the exact solver requirement declared by the installed yt-dlp release.
# Avoid upgrading unrelated compiled packages that Windows may have loaded.
$repairSolverRequirement = & $repairPython -c "from importlib.metadata import requires; print(next(r.split(';')[0].strip() for r in requires('yt-dlp') if r.lower().startswith('yt-dlp-ejs')))"
if ($LASTEXITCODE -ne 0 -or -not $repairSolverRequirement) { throw 'Could not determine the matching solver package. Share the terminal output above.' }
& $repairUv pip install --python $repairPython --no-deps $repairSolverRequirement.Trim()
if ($LASTEXITCODE -ne 0) { throw 'JavaScript solver installation failed. Share the terminal output above.' }
Write-Host 'Verifying the packages in the exact Python environment used by AIMW...'
& $repairPython -c "from importlib.metadata import version; import yt_dlp, yt_dlp_ejs; print('yt-dlp: ' + version('yt-dlp')); print('yt-dlp-ejs: ' + version('yt-dlp-ejs'))"
if ($LASTEXITCODE -ne 0) { throw 'Downloader verification failed. Share the terminal output above.' }
$repairNode = Get-Command node -ErrorAction SilentlyContinue
if (-not $repairNode) { throw 'Node.js is missing from PATH. Install Node.js 22 or newer, then reopen PowerShell.' }
& $repairNode.Source -e "if (Number(process.versions.node.split('.')[0]) < 22) { console.error('Node.js 22 or newer is required'); process.exit(1); } console.log('Node.js: ' + process.versions.node);"
if ($LASTEXITCODE -ne 0) { throw 'Node.js verification failed.' }
Write-Host 'Downloader dependencies OK.' -ForegroundColor Green
Write-Host 'Now run .\start_demo.ps1 and submit a new link through Analyze content.'
Write-Host 'This verifies setup only; YouTube may still reject restricted videos or requests.'
