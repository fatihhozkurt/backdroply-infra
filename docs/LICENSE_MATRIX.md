# License Matrix (Commercial Readiness)

Son guncelleme: 2026-03-11

Bu dokuman teknik lisans envanteridir; hukuki gorus degildir.

## Tarama Kaynaklari

- `backdroply-web/license-report.json` (npm license-checker)
- `backdroply-mobile/license-report.json` (npm license-checker)
- `backdroply-engine/license-report.json` (pip licenses export)
- `backdroply-backend/target/bom.json` (CycloneDX SBOM)

## Web (backdroply-web)

- Paket sayisi: 116
- Lisans profili: agirlikli MIT / Apache-2.0 / BSD / ISC
- Kritik copyleft (GPL/AGPL/LGPL): tespit edilmedi

## Mobile (backdroply-mobile)

- Paket sayisi: 597
- Lisans profili: agirlikli MIT / Apache-2.0 / BSD
- Not: `node-forge` lisansi `BSD-3-Clause OR GPL-2.0` (dual-license). Ticari kullanim icin BSD-3-Clause yolu secilebilir.
- Kritik copyleft (zorunlu GPL) tekil zorunluluk olarak tespit edilmedi; dual-license istisnasi manuel hukuki kontrolden gecirilmelidir.

## Engine (backdroply-engine)

- Paket sayisi: 56
- Lisans profili: MIT / Apache-2.0 / BSD
- Kritik copyleft (GPL/AGPL/LGPL): tespit edilmedi
- `rembg` ve ana Python bagimliliklari ticari kullanimda yaygin olarak uygun lisanslarla dagitilir.

## Backend (backdroply-backend)

- Bilesen sayisi: 149
- Lisans profili: agirlikli Apache-2.0 / MIT / BSD
- Dikkat edilmesi gereken transitif lisanslar:
  - `hibernate-core`: `LGPL-2.1-only`
  - bazi Jakarta artefaktlari: `GPL-2.0-with-classpath-exception`
- Bu lisanslar Java ekosisteminde yaygin olarak SaaS dagitiminda kullanilir; yine de ticari yayin oncesi hukuk danismani ile son kontrol onerilir.

## Model/Lisans Notu

- Segmentasyon agirliklarinin (u2net/u2netp/u2net_human_seg vb.) lisans metinleri deployment paketinde ve legal sayfalarda acikca belirtilmelidir.
- Model lisanslari upstream degisebileceginden release pipeline icinde periyodik tekrar kontrol gereklidir.

## Production Gate Onerisi

1. Her release'te SBOM + lisans raporu artifact olarak saklanmali.
2. Yasakli lisans politikasina (ornegin AGPL/GPL zorunlu copyleft) gore otomatik fail gate eklenmeli.
3. Attribution / third-party notices deployment paketine dahil edilmeli.
