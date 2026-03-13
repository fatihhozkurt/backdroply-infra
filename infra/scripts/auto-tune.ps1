param(
    [string]$EnvFile = ".env.example",
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"

function Write-Info([string]$Message) {
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "[OK]   $Message" -ForegroundColor Green
}

function Write-WarnLine([string]$Message) {
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
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
            Write-WarnLine "ENGINE_ENABLE_GPU=true but docker-compose.gpu.yml not found."
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

function Write-EnvFileWithOverrides([string]$BasePath, [string]$TargetPath, [hashtable]$Overrides) {
    $lines = Get-Content $BasePath
    foreach ($entry in $Overrides.GetEnumerator()) {
        $key = [string]$entry.Key
        $value = [string]$entry.Value
        $pattern = "^\s*" + [regex]::Escape($key) + "="
        $matched = $false
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match $pattern) {
                $lines[$i] = "$key=$value"
                $matched = $true
                break
            }
        }
        if (!$matched) {
            $lines += "$key=$value"
        }
    }
    Set-Content -Path $TargetPath -Value $lines -Encoding UTF8
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$envPath = Resolve-Path (Join-Path $repoRoot $EnvFile)
$tmpDir = Join-Path $repoRoot "tmp-integration"
$reportDir = Join-Path $tmpDir "reports"
$tuneDir = Join-Path $tmpDir "autotune"
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
New-Item -ItemType Directory -Path $tuneDir -Force | Out-Null

$profiles = @(
    @{
        Name = "quality_strict"
        Overrides = @{
            ENGINE_MODEL_CANDIDATES_ULTRA = "u2netp,u2net"
            ENGINE_MODEL_CANDIDATES_BALANCED = "u2netp,u2net"
            ENGINE_ULTRA_MAX_PASSES = "6"
            ENGINE_TEMPORAL_FLOW_STRENGTH = "0.26"
            ENGINE_EDGE_REFINE_STRENGTH = "0.82"
            ENGINE_ENABLE_FRAME_RECHECK = "true"
            ENGINE_RECHECK_EDGE_THRESHOLD = "8.0"
            ENGINE_RECHECK_DISAGREEMENT_THRESHOLD = "24.0"
            ENGINE_MAX_CONCURRENT_JOBS = "2"
            APP_MAX_IN_FLIGHT_PROCESS_JOBS = "64"
            APP_IN_FLIGHT_ACQUIRE_TIMEOUT_MS = "300"
            PREFLIGHT_BENCH_IMAGE_REQUESTS = "10"
            PREFLIGHT_BENCH_VIDEO_REQUESTS = "6"
            PREFLIGHT_BENCH_CONCURRENCY = "4"
            PREFLIGHT_BENCH_USER_POOL = "10"
        }
    },
    @{
        Name = "balanced_default"
        Overrides = @{
            ENGINE_MODEL_CANDIDATES_ULTRA = "u2netp"
            ENGINE_MODEL_CANDIDATES_BALANCED = "u2netp"
            ENGINE_ULTRA_MAX_PASSES = "5"
            ENGINE_TEMPORAL_FLOW_STRENGTH = "0.22"
            ENGINE_EDGE_REFINE_STRENGTH = "0.70"
            ENGINE_ENABLE_FRAME_RECHECK = "true"
            ENGINE_RECHECK_EDGE_THRESHOLD = "9.0"
            ENGINE_RECHECK_DISAGREEMENT_THRESHOLD = "28.0"
            ENGINE_MAX_CONCURRENT_JOBS = "2"
            APP_MAX_IN_FLIGHT_PROCESS_JOBS = "64"
            APP_IN_FLIGHT_ACQUIRE_TIMEOUT_MS = "250"
            PREFLIGHT_BENCH_IMAGE_REQUESTS = "10"
            PREFLIGHT_BENCH_VIDEO_REQUESTS = "6"
            PREFLIGHT_BENCH_CONCURRENCY = "4"
            PREFLIGHT_BENCH_USER_POOL = "10"
        }
    },
    @{
        Name = "throughput_boost"
        Overrides = @{
            ENGINE_MODEL_CANDIDATES_ULTRA = "u2netp"
            ENGINE_MODEL_CANDIDATES_BALANCED = "u2netp"
            ENGINE_ULTRA_MAX_PASSES = "4"
            ENGINE_TEMPORAL_FLOW_STRENGTH = "0.18"
            ENGINE_EDGE_REFINE_STRENGTH = "0.64"
            ENGINE_ENABLE_FRAME_RECHECK = "true"
            ENGINE_RECHECK_EDGE_THRESHOLD = "10.0"
            ENGINE_RECHECK_DISAGREEMENT_THRESHOLD = "30.0"
            ENGINE_MAX_CONCURRENT_JOBS = "3"
            ENGINE_UVICORN_WORKERS = "2"
            APP_MAX_IN_FLIGHT_PROCESS_JOBS = "96"
            APP_IN_FLIGHT_ACQUIRE_TIMEOUT_MS = "200"
            PREFLIGHT_BENCH_IMAGE_REQUESTS = "10"
            PREFLIGHT_BENCH_VIDEO_REQUESTS = "6"
            PREFLIGHT_BENCH_CONCURRENCY = "6"
            PREFLIGHT_BENCH_USER_POOL = "14"
        }
    }
)

$results = New-Object System.Collections.Generic.List[object]
$benchmarkScript = Join-Path $PSScriptRoot "benchmark_probe.py"
if (!(Test-Path $benchmarkScript)) {
    throw "Benchmark probe not found: $benchmarkScript"
}

foreach ($profile in $profiles) {
    $name = $profile.Name
    $overrides = $profile.Overrides
    $tempEnv = Join-Path $tuneDir (".env." + $name + ".tmp")
    $reportPath = Join-Path $reportDir ("autotune-" + $name + ".json")
    Write-EnvFileWithOverrides -BasePath $envPath -TargetPath $tempEnv -Overrides $overrides

    $envMap = Read-EnvMap $tempEnv
    $composeArgs = Compose-Args $envMap $repoRoot
    $backendPort = if ($envMap.ContainsKey("BACKEND_PORT")) { $envMap["BACKEND_PORT"] } else { "8080" }
    $enginePort = if ($envMap.ContainsKey("ENGINE_PORT")) { $envMap["ENGINE_PORT"] } else { "9000" }

    Push-Location $repoRoot
    try {
        Write-Info "Auto-tune profile '$name' is starting..."
        docker compose @composeArgs --env-file $tempEnv --profile local up -d --build | Out-Host

        if (!(Wait-HttpUp "http://localhost:$backendPort/actuator/health" '"status":"UP"')) {
            throw "Backend health check did not become UP for profile '$name'."
        }
        if (!(Wait-HttpUp "http://localhost:$enginePort/health" '"status":"ok"')) {
            throw "Engine health check did not become OK for profile '$name'."
        }

        python $benchmarkScript --env-file $tempEnv --tmp-dir $tmpDir --output-json $reportPath
        $probeExit = $LASTEXITCODE
        if ($probeExit -ne 0 -and $probeExit -ne 2) {
            throw "Benchmark probe execution failed for profile '$name' with exit code $probeExit."
        }
        if (!(Test-Path $reportPath)) {
            throw "Benchmark report is missing for profile '$name'."
        }

        $report = Get-Content -Raw $reportPath | ConvertFrom-Json
        $go = $report.goNoGo.result
        $score = [double]$report.goNoGo.score.overall
        $errRate = [double]$report.goNoGo.combinedErrorRate
        $videoP95 = [double]$report.phases.video.latencyMs.p95
        $videoQcMean = [double]$report.phases.video.qcSuspectFrames.mean
        $results.Add([pscustomobject]@{
            Name = $name
            Go = $go
            Score = $score
            CombinedErrorRate = $errRate
            VideoP95Ms = $videoP95
            VideoQcMean = $videoQcMean
            ReportPath = $reportPath
            TempEnv = $tempEnv
            Overrides = $overrides
        }) | Out-Null
        Write-Ok "Profile '$name' completed. Result=$go Score=$score"
    } finally {
        Write-Info "Stopping stack for profile '$name'..."
        docker compose @composeArgs --env-file $tempEnv --profile local down | Out-Host
        Pop-Location
    }
}

if ($results.Count -eq 0) {
    throw "Auto-tune produced no benchmark results."
}

Write-Host ""
Write-Host "Auto-tune summary:" -ForegroundColor Cyan
$results | Sort-Object Score -Descending | Format-Table Name,Go,Score,CombinedErrorRate,VideoP95Ms,VideoQcMean -AutoSize | Out-Host

$goResults = $results | Where-Object { $_.Go -eq "GO" }
$best = $null
if ($goResults.Count -gt 0) {
    $best = $goResults | Sort-Object Score -Descending | Select-Object -First 1
} else {
    $best = $results | Sort-Object Score -Descending | Select-Object -First 1
    Write-WarnLine "No profile passed GO gates. Best NO_GO profile selected for manual review."
}

$autotunedPath = Join-Path $repoRoot ".env.autotuned"
Write-EnvFileWithOverrides -BasePath $envPath -TargetPath $autotunedPath -Overrides $best.Overrides
Write-Ok "Auto-tuned env generated: $autotunedPath (profile=$($best.Name), result=$($best.Go), score=$($best.Score))"

if ($KeepRunning.IsPresent) {
    $baseEnvMap = Read-EnvMap $autotunedPath
    $autotunedComposeArgs = Compose-Args $baseEnvMap $repoRoot
    Push-Location $repoRoot
    try {
        Write-Info "Starting stack with auto-tuned env..."
        docker compose @autotunedComposeArgs --env-file $autotunedPath --profile local up -d --build | Out-Host
    } finally {
        Pop-Location
    }
}
