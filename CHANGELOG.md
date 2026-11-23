# Değişiklik günlüğü / Changelog

## 0.4.0 — 2026-11-23

İlk herkese açık sürüm. / First public release.

- **PyPI paket adı `matriks-mask`** (`pip install matriks-mask`). Python modülü (`matriks_pii`), guardrail yolu
  (`matriks_pii.guardrail.TurkishPIIGuardrail`), ortam değişkenleri (`MATRIKS_PII_*`) ve metrik adları değişmedi.
  Eski `matriks-pii` kurulu bir ortamda **önce `pip uninstall matriks-pii`**, sonra `pip install matriks-mask`
  (iki dağıtım aynı dosyaları sahiplenir; sonradan eskisini kaldırmak yeni kurulumu bozar).
- LiteLLM guardrail'i: istek sağlayıcıya gitmeden önce kişisel verileri yer tutucularla maskeler, yanıtta (akış dâhil)
  geri çevirir; ünlü uyumuna göre Türkçe ek onarımı.
- 34 temel varlık (TCKN, VKN, IBAN, Troy dâhil kartlar, telefon, plaka, MERSİS, adres, ad-soyad, gizli anahtarlar…;
  kontrol basamağı ve bağlam doğrulamalı) + KVKK m.6'daki 12 özel nitelikli veri kategorisi (kişiye bağlılık şartıyla).
- `balanced` / `strict` / `minimal` profilleri; `extra_regex`, `allow_list`, `deny_list`; isteğe bağlı Türkçe NER.
- Chat/Completions, Embeddings, Responses API, Anthropic Messages, Gemini native; tool çağrıları ve JSON içerik.
- Fail-closed varsayılanlar, değersiz loglama ve denetim izi, Prometheus metrikleri, AES-GCM şifreli Redis oturum
  deposu, kurulum doğrulaması (`selftest`).
- `matriks-pii` komutu (diğer adı `matriks-mask`): `mask` (LiteLLM olmadan maskeleme; `--profile`, `--config`,
  `--json`), `selftest`, `keys`.
- Kuruma özel tanımlar: README'de ayrı bölüm; `examples/sektor/` altında finans, havayolu, sağlık, sanayi,
  e-ticaret/kargo, telekom ve yurt dışı örnek dosyaları, her biri kendi ölçüm kümesiyle test edilir.
- Lisans: kod Apache-2.0; paketteki üçüncü taraf veri dosyaları için `THIRD_PARTY_NOTICES.md`.

İç sürümler (0.1.0 – 0.3.3) ayrı paket olarak yayımlanmadı; içerikleri bu sürümdedir. GitHub'daki 0.3.3'e göre
değişenler:

- URL kodlu (`ayse%40example.com`, `0532%20123…`; Outlook SafeLinks gibi) ve HTML varlıklı (`&#64;`) değerler çözülmüş
  bir kopyada taranır, orijinal kodlu aralık maskelenir; yanıtta orijinal kodlamayla geri çevrilir. Türkçe yüzde yazımı
  ("%40 arttı") çözülmez. Kodsuz metinde tespit değişmez.
- XML/HTML etiketli parola (`<Password>…</Password>`, `<şifre>`, `<pwd>`) `SIFRE` olarak yakalanır.
- Tireli hesap no (`0012345-678`) artık tek değer olarak maskelenir (önceden `-678` açıkta kalıyordu).
- `strict` profilde bağlamsız tarih kuralı zaman damgalarını (`2026-11-20 14:32`, `…T09:15`) ve gelecekteki tarihleri
  doğum tarihi saymaz (log trafiğinde yanlış pozitif).
- `extra_regex` için `group` alanı (yalnız yakalama grubu maskelenir). `context` artık büyük/küçük harf ve Türkçe harf
  duyarsızdır (önceden `reçete`, `PNR` gibi bağlamlar katlanmış metinde hiç eşleşmiyordu). `extra_regex` kullanan
  config'lerde `config_hash` değişir.
- `selftest --corpus` hatalı girdide yığın izi yerine biçimi anlatan kısa bir ileti verir (çıkış kodu 2).
- Tek sayıdan oluşan tool argümanında (`"arguments": "1.52e+274"`) sayı içindeki değer maskelenince JSON bozuluyordu;
  artık JSON metni olarak geçerli kalır (özellik testi buldu).
