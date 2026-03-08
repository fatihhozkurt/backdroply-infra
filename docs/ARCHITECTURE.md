# Architecture

## High-level

1. `web` (React)
   - Landing + onboarding + studio
   - Google ID token alir
   - Backend API ile token wallet / job workflow
2. `backend` (Spring Boot)
   - Google ID token dogrular
   - Kendi JWT tokenini uretir ve HttpOnly cookie olarak set eder
   - Quota + token muhasebesi + history + billing hook
   - Engine servisine multipart request proxy eder
3. `engine` (FastAPI + rembg/OpenCV/ffmpeg)
   - Upload validation (type/size/duration/suspicious-content)
   - AI segmentation pipeline
   - Brush mask keep/erase uygulamasi
   - Transparent/solid background output

## Security Boundaries

- `engine` endpointleri `X-Engine-Token` ile korunur.
- `backend` endpointleri JWT gerektirir (`/auth/google` ve `/billing/webhook` haric).
- Dosya adlari sanitize edilir.
- Maksimum dosya boyutu/sure ile donanim korumasi uygulanir.

## Data Model

- `users`
  - `google_sub`, `email`, `full_name`, `token_balance`, `language`
- `jobs`
  - medya tipi, kalite, token maliyeti, qc bilgisi, engine job id
- `purchase_requests`
  - paket, tutar, token, webhook/provider referansi, durum

## Processing Strategy

- Model fuzion: `u2net_human_seg + u2net`
- Border analiz + connected background suppression
- Temporal foreground lock (video)
- GrabCut refinement
- QC suspicious frame analizi
- Ultra modda coklu pass ve en iyi sonucu secme
