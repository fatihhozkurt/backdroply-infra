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
- `infra/scripts/load-benchmark.ps1`
- `infra/scripts/auto-tune.ps1`
- `infra/scripts/split-repos.ps1`
- `infra/scripts/push-split-repos.ps1`

## Run Local Stack

```bash
docker compose --profile local up --build -d
```

GPU primary + CPU fallback (NVIDIA host):

```bash
ENGINE_ENABLE_GPU=true docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile local up --build -d
```

## Production-Like Local (Recommended for manual release testing)

Starts deploy profile (`web-prod` + backend + engine + postgres + rabbitmq + minio) with your env file:

```powershell
pwsh ./infra/scripts/prod-like-local-up.ps1 -EnvFile .env.production.local
```

Run with full async-flow E2E + benchmark:

```powershell
pwsh ./infra/scripts/prod-like-local-up.ps1 -EnvFile .env.production.local -RunE2E -RunBenchmark
```

Stop:

```powershell
pwsh ./infra/scripts/prod-like-local-down.ps1 -EnvFile .env.production.local
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

With benchmark + automatic go/no-go gates only:

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production -RunBenchmark
```

With auto-tune (profile sweep + `.env.autotuned` generation):

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production -RunAutoTune
```

Direct full probe command:

```powershell
pwsh ./infra/scripts/full-e2e.ps1 -EnvFile .env.production
```

Direct benchmark command:

```powershell
pwsh ./infra/scripts/load-benchmark.ps1 -EnvFile .env.production
```

`benchmark_probe.py` now measures **terminal job latency** (submit -> `SUCCESS`/`FAILED`) by polling `/media/jobs/{id}/status`; it no longer reports submit-only latency.

Custom sample files (for real-world manual benchmark):

```powershell
python .\infra\scripts\benchmark_probe.py `
  --env-file .\.env.production.local `
  --tmp-dir .\tmp-integration `
  --video-file C:\Users\fatih\Desktop\vidu-video-3191802828768854.mp4 `
  --image-requests 0 --video-requests 1 --concurrency 1 --user-pool 1 `
  --request-timeout-sec 500 `
  --output-json .\tmp-integration\reports\bench-user-video.json
```

Ground-truth alpha quality gate (optional):

```powershell
python .\infra\scripts\benchmark_probe.py `
  --env-file .\.env.production.local `
  --tmp-dir .\tmp-integration `
  --video-file C:\path\input.mp4 `
  --video-gt-alpha-video C:\path\input_gt_alpha.mp4 `
  --image-requests 0 --video-requests 1 --concurrency 1 --user-pool 1 `
  --video-gt-eval-limit 1 `
  --output-json .\tmp-integration\reports\bench-gt.json
```

If `pwsh` is not installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\\infra\\scripts\\full-e2e.ps1 -EnvFile .env.production
```

## Docs

See `docs/` for architecture, security, legal, deployment, and mobile notes.
Go-live gate checklist: `docs/GO_LIVE_GATE.md`.
Latest technical readiness report: `docs/PRODUCTION_READINESS_REPORT_2026-03-11.md`.

## High-Traffic Tuning

For higher concurrent traffic, tune these env keys in `.env`:

- `ENGINE_MAX_CONCURRENT_JOBS`
- `ENGINE_QUEUE_WAIT_SECONDS`
- `ENGINE_UVICORN_WORKERS`
- `ENGINE_UVICORN_LIMIT_CONCURRENCY`
- `APP_MAX_IN_FLIGHT_PROCESS_JOBS`
- `APP_IN_FLIGHT_ACQUIRE_TIMEOUT_MS`
- `QUEUE_ENABLED`
- `QUEUE_MAX_DEPTH`
- `QUEUE_CONSUMERS`
- `QUEUE_PREFETCH`
- `RABBITMQ_USER`
- `RABBITMQ_PASS`

Support/compliance contact metadata (surfaced in web/mobile):

- `SUPPORT_EMAIL`
- `SUPPORT_KVKK_EMAIL`
- `SUPPORT_PHONE`
- `SUPPORT_KEP`
- `SUPPORT_RESPONSE_SLA_HOURS`
- `SUPPORT_DATA_DELETION_URL`

For GPU nodes:

- `ENGINE_ENABLE_GPU=true`
- `ENGINE_ORT_RUNTIME=gpu` (build arg)
- `ENGINE_ORT_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider`
- `ENGINE_ORT_ALLOW_CPU_FALLBACK=true`

Start conservatively, then load-test and increase step by step.

Async media processing stack includes RabbitMQ in this compose topology.
Backend submit endpoints enqueue jobs; workers consume queue and clients poll `/api/v1/media/jobs/{id}/status`.

Go/no-go thresholds and benchmark volume can be tuned via:

- `PREFLIGHT_BENCH_*`
- `PREFLIGHT_GO_*`
