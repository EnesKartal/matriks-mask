# Test fixture'ları

**Tüm değerler sentetiktir.** TCKN, VKN, IBAN ve kart numaraları kontrol basamağı algoritmasıyla üretilmiştir; gerçek kişilere ait değildir. Ad/soyad örnekleri Türkiye'nin en yaygın adlarından rastgele birleştirilmiştir. SPK VII-128.10 m.25 gereği test ortamında gerçek müşteri verisi kullanılmaz.

| Dizin | İçerik | Üretim |
|---|---|---|
| `detect/` | Pozitif/karışık tespit senaryoları (`expect` listesi) | `python scripts/build_fixtures.py` |
| `negative/` | Yanlış pozitif tuzakları (`expect: []`) | elle (Python ile checksum doğrulamalı) |
| `revert/` | Yer tutucu varyantları ve ek onarımı | `scripts/build_fixtures.py` |
| `streaming/` | Akış bölme değişmezi için tam çıktılar | `scripts/build_fixtures.py` |

Sözleşme: `expect` = `engine.detected(text)` sonucunun `(entity, span.text)` çoklu kümesi (IGNORE aksiyonlu varlıklar hariç).
