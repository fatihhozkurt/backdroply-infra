param(
  [string]$OutputBase = "",
  [string]$Branch = "main",
  [string]$WebRemote = "",
  [string]$BackendRemote = "",
  [string]$EngineRemote = "",
  [string]$MobileRemote = "",
  [string]$InfraRemote = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($OutputBase)) {
  $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
  $OutputBase = (Resolve-Path (Join-Path $repoRoot "..")).Path
}

$repos = @(
  @{ Name = "backdroply-web"; Path = (Join-Path $OutputBase "backdroply-web"); Remote = $WebRemote },
  @{ Name = "backdroply-backend"; Path = (Join-Path $OutputBase "backdroply-backend"); Remote = $BackendRemote },
  @{ Name = "backdroply-engine"; Path = (Join-Path $OutputBase "backdroply-engine"); Remote = $EngineRemote },
  @{ Name = "backdroply-mobile"; Path = (Join-Path $OutputBase "backdroply-mobile"); Remote = $MobileRemote },
  @{ Name = "backdroply-infra"; Path = (Join-Path $OutputBase "backdroply-infra"); Remote = $InfraRemote }
)

foreach ($repo in $repos) {
  if (!(Test-Path $repo.Path)) {
    throw "Repo klasoru bulunamadi: $($repo.Path)"
  }

  if (!(Test-Path (Join-Path $repo.Path ".git"))) {
    throw "Git init eksik: $($repo.Path)"
  }

  if ([string]::IsNullOrWhiteSpace($repo.Remote)) {
    throw "Remote URL eksik: $($repo.Name)"
  }

  $currentOrigin = (& git -C $repo.Path remote get-url origin 2>$null)
  if ($LASTEXITCODE -eq 0 -and ![string]::IsNullOrWhiteSpace($currentOrigin)) {
    $null = & git -C $repo.Path remote set-url origin $repo.Remote
  } else {
    $null = & git -C $repo.Path remote add origin $repo.Remote
  }
  if ($LASTEXITCODE -ne 0) {
    throw "origin remote ayarlanamadi: $($repo.Name)"
  }

  $null = & git -C $repo.Path push -u origin $Branch
  if ($LASTEXITCODE -ne 0) {
    throw "Push basarisiz: $($repo.Name)"
  }

  Write-Host "Pushed: $($repo.Name) -> $($repo.Remote)"
}

Write-Host "Tum split repolar push edildi."
