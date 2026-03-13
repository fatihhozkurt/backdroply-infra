# Go-Live Gate

This document defines the minimum launch gate for Backdroply SaaS.

## 1) Automated Preflight (Required)

From `backdroply-infra` repo root:

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production
```

Optional full smoke run:

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production -RunSmoke
```

Optional full E2E flow run (recommended before production cut):

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production -RunFullE2E
```

`-RunFullE2E` includes benchmark + automatic GO/NO_GO checks by default.

Benchmark only:

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production -RunBenchmark
```

Auto-tune profiles and generate `.env.autotuned`:

```powershell
pwsh ./infra/scripts/go-live-preflight.ps1 -EnvFile .env.production -RunAutoTune
```

Or run only E2E flow:

```powershell
pwsh ./infra/scripts/full-e2e.ps1 -EnvFile .env.production
```

The script fails (`exit 1`) when critical config is unsafe:

- weak/placeholder JWT secret
- placeholder Google OAuth client id
- non-HTTPS origins
- missing payment keys / webhook secret
- weak engine shared token

## 2) CI Gates (Required)

Every repository must pass CI on `main`:

- `backdroply-backend`: maven tests + SBOM/OSV + Trivy image scan
- `backdroply-web`: build + npm audit + Trivy image scan
- `backdroply-engine`: pytest + pip-audit + Trivy image scan
- `backdroply-mobile`: expo doctor + web export + android release build
- `backdroply-infra`: docker compose config validation + docs presence check

## 3) Google OAuth Production Checklist

Google Cloud Console:

1. Configure consent screen (app name, support email, privacy URL, terms URL).
2. Add authorized JavaScript origins:
   - `https://app.backdroply.com`
   - `https://www.backdroply.com`
3. Add backend redirect/callbacks if your architecture uses them.
4. Ensure web/mobile client IDs are correctly mapped:
   - web: `VITE_GOOGLE_CLIENT_ID` and backend `GOOGLE_CLIENT_ID`
   - mobile: `expo.extra.googleWebClientId`, `googleAndroidClientId`, `googleIosClientId`

Validation:

- web sign-in succeeds without `origin_mismatch`
- mobile sign-in succeeds on Android + iOS

## 4) Payment and Receipt Checklist

1. Set live provider credentials:
   - `PAYMENT_PROVIDER_API_KEY`
   - `PAYMENT_PROVIDER_SECRET_KEY`
   - `PAYMENT_WEBHOOK_SECRET`
2. Configure HTTPS webhook endpoint and verify HMAC signature.
3. Run replay/idempotency tests for duplicate webhook events.
4. Confirm receipt email delivery with production SMTP.
5. Verify legal copy (receipt vs official invoice) is visible in UI and terms.

## 5) Mobile Launch Matrix

Run at minimum:

- Android 13/14 physical device: login, process image, process video, download output, account delete
- iOS 17+ physical device: same flow
- cold start + warm start + offline recovery scenarios
- invalid token / expired token scenario

Crash criteria:

- zero crash on first launch
- zero crash during Google sign-in
- zero crash during upload and download flows

## 6) TR Compliance Contact and Data Rights Checklist

Before launch:

1. Footer contains permanent links: Contact, Terms, Privacy, Cookies.
2. `/contact` page is public and contains:
   - support email
   - support form with ticket id
   - optional phone/KEP
   - response SLA text (for example 48 hours)
3. Purchase/plan UI shows support/refund/cancellation contact line.
4. Privacy policy contains explicit data subject channel (KVKK) and deletion request path.
5. Mobile store metadata includes support email + account/data deletion path.
6. Legal note is aligned with your business status:
   - if no registered company yet, avoid claiming official invoice issuance
   - when company is ready, integrate compliant e-invoice/e-archive flow

## 7) Final Sign-Off Criteria

Launch is allowed only if all items below are true:

1. preflight script passes with production env file
2. full E2E + benchmark gate returns GO
3. all repository CI gates pass on `main`
4. OAuth and payment live tests pass
5. mobile matrix passes on physical devices
6. legal/privacy/cookie/contact pages are published and linked
