# Mobile Roadmap (iOS + Android)

`apps/mobile` artik Google OAuth + backend JWT + secure token storage taban akisini icerir.

## Mevcut Durum

1. Google OAuth login (`expo-auth-session/providers/google`)
2. Backend `/api/v1/auth/google/mobile` entegrasyonu
3. Token saklama (`expo-secure-store`)
4. Oturum yenileme (`/users/me`) ve cikis
5. Hesap silme endpoint cagrisi

## Enterprise seviyesine cikmak icin:

1. Google OAuth PKCE akisini `expo-auth-session` ile canliya alin.
2. Video/image upload endpointlerini backend ile baglayin.
3. Job polling + download akisina dosya izinlerini ekleyin.
4. Arka planda upload ve resumable transfer (buyuk dosya) ekleyin.
5. Apple App Store ve Google Play policy kontrollerini tamamlayin:
   - privacy policy URL
   - account deletion policy
   - subscription/consumable bilgi metinleri
6. Crash + analytics + abuse detection ekleyin.

## Launch Test Matrix (Minimum)

1. Android physical device (13/14):
   - first launch
   - Google login
   - image process
   - video process
   - output download
   - account deletion
2. iOS physical device (17+):
   - same flow as Android
3. Failure scenarios:
   - invalid/expired token
   - backend unreachable
   - upload cancellation

Gate: launch only if all matrix checks pass without crash.

## Dagitim

- iOS: Apple Developer Program + bundle id + signing
- Android: Play Console + package id + signing key
- CI/CD: EAS Build veya Fastlane
