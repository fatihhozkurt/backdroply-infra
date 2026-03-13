# Deploy Profiles

## 1) Local

```bash
docker compose --profile local up --build
```

- Web dev: `http://localhost:5173`
- API: `http://localhost:8080`

## 2) Dev

```bash
docker compose --profile dev up --build
```

`dev` profili local ile aynidir; staging benzeri testler icin kullanilir.

## 3) Deploy

```bash
docker compose --profile deploy up --build -d
```

- `web-prod` nginx ile static build sunar.
- Backend ve engine container icinde calisir.
- Production'da TLS terminasyonu icin ters proxy (Nginx/Traefik/Cloud LB) ekleyin.

## Production-Like Local

```powershell
pwsh ./infra/scripts/prod-like-local-up.ps1 -EnvFile .env.production.local
```

Bu komut deploy profilini localde ayaga kaldirir (web-prod + backend + queue + storage).
Istege bagli olarak:

```powershell
pwsh ./infra/scripts/prod-like-local-up.ps1 -EnvFile .env.production.local -RunE2E -RunBenchmark
```

## .env Konfig Notlari

- `APP_*` degiskenleri backend ayarlari
- `ENGINE_*` degiskenleri AI motor limitleri
- `VITE_*` degiskenleri frontend build/runtime
- `APP_STRICT_STARTUP=true` ile backend production fail-fast config kontrolu yapar
- Eszamanli islem limiti backend tarafinda sabit: kullanici basina ayni anda max 1 image + 1 video
- `STORAGE_ENABLED=true` yaparsan `My Media` ciktilari MinIO/S3'e kalici kaydedilir

## Go-Live Gate

Deploy oncesi:

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production
```

Opsiyonel smoke:

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production -RunSmoke
```

Opsiyonel full E2E:

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production -RunFullE2E
```

`-RunFullE2E` artik benchmark + go/no-go kalite/perf kapilarini da calistirir.

Sadece benchmark/go-no-go:

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production -RunBenchmark
```

Otomatik tuning (profil taramasi + `.env.autotuned`):

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production -RunAutoTune
```

Windows PowerShell (pwsh yoksa):

```powershell
powershell -ExecutionPolicy Bypass -File .\\infra\\scripts\\full-e2e.ps1 -EnvFile .env.production
```

## Dagitik Mimari Plani

Auth + queue + k8s karar dokumani:

`docs/ARCHITECTURE_SCALE_PLAN.md`
