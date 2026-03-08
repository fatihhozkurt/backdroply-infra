$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
Push-Location $repoRoot
try {
  docker compose down -v
} finally {
  Pop-Location
}
