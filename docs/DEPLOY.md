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
