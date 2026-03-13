param(
  [string]$Profile = "local"
)

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

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$envFile = Join-Path $repoRoot ".env"
$envExample = Join-Path $repoRoot ".env.example"

if (-not (Test-Path $envFile)) {
  if (-not (Test-Path $envExample)) {
    throw ".env.example bulunamadi: $envExample"
  }
  Write-Host ".env bulunamadi. .env.example kopyalanacak..."
  Copy-Item $envExample $envFile
}

Push-Location $repoRoot
try {
  $envMap = Read-EnvMap $envFile
  $composeArgs = @("-f", (Join-Path $repoRoot "docker-compose.yml"))
  if ($envMap.ContainsKey("ENGINE_ENABLE_GPU") -and $envMap["ENGINE_ENABLE_GPU"].Trim().ToLowerInvariant() -eq "true") {
    $gpuOverride = Join-Path $repoRoot "docker-compose.gpu.yml"
    if (Test-Path $gpuOverride) {
      $composeArgs += @("-f", $gpuOverride)
      Write-Host "GPU compose override aktif: $gpuOverride"
    } else {
      Write-Host "ENGINE_ENABLE_GPU=true ama docker-compose.gpu.yml bulunamadi."
    }
  }
  docker compose @composeArgs --env-file $envFile --profile $Profile up --build
} finally {
  Pop-Location
}
