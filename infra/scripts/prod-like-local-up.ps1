param(
  [string]$EnvFile = ".env.production.local",
  [switch]$RunE2E,
  [switch]$RunBenchmark
)

$ErrorActionPreference = "Stop"

function Read-EnvMap([string]$Path) {
  $map = @{}
  if (!(Test-Path $Path)) {
    return $map
  }
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
      Write-Host "[INFO] GPU compose override enabled: $gpuFile" -ForegroundColor Cyan
    } else {
      Write-Host "[WARN] ENGINE_ENABLE_GPU=true but docker-compose.gpu.yml not found." -ForegroundColor Yellow
    }
  }
  return $args
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

function Test-PortInUse([int]$Port) {
  try {
    $used = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $used
  } catch {
    return $false
  }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$envPath = Join-Path $repoRoot $EnvFile
$envExample = Join-Path $repoRoot ".env.example"

if (!(Test-Path $envPath)) {
  if (!(Test-Path $envExample)) {
    throw ".env.example not found: $envExample"
  }
  Write-Host "[INFO] $EnvFile not found. Creating from .env.example..." -ForegroundColor Cyan
  Copy-Item $envExample $envPath
}

$envMap = Read-EnvMap $envPath
$composeArgs = Compose-Args $envMap $repoRoot

$backendPort = if ($envMap.ContainsKey("BACKEND_PORT")) { $envMap["BACKEND_PORT"] } else { "8080" }
$enginePort = if ($envMap.ContainsKey("ENGINE_PORT")) { $envMap["ENGINE_PORT"] } else { "9000" }
$webPort = if ($envMap.ContainsKey("WEB_PORT")) { $envMap["WEB_PORT"] } else { "8081" }

Push-Location $repoRoot
try {
  foreach ($conflictName in @("bgremover-web-dev", "bgremover-web-prod")) {
    $containerIdRaw = docker ps -q --filter "name=^$conflictName$" 2>$null
    $containerId = if ($null -eq $containerIdRaw) { "" } else { "$containerIdRaw".Trim() }
    if ($containerId.Length -gt 0) {
      Write-Host "[INFO] Existing container detected ($conflictName). Restarting cleanly..." -ForegroundColor Cyan
      docker stop $conflictName | Out-Host
      docker rm $conflictName | Out-Host
    }
  }

  if (Test-PortInUse ([int]$webPort)) {
    foreach ($candidate in @(5180, 8081, 5174)) {
      if (-not (Test-PortInUse $candidate)) {
        $webPort = "$candidate"
        $env:WEB_PORT = "$candidate"
        Write-Host "[WARN] Requested WEB_PORT is in use. Falling back to WEB_PORT=$candidate for this run." -ForegroundColor Yellow
        break
      }
    }
  }

  Write-Host "[INFO] Starting production-like local stack (deploy profile)..." -ForegroundColor Cyan
  docker compose @composeArgs --env-file $envPath --profile deploy up -d --build | Out-Host

  if (!(Wait-HttpUp "http://localhost:$backendPort/actuator/health" '"status":"UP"')) {
    throw "Backend health check failed on port $backendPort."
  }
  if (!(Wait-HttpUp "http://localhost:$enginePort/health" '"status":"ok"')) {
    throw "Engine health check failed on port $enginePort."
  }
  $webCode = curl.exe -sS -o NUL -w "%{http_code}" "http://localhost:$webPort"
  if ($webCode -ne "200") {
    throw "Web health check failed with HTTP $webCode on port $webPort."
  }

  Write-Host "[OK] Production-like local stack is up." -ForegroundColor Green
  Write-Host "Web:      http://localhost:$webPort" -ForegroundColor Green
  Write-Host "API:      http://localhost:$backendPort/api/v1" -ForegroundColor Green
  Write-Host "Health:   http://localhost:$backendPort/actuator/health" -ForegroundColor Green
  Write-Host "Engine:   http://localhost:$enginePort/health" -ForegroundColor Green

  if ($RunE2E.IsPresent) {
    $probePath = Join-Path $PSScriptRoot "e2e_full_probe.py"
    if (!(Test-Path $probePath)) {
      throw "E2E probe script not found: $probePath"
    }
    $tmpDir = Join-Path $repoRoot "tmp-integration"
    Write-Host "[INFO] Running full E2E probe..." -ForegroundColor Cyan
    python $probePath --env-file $envPath --tmp-dir $tmpDir
    if ($LASTEXITCODE -ne 0) {
      throw "E2E probe failed with exit code $LASTEXITCODE."
    }
    Write-Host "[OK] E2E probe passed." -ForegroundColor Green
  }

  if ($RunBenchmark.IsPresent) {
    $benchmarkPath = Join-Path $PSScriptRoot "benchmark_probe.py"
    if (!(Test-Path $benchmarkPath)) {
      throw "Benchmark script not found: $benchmarkPath"
    }
    $tmpDir = Join-Path $repoRoot "tmp-integration"
    $reportDir = Join-Path $tmpDir "reports"
    New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $reportPath = Join-Path $reportDir "benchmark-$stamp.json"
    Write-Host "[INFO] Running benchmark/go-no-go..." -ForegroundColor Cyan
    python $benchmarkPath --env-file $envPath --tmp-dir $tmpDir --output-json $reportPath
    if ($LASTEXITCODE -eq 2) {
      throw "Benchmark result is NO_GO. Report: $reportPath"
    }
    if ($LASTEXITCODE -ne 0) {
      throw "Benchmark probe failed with exit code $LASTEXITCODE."
    }
    Write-Host "[OK] Benchmark GO. Report: $reportPath" -ForegroundColor Green
  }
} finally {
  Pop-Location
}
