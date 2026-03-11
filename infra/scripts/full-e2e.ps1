param(
    [string]$EnvFile = "tmp-integration/.env.e2e",
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"

function Write-Info([string]$Message) {
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "[OK]   $Message" -ForegroundColor Green
}

function Read-EnvMap([string]$Path) {
    if (!(Test-Path $Path)) {
        throw "Env file not found: $Path"
    }
    $map = @{}
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line.Length -eq 0 -or $line.StartsWith("#")) { return }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }
        $key = $line.Substring(0, $idx).Trim()
        $val = $line.Substring($idx + 1).Trim()
        $map[$key] = $val
    }
    return $map
}

function Wait-HttpUp([string]$Url, [string]$Contains, [int]$Retries = 60, [int]$SleepSec = 2) {
    for ($i = 1; $i -le $Retries; $i++) {
        try {
            $resp = curl.exe -sS $Url
            if ($resp -and $resp.Contains($Contains)) {
                return $true
            }
        } catch {
        }
        Start-Sleep -Seconds $SleepSec
    }
    return $false
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$envPath = Resolve-Path (Join-Path $repoRoot $EnvFile)
$envMap = Read-EnvMap $envPath

$backendPort = if ($envMap.ContainsKey("BACKEND_PORT")) { $envMap["BACKEND_PORT"] } else { "8080" }
$enginePort = if ($envMap.ContainsKey("ENGINE_PORT")) { $envMap["ENGINE_PORT"] } else { "9000" }

Push-Location $repoRoot
try {
    Write-Info "Starting compose stack with env: $envPath"
    docker compose --env-file $envPath --profile local up -d --build | Out-Host

    if (!(Wait-HttpUp "http://localhost:$backendPort/actuator/health" '"status":"UP"')) {
        throw "Backend health check did not become UP."
    }
    Write-Ok "Backend is healthy."

    if (!(Wait-HttpUp "http://localhost:$enginePort/health" '"status":"ok"')) {
        throw "Engine health check did not become OK."
    }
    Write-Ok "Engine is healthy."

    $probePath = Join-Path $PSScriptRoot "e2e_full_probe.py"
    if (!(Test-Path $probePath)) {
        throw "Probe script not found: $probePath"
    }
    $tmpDir = Join-Path $repoRoot "tmp-integration"

    Write-Info "Running full E2E probe..."
    python $probePath --env-file $envPath --tmp-dir $tmpDir
    if ($LASTEXITCODE -ne 0) {
        throw "E2E probe failed with exit code $LASTEXITCODE"
    }
    Write-Ok "Full E2E probe passed."
} finally {
    if (!$KeepRunning.IsPresent) {
        Write-Info "Stopping stack..."
        docker compose --env-file $envPath --profile local down | Out-Host
    }
    Pop-Location
}
