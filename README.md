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

## Docs

See `docs/` for architecture, security, legal, deployment, and mobile notes.
Go-live gate checklist: `docs/GO_LIVE_GATE.md`.
