# Security Checklist

- [x] JWT tabanli backend auth
- [x] Web cookie auth + CSRF token korumasi
- [x] Mobil auth icin ayrik token endpoint (`/auth/google/mobile`)
- [x] Google JWT JWKS imza dogrulamasi (issuer/audience/email_verified)
- [x] Engine internal token
- [x] CORS kisitlamasi
- [x] Proxy-aware secure cookie policy (`X-Forwarded-Proto`)
- [x] File type + magic sniffing
- [x] Script-like payload pattern bloklama
- [x] Video size/duration limiti
- [x] Eszamanli islem limiti (kullanici basina ayni anda max 1 image + 1 video)
- [x] Token consume/refund atomik akis
- [x] Webhook imza dogrulama (HMAC)
- [x] Webhook timestamp window + replay korumasi
- [x] Kalici webhook idempotency (DB event log + unique event_id)
- [x] Webhook event log retention + scheduler cleanup
- [x] Endpoint bazli rate limiting (auth/process/frame/webhook)
- [x] Download akisinda streaming transfer
- [x] Object storage icin opsiyonel SSE (AES256/KMS)
- [x] SMTP opsiyonel; yoksa bloklamaz
- [x] Strict startup gate (critical secret/OAuth/payment config fail-fast)
- [x] Multi-repo CI security gates (tests + dependency scan + image scan)

## Ek Oneriler (Production)

1. WAF + CDN + rate limiting (IP/user bazli).
2. Backend ve engine icin private subnet + zero trust network policy.
3. Secrets manager (Vault, AWS Secrets Manager, GCP Secret Manager).
4. SAST/DAST + dependency scanning CI pipeline.
5. Anti-malware (ClamAV/managed scanning) ve sandbox processing node'lari.
6. Audit log + SIEM entegrasyonu.

## Non-hackable Gercegi

Tamamen "hacklenemez" sistem teknik olarak garanti edilemez. Hedef:
- saldiri yuzeyini azaltmak
- hasar etkisini sinirlamak
- tespit + yanit suresini kisaltmak
