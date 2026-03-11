# Backdroply Infra

Infrastructure and deployment assets for local/dev/deploy profiles.

## Scope

- Docker Compose topology
- Environment template (`.env.example`)
- Infrastructure scripts under `infra/scripts`
- Product docs under `docs/`

> Compose build context note: this repo expects sibling repos at:
> `../backdroply-web`, `../backdroply-backend`, `../backdroply-engine`

## Key Scripts

- `infra/scripts/dev-up.ps1`
- `infra/scripts/dev-down.ps1`
- `infra/scripts/go-live-preflight.ps1`
- `infra/scripts/split-repos.ps1`
- `infra/scripts/push-split-repos.ps1`

## Run Local Stack

```bash
docker compose --profile local up --build -d
```

## Stop

```bash
docker compose --profile local down
```

## Go-Live Preflight

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production
```

With smoke run:

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production -RunSmoke
```

With full API flow probe (auth + media + concurrency + security + my-media cap):

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production -RunFullE2E
```

Direct full probe command:

```powershell
pwsh ./infra/scripts/full-e2e.ps1 -EnvFile .env.production
```

If `pwsh` is not installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\\infra\\scripts\\full-e2e.ps1 -EnvFile .env.production
```

## Docs

See `docs/` for architecture, security, legal, deployment, and mobile notes.
Go-live gate checklist: `docs/GO_LIVE_GATE.md`.
Latest technical readiness report: `docs/PRODUCTION_READINESS_REPORT_2026-03-11.md`.
