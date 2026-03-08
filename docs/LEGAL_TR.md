# Turkiye Hukuki Notlar (SaaS + Token + Odeme)

Bu dosya teknik ekip icin yol haritasidir; hukuki danismanlik degildir.

## 1) Fatura / Dekont Konusu

- Vergi Usul Kanunu kapsaminda fatura duzeni vergi mukellefiyetiyle baglantilidir.
- Sirket/vergisel mukellefiyet olmadan "resmi e-fatura" sureci yurumez.
- Bu nedenle uygulamada "odeme dekontu/receipt" dili kullanildi.
- Resmi fatura/e-fatura icin mali mustavir + vergi kaydi + uygun e-belge altyapisi gerekir.

## 2) Odeme Hizmeti ve Lisans

- 6493 sayili Kanun kapsaminda odeme hizmetleri regule alandadir.
- Uygulamanin dogrudan lisanssiz odeme hizmeti sunmasi yerine lisansli PSP ile calismasi gerekir.
- Bu projede odeme akisina webhook + intent iskeleti eklendi; canliya cikis oncesi lisansli PSP ile kontrat sarttir.

## 3) Mesafeli Satis ve Tuketici Yuku

- Dijital hizmet satista mesafeli sozlesme, on bilgilendirme, iade/iptal kosullari ve acik metinler zorunludur.
- Kullaniciya kalite taahhudu "best effort" olarak yazilmali, teknik sinirlar acik belirtilmelidir.

## 4) KVKK / Cerez

- Cerez ve analitik kullaniminda aciklatma metni + gerekli durumlarda acik riza/tercih yonetimi gerekir.
- Uygulamada cookie consent banner akisi bulunur; production'da KVKK uyumlu detayli metinler eklenmelidir.
- Hesap silme / veri silme talebi icin self-service endpoint veya destek kanali sunulmalidir.

## 5) Sorumluluk Sinirlama (Background Remove %100 Garantisi)

- Kullanici sozlesmesine:
  - modelin olasiliksal calistigi
  - her frame/senaryoda mutlak sonuc garanti edilmedigi
  - teknik limitler ve kullanici dosyasina bagli degiskenlik
  maddeleri eklenmelidir.

## Kaynaklar (Resmi)

1. TBMM / Vergi Usul Kanunu (213): https://www5.tbmm.gov.tr/kanunlar/k213.html
2. TCMB / 6493 sayili Kanun sayfasi: https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Temel+Faaliyetler/Odeme+Hizmetleri/6493+sayili+Kanun
3. TCMB / Elektronik para kuruluslari bilgilendirme: https://www.tcmb.gov.tr/wps/wcm/connect/tr/tcmb+tr/main+menu/temel+faaliyetler/odeme+hizmetleri/elektronik+para+kuruluslari/hakkinda
4. Ticaret Bakanligi / Tuketici mevzuat sayfasi: https://ticaret.gov.tr/tuketici-ve-piyasa-gozetimi/genel-mudurluk-mevzuat
5. KVKK / Cerez Uygulamalari Rehberi (PDF): https://kvkk.gov.tr/SharedFolderServer/CMSFiles/f0f0057d-7f78-4185-aea0-86c37f02f804.pdf
