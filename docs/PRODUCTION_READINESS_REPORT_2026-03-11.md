# Production Readiness Report (2026-03-11)

Bu rapor Backdroply multi-repo setup'i icin teknik readiness denetimi sonucudur.

## Kapsam

- backdroply-web
- backdroply-backend
- backdroply-engine
- backdroply-mobile
- backdroply-infra

## Calistirilan Dogrulamalar

### Web

- `npm ci`
- `npm run build`
- `npm audit --omit=dev`
- Sonuc: build basarili, audit 0 vulnerability.

### Backend

- `mvn -B test` (Docker Maven image)
- `mvn -B org.cyclonedx:cyclonedx-maven-plugin:2.9.1:makeBom`
- `osv-scanner scan source --sbom target/bom.json`
- Sonuc: 27 test gecti, OSV bulgu yok.

### Engine

- `pytest -q` (Docker Python 3.12 trixie)
- `pip-audit -r requirements.txt` (Docker Python 3.12 trixie)
- Sonuc: 6 test gecti, bilinen Python dependency vulnerability yok.

### Mobile

- `npm install`
- `npm run doctor`
- `npx expo install --check`
- `npm audit --omit=dev`
- `npm run build:android:release`
- Sonuc: doctor 17/17, dependency check temiz, release APK build basarili.

### Full Stack E2E

- `powershell -ExecutionPolicy Bypass -File infra/scripts/full-e2e.ps1 -EnvFile tmp-integration/.env.e2e`
- Probe kapsami:
  - unauthorized access guard
  - authenticated profile fetch
  - image process + download
  - video process + download
  - frame extraction
  - malicious payload block
  - concurrent processing limit (max 1 image + 1 video class)
  - my-media retention cap (10)
  - history endpoint
  - account deletion flow
- Sonuc: tum probe adimlari gecti.

### Container Image Security (Trivy, OS paketleri)

- `web-prod`: HIGH/CRITICAL = 0
- `backend`: HIGH/CRITICAL = 0
- `engine`: HIGH = 2, CRITICAL = 0
  - kalan bulgu: `CVE-2026-0861` (`libc-bin`, `libc6`)
  - not: upstream fix cikinca base image refresh gerekecek

## Uygulanan Sertlestirmeler

- Engine base image `python:3.12-slim-bookworm` -> `python:3.12-slim-trixie`
- Backend AWS SDK zincirinde `apache-client` transitifi dislanip `url-connection-client` eklendi (`commons-logging` yolu kaldirildi)
- Mobile Expo patch mismatch giderildi:
  - `expo ~55.0.6`
  - `expo-auth-session ~55.0.8`
  - `jsEngine` -> `hermes`
- Infra'ya tekrar-edilebilir full E2E scripts eklendi:
  - `infra/scripts/e2e_full_probe.py`
  - `infra/scripts/full-e2e.ps1`
  - `go-live-preflight.ps1` icine `-RunFullE2E` secenegi eklendi

## Lisans Ozeti

- Web: copyleft zorunlu lisans tespit edilmedi (agirlikli MIT/Apache/BSD)
- Mobile: bir dual-license bagimlilik var (`node-forge`: `BSD-3-Clause OR GPL-2.0`), BSD yolu secilebilir
- Engine: copyleft zorunlu lisans tespit edilmedi
- Backend: transitif olarak LGPL/ClassPath-Exception lisansli bilesenler var (Java ekosisteminde yaygin), ticari yayin oncesi hukuk kontrolu onerilir

## Go/No-Go Karari

Teknik olarak pre-production asamasina gecis icin **GO (kosullu)**:

- Core akislarda kritik teknik bloklayici bulunmadi.
- Kalan teknik risk: engine image tarafinda 2 adet HIGH (upstream fix bekleyen glibc CVE).
- Launch oncesi zorunlu operasyonel adimlar:
  1. Production `.env` gercek secret/OAuth/payment degerleri ile doldurulup `go-live-preflight` calistirilmali.
  2. Fiziksel Android/iOS cihazlarda smoke + crash-free test matrix tamamlanmali.
  3. Hukuki/ticari model (fatura/odeme/kvkk/aydinlatma) icin final legal review alinmali.
