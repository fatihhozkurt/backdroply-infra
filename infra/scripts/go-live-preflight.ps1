param(
    [string]$EnvFile = ".env.example",
    [switch]$RunSmoke,
    [switch]$RunFullE2E,
    [switch]$RunBenchmark,
    [switch]$RunAutoTune,
    [switch]$SkipBenchmark,
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"

function Write-Ok([string]$Message) {
    Write-Host "[OK]  $Message" -ForegroundColor Green
}

function Write-WarnLine([string]$Message) {
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Err([string]$Message) {
    Write-Host "[ERR] $Message" -ForegroundColor Red
}

function IsPlaceholder([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $true }
    $v = $Value.Trim().ToLowerInvariant()
    return $v.StartsWith("replace_") -or $v.StartsWith("change_me") -or $v.Contains("example") -or $v.Contains("your_")
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
            Write-Host "[INFO] GPU compose override enabled: $gpuFile" -ForegroundColor Cyan
        } else {
            Write-WarnLine "ENGINE_ENABLE_GPU=true but docker-compose.gpu.yml not found."
        }
    }
    return $args
}

function Require-Value([hashtable]$EnvMap, [string]$Key, [System.Collections.Generic.List[string]]$Errors) {
    if (!$EnvMap.ContainsKey($Key) -or [string]::IsNullOrWhiteSpace($EnvMap[$Key])) {
        $Errors.Add("$Key is missing or empty.")
        return
    }
    if (IsPlaceholder $EnvMap[$Key]) {
        $Errors.Add("$Key still uses a placeholder value.")
    }
}

function Assert-HttpsOrigin([hashtable]$EnvMap, [System.Collections.Generic.List[string]]$Errors) {
    if (!$EnvMap.ContainsKey("BACKEND_ALLOWED_ORIGIN")) {
        $Errors.Add("BACKEND_ALLOWED_ORIGIN is missing.")
        return
    }
    $origins = $EnvMap["BACKEND_ALLOWED_ORIGIN"].Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
    if ($origins.Count -eq 0) {
        $Errors.Add("BACKEND_ALLOWED_ORIGIN has no valid origins.")
        return
    }
    foreach ($origin in $origins) {
        if (!$origin.StartsWith("https://")) {
            $Errors.Add("BACKEND_ALLOWED_ORIGIN must be HTTPS for launch: $origin")
        }
        $low = $origin.ToLowerInvariant()
        if ($low.Contains("localhost") -or $low.Contains("127.0.0.1")) {
            $Errors.Add("BACKEND_ALLOWED_ORIGIN cannot contain localhost for launch: $origin")
        }
    }
}

function Verify-GoogleClient([hashtable]$EnvMap, [System.Collections.Generic.List[string]]$Errors) {
    Require-Value $EnvMap "GOOGLE_CLIENT_ID" $Errors
    Require-Value $EnvMap "VITE_GOOGLE_CLIENT_ID" $Errors
    if ($EnvMap.ContainsKey("GOOGLE_CLIENT_ID") -and !$EnvMap["GOOGLE_CLIENT_ID"].Trim().EndsWith(".apps.googleusercontent.com")) {
        $Errors.Add("GOOGLE_CLIENT_ID format looks invalid.")
    }
    if ($EnvMap.ContainsKey("GOOGLE_CLIENT_ID") -and $EnvMap.ContainsKey("VITE_GOOGLE_CLIENT_ID")) {
        if ($EnvMap["GOOGLE_CLIENT_ID"].Trim() -ne $EnvMap["VITE_GOOGLE_CLIENT_ID"].Trim()) {
            $Errors.Add("GOOGLE_CLIENT_ID and VITE_GOOGLE_CLIENT_ID must match.")
        }
    }
}

function Verify-MobileGoogleIds([System.Collections.Generic.List[string]]$Warnings) {
    $mobileAppJson = Join-Path "..\backdroply-mobile" "app.json"
    if (!(Test-Path $mobileAppJson)) {
        $Warnings.Add("Mobile repo not found at ../backdroply-mobile. Mobile OAuth IDs could not be checked.")
        return
    }
    $payload = Get-Content -Raw $mobileAppJson | ConvertFrom-Json
    $extra = $payload.expo.extra
    if ([string]::IsNullOrWhiteSpace($extra.googleWebClientId)) {
        $Warnings.Add("backdroply-mobile/app.json -> expo.extra.googleWebClientId is empty.")
    }
    if ([string]::IsNullOrWhiteSpace($extra.googleAndroidClientId)) {
        $Warnings.Add("backdroply-mobile/app.json -> expo.extra.googleAndroidClientId is empty.")
    }
    if ([string]::IsNullOrWhiteSpace($extra.googleIosClientId)) {
        $Warnings.Add("backdroply-mobile/app.json -> expo.extra.googleIosClientId is empty.")
    }
}

function Invoke-Smoke([string]$EnvFilePath, [string[]]$ComposeArgs, [hashtable]$EnvMap) {
    Write-Host ""
    Write-Host "Running docker compose smoke..." -ForegroundColor Cyan
    docker compose @ComposeArgs --env-file $EnvFilePath --profile local up -d --build | Out-Host
    Start-Sleep -Seconds 10

    $backendPort = if ($EnvMap.ContainsKey("BACKEND_PORT")) { $EnvMap["BACKEND_PORT"] } else { "8080" }
    $enginePort = if ($EnvMap.ContainsKey("ENGINE_PORT")) { $EnvMap["ENGINE_PORT"] } else { "9000" }
    $webPort = if ($EnvMap.ContainsKey("WEB_PORT")) { $EnvMap["WEB_PORT"] } else { "5173" }

    $apiHealth = curl.exe -sS "http://localhost:$backendPort/actuator/health"
    if (!$apiHealth.Contains('"status":"UP"')) {
        throw "Backend health check failed: $apiHealth"
    }
    Write-Ok "Backend health check passed."

    $engineHealth = curl.exe -sS "http://localhost:$enginePort/health"
    if (!$engineHealth.Contains('"status":"ok"')) {
        throw "Engine health check failed: $engineHealth"
    }
    Write-Ok "Engine health check passed."

    $webCode = curl.exe -sS -o NUL -w "%{http_code}" "http://localhost:$webPort"
    if ($webCode -ne "200") {
        throw "Web health check failed with status: $webCode"
    }
    Write-Ok "Web health check passed."
}

$root = Resolve-Path "."
$envPath = Join-Path $root $EnvFile

Write-Host "Backdroply Go-Live Preflight" -ForegroundColor Cyan
Write-Host "Using env file: $envPath"

$errors = New-Object 'System.Collections.Generic.List[string]'
$warnings = New-Object 'System.Collections.Generic.List[string]'
$envMap = Read-EnvMap $envPath
$composeArgs = Compose-Args $envMap $root

# Core security + OAuth + payment checks
Require-Value $envMap "BACKEND_JWT_SECRET" $errors
if ($envMap.ContainsKey("BACKEND_JWT_SECRET") -and $envMap["BACKEND_JWT_SECRET"].Length -lt 32) {
    $errors.Add("BACKEND_JWT_SECRET must be at least 32 chars.")
}
Require-Value $envMap "ENGINE_SHARED_TOKEN" $errors
if ($envMap.ContainsKey("ENGINE_SHARED_TOKEN") -and $envMap["ENGINE_SHARED_TOKEN"].Length -lt 24) {
    $errors.Add("ENGINE_SHARED_TOKEN must be at least 24 chars.")
}
Verify-GoogleClient $envMap $errors
Require-Value $envMap "PAYMENT_PROVIDER_API_KEY" $errors
Require-Value $envMap "PAYMENT_PROVIDER_SECRET_KEY" $errors
Require-Value $envMap "PAYMENT_WEBHOOK_SECRET" $errors
if ($envMap.ContainsKey("PAYMENT_WEBHOOK_SECRET") -and $envMap["PAYMENT_WEBHOOK_SECRET"].Length -lt 24) {
    $errors.Add("PAYMENT_WEBHOOK_SECRET must be at least 24 chars.")
}
if ($envMap.ContainsKey("PAYMENT_PROVIDER_BASE_URL")) {
    $pb = $envMap["PAYMENT_PROVIDER_BASE_URL"].Trim()
    if (!$pb.StartsWith("https://")) {
        $errors.Add("PAYMENT_PROVIDER_BASE_URL must be HTTPS.")
    }
}
Assert-HttpsOrigin $envMap $errors

if ($envMap.ContainsKey("APP_STRICT_STARTUP")) {
    if ($envMap["APP_STRICT_STARTUP"].Trim().ToLowerInvariant() -ne "true") {
        $warnings.Add("APP_STRICT_STARTUP is not true. Enable it for deploy profile.")
    }
} else {
    $warnings.Add("APP_STRICT_STARTUP is missing in env.")
}

Verify-MobileGoogleIds $warnings

if ($errors.Count -eq 0) {
    Write-Ok "Static preflight checks passed."
} else {
    Write-Err "Static preflight checks failed."
    $errors | ForEach-Object { Write-Err $_ }
}

if ($warnings.Count -gt 0) {
    $warnings | ForEach-Object { Write-WarnLine $_ }
}

if ($errors.Count -eq 0 -and $RunSmoke.IsPresent) {
    try {
        Invoke-Smoke $envPath $composeArgs $envMap
    } finally {
        if (!$KeepRunning.IsPresent) {
            docker compose @composeArgs --env-file $envPath --profile local down | Out-Host
            Write-Host "Smoke stack stopped."
        }
    }
}

if ($errors.Count -eq 0 -and $RunFullE2E.IsPresent) {
    $fullE2eScript = Join-Path $PSScriptRoot "full-e2e.ps1"
    if (!(Test-Path $fullE2eScript)) {
        throw "full-e2e script not found: $fullE2eScript"
    }
    if (!$SkipBenchmark.IsPresent -and $KeepRunning.IsPresent) {
        & $fullE2eScript -EnvFile $EnvFile -RunBenchmark -KeepRunning
    } elseif (!$SkipBenchmark.IsPresent -and !$KeepRunning.IsPresent) {
        & $fullE2eScript -EnvFile $EnvFile -RunBenchmark
    } elseif ($SkipBenchmark.IsPresent -and $KeepRunning.IsPresent) {
        & $fullE2eScript -EnvFile $EnvFile -KeepRunning
    } else {
        & $fullE2eScript -EnvFile $EnvFile
    }
}

if ($errors.Count -eq 0 -and !$RunFullE2E.IsPresent -and $RunBenchmark.IsPresent) {
    $benchmarkScript = Join-Path $PSScriptRoot "load-benchmark.ps1"
    if (!(Test-Path $benchmarkScript)) {
        throw "load-benchmark script not found: $benchmarkScript"
    }
    if ($KeepRunning.IsPresent) {
        & $benchmarkScript -EnvFile $EnvFile -KeepRunning
    } else {
        & $benchmarkScript -EnvFile $EnvFile
    }
}

if ($errors.Count -eq 0 -and $RunAutoTune.IsPresent) {
    $autoTuneScript = Join-Path $PSScriptRoot "auto-tune.ps1"
    if (!(Test-Path $autoTuneScript)) {
        throw "auto-tune script not found: $autoTuneScript"
    }
    if ($KeepRunning.IsPresent) {
        & $autoTuneScript -EnvFile $EnvFile -KeepRunning
    } else {
        & $autoTuneScript -EnvFile $EnvFile
    }
}

if ($errors.Count -gt 0) {
    exit 1
}

Write-Host "Go-live preflight completed." -ForegroundColor Green
