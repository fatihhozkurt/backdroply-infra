param(
  [string]$OutputBase = "",
  [switch]$CleanTarget,
  [switch]$InitGit,
  [switch]$Commit,
  [string]$DefaultBranch = "main",
  [string]$CommitMessage = "chore: initial split from monorepo"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if ([string]::IsNullOrWhiteSpace($OutputBase)) {
  $OutputBase = (Resolve-Path (Join-Path $repoRoot "..")).Path
}

Write-Host "Repo root   : $repoRoot"
Write-Host "Output base : $OutputBase"

function Ensure-Directory {
  param([string]$Path)
  if (!(Test-Path $Path)) {
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
  }
}

function Copy-Tree {
  param(
    [string]$Source,
    [string]$Target
  )
  Ensure-Directory $Target
  $excludeDirs = @("node_modules", "dist", "dist-web", "target", ".expo", ".gradle", "__pycache__", ".venv")
  $excludeFiles = @("*.log")
  $args = @(
    $Source,
    $Target,
    "/E",
    "/R:1",
    "/W:1",
    "/NFL",
    "/NDL",
    "/NJH",
    "/NJS",
    "/NP"
  )
  foreach ($d in $excludeDirs) {
    $args += "/XD"
    $args += $d
  }
  foreach ($f in $excludeFiles) {
    $args += "/XF"
    $args += $f
  }
  $null = & robocopy @args
  $code = $LASTEXITCODE
  if ($code -gt 7) {
    throw "robocopy failed from '$Source' to '$Target' with exit code $code"
  }
}

function Write-RepoReadme {
  param(
    [string]$Target,
    [string]$Title,
    [string[]]$Lines
  )
  $content = @("# $Title", "") + $Lines + @("")
  Set-Content -Path (Join-Path $Target "README.md") -Value $content -Encoding UTF8
}

function Write-RepoGitignore {
  param(
    [string]$Target,
    [string[]]$Lines
  )
  Set-Content -Path (Join-Path $Target ".gitignore") -Value ($Lines + @("")) -Encoding UTF8
}

function Initialize-GitRepo {
  param([string]$RepoPath)

  if (!(Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git komutu bulunamadi."
  }

  $gitDir = Join-Path $RepoPath ".git"
  if (!(Test-Path $gitDir)) {
    $null = & git -C $RepoPath init
    if ($LASTEXITCODE -ne 0) {
      throw "git init failed: $RepoPath"
    }
  }

  $null = & git -C $RepoPath branch -M $DefaultBranch
  if ($LASTEXITCODE -ne 0) {
    throw "git branch -M failed: $RepoPath"
  }

  $null = & git -C $RepoPath add .
  if ($LASTEXITCODE -ne 0) {
    throw "git add failed: $RepoPath"
  }

  if ($Commit) {
    $null = & git -C $RepoPath commit -m $CommitMessage
    if ($LASTEXITCODE -ne 0) {
      Write-Warning "Commit atlandi ($RepoPath). Muhtemel sebep: user.name/user.email ayari eksik veya degisiklik yok."
    }
  }
}

$targets = @{
  "backdroply-web" = "apps\web"
  "backdroply-backend" = "services\backend"
  "backdroply-engine" = "services\engine"
  "backdroply-mobile" = "apps\mobile"
}

foreach ($name in $targets.Keys) {
  $dest = Join-Path $OutputBase $name
  if ($CleanTarget -and (Test-Path $dest)) {
    Remove-Item -Path $dest -Recurse -Force
  }
  Ensure-Directory $dest
}

# Split core repos
Copy-Tree -Source (Join-Path $repoRoot "apps\web") -Target (Join-Path $OutputBase "backdroply-web")
Copy-Tree -Source (Join-Path $repoRoot "services\backend") -Target (Join-Path $OutputBase "backdroply-backend")
Copy-Tree -Source (Join-Path $repoRoot "services\engine") -Target (Join-Path $OutputBase "backdroply-engine")
Copy-Tree -Source (Join-Path $repoRoot "apps\mobile") -Target (Join-Path $OutputBase "backdroply-mobile")

# Infra/deploy repo
$infraRepo = Join-Path $OutputBase "backdroply-infra"
if ($CleanTarget -and (Test-Path $infraRepo)) {
  Remove-Item -Path $infraRepo -Recurse -Force
}
Ensure-Directory $infraRepo
Copy-Tree -Source (Join-Path $repoRoot "infra") -Target (Join-Path $infraRepo "infra")
Copy-Tree -Source (Join-Path $repoRoot "docs") -Target (Join-Path $infraRepo "docs")
Copy-Item -Path (Join-Path $repoRoot "docker-compose.yml") -Destination (Join-Path $infraRepo "docker-compose.yml") -Force
Copy-Item -Path (Join-Path $repoRoot ".env.example") -Destination (Join-Path $infraRepo ".env.example") -Force

Write-RepoReadme -Target (Join-Path $OutputBase "backdroply-web") -Title "Backdroply Web" -Lines @(
  "React + Tailwind web client.",
  "",
  "## Run",
  "npm install",
  "npm run dev"
)
Write-RepoGitignore -Target (Join-Path $OutputBase "backdroply-web") -Lines @(
  "node_modules/",
  "dist/",
  ".DS_Store",
  "*.log"
)

Write-RepoReadme -Target (Join-Path $OutputBase "backdroply-backend") -Title "Backdroply Backend" -Lines @(
  "Spring Boot API with JWT auth, token wallet, billing hooks and Liquibase migrations.",
  "",
  "## Run",
  "mvn spring-boot:run"
)
Write-RepoGitignore -Target (Join-Path $OutputBase "backdroply-backend") -Lines @(
  "target/",
  ".mvn/",
  ".idea/",
  ".DS_Store",
  "*.log"
)

Write-RepoReadme -Target (Join-Path $OutputBase "backdroply-engine") -Title "Backdroply Engine" -Lines @(
  "Python FastAPI background removal engine for image and video.",
  "",
  "## Run",
  "pip install -r requirements.txt",
  "uvicorn app.main:app --host 0.0.0.0 --port 9000"
)
Write-RepoGitignore -Target (Join-Path $OutputBase "backdroply-engine") -Lines @(
  "__pycache__/",
  ".venv/",
  "*.pyc",
  "*.pyo",
  ".pytest_cache/",
  ".DS_Store"
)

Write-RepoReadme -Target (Join-Path $OutputBase "backdroply-mobile") -Title "Backdroply Mobile" -Lines @(
  "Expo based iOS/Android app.",
  "",
  "## Run",
  "npm install",
  "npx expo start"
)
Write-RepoGitignore -Target (Join-Path $OutputBase "backdroply-mobile") -Lines @(
  "node_modules/",
  "dist-web/",
  ".expo/",
  ".DS_Store",
  "*.log"
)

Write-RepoReadme -Target $infraRepo -Title "Backdroply Infra" -Lines @(
  "Deployment and environment assets.",
  "",
  "## Run (local profile)",
  "docker compose --profile local up --build -d"
)
Write-RepoGitignore -Target $infraRepo -Lines @(
  ".env",
  "*.log",
  ".DS_Store"
)

$generatedRepos = @(
  (Join-Path $OutputBase "backdroply-web"),
  (Join-Path $OutputBase "backdroply-backend"),
  (Join-Path $OutputBase "backdroply-engine"),
  (Join-Path $OutputBase "backdroply-mobile"),
  $infraRepo
)

if ($InitGit) {
  foreach ($repo in $generatedRepos) {
    Initialize-GitRepo -RepoPath $repo
  }
}

Write-Host "Split completed."
Write-Host "Generated repos under ${OutputBase}:"
Write-Host " - backdroply-web"
Write-Host " - backdroply-backend"
Write-Host " - backdroply-engine"
Write-Host " - backdroply-mobile"
Write-Host " - backdroply-infra"
if ($InitGit) {
  Write-Host "Git initialized for all generated repos (branch: $DefaultBranch)."
  if ($Commit) {
    Write-Host "Initial commit attempted with message: $CommitMessage"
  }
}
