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

## 6) Final Sign-Off Criteria

Launch is allowed only if all items below are true:

1. preflight script passes with production env file
2. all repository CI gates pass on `main`
3. OAuth and payment live tests pass
4. mobile matrix passes on physical devices
5. legal/privacy/cookie pages are published and linked
