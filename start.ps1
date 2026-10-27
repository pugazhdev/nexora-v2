# Starts the API, the web app and (unless -NoTunnel) a Cloudflare Tunnel, each in its own window.
# The web app on $WebPort already proxies /api to the API, so the tunnel exposes that single port.
# Stop everything with .\stop.ps1
param(
    [switch]$NoTunnel,
    [string]$PublicHost = 'nexora.softsuaveai.space',
    [string]$TunnelName = 'nexora'
)
$ErrorActionPreference = 'Stop'
$ApiPort = 8015
$WebPort = 5173
$Root = $PSScriptRoot
$PidFile = Join-Path $Root '.pids.json'
$VenvPython = Join-Path $Root 'backend\.venv\Scripts\python.exe'

if (Test-Path $PidFile) { throw 'Already running (found .pids.json). Run .\stop.ps1 first.' }
foreach ($port in $ApiPort, $WebPort) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Run .\stop.ps1 or free the port."
    }
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js 20+ is not on PATH.' }

# First-run setup. 'py' is preferred because 'python' may be the Microsoft Store stub.
if (-not (Test-Path $VenvPython)) {
    Write-Host 'Creating Python virtual environment...'
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv "$Root\backend\.venv" } else { python -m venv "$Root\backend\.venv" }
    if ($LASTEXITCODE) { throw 'Could not create the virtual environment.' }
}
if (-not (Test-Path "$Root\backend\.venv\.deps_installed")) {
    Write-Host 'Installing backend dependencies...'
    & $VenvPython -m pip install -q --disable-pip-version-check -r "$Root\backend\requirements.txt"
    if ($LASTEXITCODE) { throw 'Backend dependency install failed.' }
    Set-Content "$Root\backend\.venv\.deps_installed" 'ok'
}
if (-not (Test-Path "$Root\backend\.env")) { throw 'backend\.env is missing. Copy backend\.env.example and fill it in.' }

if (Test-Path "$Root\backend\alembic.ini") {
Write-Host 'Applying database migrations...'
Push-Location "$Root\backend"
try { & $VenvPython -m alembic upgrade head; if ($LASTEXITCODE) { throw 'Database migration failed. Check DATABASE_URL.' } }
finally { Pop-Location }
}

if (-not (Test-Path "$Root\frontend\node_modules")) {
    Write-Host 'Installing frontend dependencies...'
    Push-Location "$Root\frontend"
    try { npm install; if ($LASTEXITCODE) { throw 'npm install failed.' } }
    finally { Pop-Location }
}
# A stale Vite pre-bundle cache can cause "Invalid hook call".
Remove-Item "$Root\frontend\node_modules\.vite\deps" -Recurse -Force -ErrorAction SilentlyContinue

$api = Start-Process $VenvPython -WorkingDirectory "$Root\backend" -PassThru `
    -ArgumentList '-m', 'uvicorn', 'app.main:app_factory', '--factory', '--reload', '--port', $ApiPort
$env:VITE_API_PROXY = "http://localhost:$ApiPort"
$env:VITE_ALLOWED_HOSTS = $PublicHost   # Vite rejects unknown Host headers, so allow the public domain
$web = Start-Process 'npm.cmd' -WorkingDirectory "$Root\frontend" -PassThru `
    -ArgumentList 'run', 'dev', '--', '--port', $WebPort, '--strictPort'
$pids = @{ api = $api.Id; web = $web.Id }

if (-not $NoTunnel) {
    if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) { throw 'cloudflared is not on PATH. Install it or use -NoTunnel.' }
    # The login cert for the softsuaveai.space zone, falling back to the default one.
    $cert = Join-Path $HOME '.cloudflared\cert-softsuaveai.space.pem'
    if (-not (Test-Path $cert)) { $cert = Join-Path $HOME '.cloudflared\cert.pem' }
    $found = cloudflared tunnel --origincert $cert list --output json | ConvertFrom-Json | Where-Object name -eq $TunnelName
    if (-not $found) {
        Write-Host "Creating Cloudflare tunnel '$TunnelName'..."
        cloudflared tunnel --origincert $cert create $TunnelName
        if ($LASTEXITCODE) { throw "Could not create tunnel '$TunnelName'." }
        $found = cloudflared tunnel --origincert $cert list --output json | ConvertFrom-Json | Where-Object name -eq $TunnelName
    }
    $creds = Join-Path $HOME ".cloudflared\$($found.id).json"
    if (-not (Test-Path $creds)) { throw "Tunnel '$TunnelName' exists but its credentials file $creds is missing on this machine." }
    # Points the DNS name at this tunnel; --overwrite-dns makes it safe to run on every start.
    cloudflared tunnel --origincert $cert route dns --overwrite-dns $TunnelName $PublicHost
    if ($LASTEXITCODE) { throw "Could not route $PublicHost to tunnel '$TunnelName'." }
    # A dedicated config, so the default ~/.cloudflared/config.yml of other projects is never picked up.
    $cfg = Join-Path $HOME ".cloudflared\$TunnelName.yml"
    @"
tunnel: $($found.id)
credentials-file: $creds
ingress:
  - hostname: $PublicHost
    service: http://localhost:$WebPort
  - service: http_status:404
"@ | Set-Content -Encoding ascii $cfg
    $tunnel = Start-Process 'cloudflared' -PassThru -ArgumentList 'tunnel', '--config', $cfg, '--no-autoupdate', 'run'
    $pids.tunnel = $tunnel.Id
}

$pids | ConvertTo-Json | Set-Content $PidFile
Write-Host "API: http://localhost:$ApiPort   Web: http://localhost:$WebPort"
if (-not $NoTunnel) { Write-Host "Public: https://$PublicHost" }
Write-Host 'Stop with .\stop.ps1'
Start-Sleep -Seconds 5
Start-Process "http://localhost:$WebPort"
