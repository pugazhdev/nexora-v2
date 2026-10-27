# Stops the servers started by .\start.ps1
$ApiPort = 8015
$WebPort = 5173
$Root = $PSScriptRoot
$PidFile = Join-Path $Root '.pids.json'

$pids = @()
if (Test-Path $PidFile) {
    $saved = Get-Content $PidFile -Raw | ConvertFrom-Json
    $pids += $saved.api, $saved.web, $saved.tunnel | Where-Object { $_ }
}
# Also catch servers started some other way (e.g. by hand), but only ones running from this repo.
foreach ($port in $ApiPort, $WebPort) {
    foreach ($conn in Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)").CommandLine
        $exe = (Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue).Path
        # The venv launcher hands off to the base Python, so the API is recognised by its uvicorn app name.
        if ("$cmd $exe" -like "*$Root*" -or "$cmd" -like '*uvicorn app.main:app_factory*') { $pids += $conn.OwningProcess }
    }
}

$stopped = 0
foreach ($id in $pids | Sort-Object -Unique) {
    if (Get-Process -Id $id -ErrorAction SilentlyContinue) {
        taskkill /PID $id /T /F *> $null   # /T also ends the uvicorn reloader worker and Vite's node child
        $stopped++
    }
}
Remove-Item $PidFile -ErrorAction SilentlyContinue
if ($stopped) { Write-Host "Stopped $stopped process tree(s)." } else { Write-Host 'Nothing was running.' }
