param(
  [string]$Profile = "local"
)

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
  docker compose --env-file $envFile --profile $Profile up --build
} finally {
  Pop-Location
}
