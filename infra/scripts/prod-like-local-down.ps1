param(
  [string]$EnvFile = ".env.production.local",
  [switch]$WithVolumes
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
    }
  }
  return $args
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$envPath = Join-Path $repoRoot $EnvFile
$envMap = Read-EnvMap $envPath
$composeArgs = Compose-Args $envMap $repoRoot

Push-Location $repoRoot
try {
  $downArgs = @("compose") + $composeArgs + @("--env-file", $envPath, "--profile", "deploy", "down", "--remove-orphans")
  if ($WithVolumes.IsPresent) {
    $downArgs += "-v"
  }
  docker @downArgs | Out-Host
} finally {
  Pop-Location
}
