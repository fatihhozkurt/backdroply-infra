param(
    [string]$EnvFile = "tmp-integration/.env.e2e",
    [switch]$RunBenchmark,
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

function Compose-Args([hashtable]$EnvMap, [string]$RepoRoot) {
    $args = @("-f", (Join-Path $RepoRoot "docker-compose.yml"))
    $enableGpu = $false
    if ($EnvMap.ContainsKey("ENGINE_ENABLE_GPU")) {
        $enableGpu = $EnvMap["ENGINE_ENABLE_GPU"].Trim().ToLowerInvariant() -eq "true"
    }
    if ($enableGpu) {
        $gpuFile = Join-Path $RepoRoot "docker-compose.gpu.yml"
        if (Test-Path $gpuFile) {
            $args += @("-f", $gpuFile)
            Write-Info "GPU compose override enabled: $gpuFile"
        } else {
            Write-Info "ENGINE_ENABLE_GPU=true but docker-compose.gpu.yml not found."
        }
    }
    return $args
}

function Wait-HttpUp([string]$Url, [string]$Contains, [int]$Retries = 60, [int]$SleepSec = 2) {
    for ($i = 1; $i -le $Retries; $i++) {
        try {
            $resp = curl.exe -sS --connect-timeout 5 --max-time 10 $Url
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
$composeArgs = Compose-Args $envMap $repoRoot

$backendPort = if ($envMap.ContainsKey("BACKEND_PORT")) { $envMap["BACKEND_PORT"] } else { "8080" }
$enginePort = if ($envMap.ContainsKey("ENGINE_PORT")) { $envMap["ENGINE_PORT"] } else { "9000" }
$tmpDir = Join-Path $repoRoot "tmp-integration"
$reportDir = Join-Path $tmpDir "reports"
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null

Push-Location $repoRoot
try {
    Write-Info "Starting compose stack with env: $envPath"
    docker compose @composeArgs --env-file $envPath --profile local up -d --build | Out-Host

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
    Write-Info "Running full E2E probe..."
    python $probePath --env-file $envPath --tmp-dir $tmpDir
    if ($LASTEXITCODE -ne 0) {
        throw "E2E probe failed with exit code $LASTEXITCODE"
    }
    Write-Ok "Full E2E probe passed."

    if ($RunBenchmark.IsPresent) {
        $benchmarkPath = Join-Path $PSScriptRoot "benchmark_probe.py"
        if (!(Test-Path $benchmarkPath)) {
            throw "benchmark probe script not found: $benchmarkPath"
        }
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $reportPath = Join-Path $reportDir "benchmark-$stamp.json"
        Write-Info "Running benchmark + go/no-go probe..."
        python $benchmarkPath --env-file $envPath --tmp-dir $tmpDir --output-json $reportPath
        if ($LASTEXITCODE -eq 2) {
            throw "Benchmark completed with NO_GO result. Report: $reportPath"
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Benchmark probe failed with exit code $LASTEXITCODE"
        }
        Write-Ok "Benchmark GO. Report: $reportPath"
    }
} finally {
    if (!$KeepRunning.IsPresent) {
        Write-Info "Stopping stack..."
        docker compose @composeArgs --env-file $envPath --profile local down | Out-Host
    }
    Pop-Location
}
