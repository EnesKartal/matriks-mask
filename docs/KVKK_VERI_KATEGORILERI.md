# matriks-pii — KVKK veri kategorileri eşlemesi (hukuki görüş değildir)

Bu tablo VERBİS envanteri, aydınlatma metni ve veri koruma etki değerlendirmesi (DPIA) için hangi kişisel veri
kategorisinin eklenti tarafından nasıl ele alındığını gösterir. Varsayılanlar `profile: balanced` içindir.

| Varlık | VERBİS kategorisi | KVKK maddesi | Varsayılan | Yanıtta geri yükleme |
|---|---|---|---|---|
| `KISI` | Kimlik | m.5 | MASK | evet (ek onarımıyla) |
| `TCKN` (98/99 ile başlayan yabancı kimlik no dâhil) | Kimlik | m.5 | MASK | evet |
| `PASAPORT`, `KIMLIK_SERI`, `EHLIYET`, `NUFUS_KAYIT` | Kimlik | m.5 | MASK | evet |
| `DOGUM_TARIHI`, `DOGUM_YERI` | Kimlik | m.5 | MASK | evet |
| `TELEFON`, `EPOSTA` | İletişim | m.5 | MASK | evet |
| `ADRES`, `ADRES_KODU` | İletişim / Lokasyon | m.5 | MASK | evet |
| `KONUM` (kişiye bağlı koordinat) | Lokasyon | m.5 | MASK | evet |
| `IP`, `MAC` | İşlem Güvenliği | m.5 | MASK / IGNORE | evet |
| `IBAN`, `HESAP_NO`, `MUSTERI_NO`, `MKK_SICIL`, `POLICE_NO` | Finans / Müşteri İşlem | m.5 | MASK | evet |
| `KART`, `KART_SKT` | Finans | m.5 (PCI DSS) | MASK | yalnız son 4 hane |
| `KART_CVV` | Finans | m.5 (PCI DSS) | MASK | **asla** |
| `VKN`, `MERSIS`, `TICARET_SICIL` | Finans (şahıs işletmesinde kişisel veri) | m.5 | MASK / IGNORE (`TICARET_SICIL`) | evet |
| `SGK`, `ETTN`, `IMEI`, `SASI_NO`, `PLAKA`, `KRIPTO_CUZDAN` | Özlük / Müşteri İşlem / Fiziksel | m.5 | MASK (kripto: IGNORE) | evet |
| `SIFRE` | İşlem Güvenliği | m.12 | MASK (strict: **BLOCK**) | hayır (`****`) |
| `GIZLI_ANAHTAR` (API anahtarı, token, özel anahtar) | İşlem Güvenliği | m.12 | MASK (strict: BLOCK) | **asla** (`****`) |
| `OZEL_SAGLIK` | Sağlık Bilgileri | **m.6** | MASK | evet |
| `OZEL_GENETIK`, `OZEL_BIYOMETRIK` | Genetik / Biyometrik Veri | **m.6** | MASK | evet |
| `OZEL_CINSEL` | Cinsel Hayat | **m.6** | MASK | evet |
| `OZEL_CEZA` (kesinleşmiş mahkûmiyet, güvenlik tedbiri) | Ceza Mahkûmiyeti ve Güvenlik Tedbirleri | **m.6** | MASK | evet |
| `OZEL_CEZA_GENIS` (şüpheli, sanık, gözaltı — m.6 dışı ama hassas) | Hukuki İşlem | m.5 | LOG | — |
| `OZEL_DIN`, `OZEL_FELSEFI` | Felsefi İnanç, Din, Mezhep | **m.6** | LOG (strict: MASK) | evet |
| `OZEL_ETNIK` | Irk ve Etnik Köken | **m.6** | LOG (strict: MASK) | evet |
| `OZEL_SIYASI` | Siyasi Düşünce | **m.6** | LOG (strict: MASK) | evet |
| `OZEL_UYELIK` | Dernek / Vakıf / Sendika Üyeliği | **m.6** | LOG (strict: MASK) | evet |
| `OZEL_KIYAFET` | Kılık ve Kıyafet | **m.6** | LOG (strict: MASK) | evet |

Özel nitelikli veri yalnız **kişiye bağlı** olduğunda (aynı cümlede kişi/kimlik ya da 1./2. şahıs/müşteri işaretçisi)
sayılır (KVKK m.3/1-d). "Kanser araştırması yayımlandı" gibi haber cümleleri işaretlenmez. Kaynak: Kişisel Verileri
Koruma Kurumu, Özel Nitelikli Kişisel Veriler Rehberi (2025); Üretken Yapay Zekâ ve Kişisel Verilerin Korunması Rehberi (15 Soruda), 24.11.2025.

## Denetim izi (audit log)

- Biçim: günlük döndürülen JSONL (`<path>.YYYYMMDD.jsonl`), dosya tutamacı açık tutulur.
- Kayıt alanları: `ts, guardrail, guardrail_version, config_hash, event, litellm_call_id, session_ref (oturum kimliğinin
  karması), api_key_hash, user_id, team_id, model, call_type, stream, entities{varlık: sayı}, logged{varlık: sayı},
  actions, status, blocked, duration_ms, score_buckets{varlık: {skor kovası: sayı}}, dry_run, would_mask,
  session_missing, unresolved, replaced`.
- **Hiçbir kişisel veri değeri yazılmaz.** Yalnız tür, sayı ve meta.
- Saklama: süreyi kurum, kendi politikasına ve tabi olduğu sektör mevzuatına göre belirler (kayıtlar değer
  içermez).
- DPIA için kanıt: hangi tarihte, hangi API anahtarı/ekip için, hangi kategoriden kaç değerin maskelendiği/engellendiği,
  hangi yapılandırmayla (`config_hash`).

## Hatırlatma

Harita (yer tutucu ↔ değer) bellekte veya şifreli Redis'te tutulduğu sürece bu işlem **takma ad (kod) kullanımıdır,
anonimleştirme değildir**; veri sorumlusu nezdinde kişisel veri olmaya devam eder. Yurt dışındaki LLM sağlayıcısına istek
göndermek m.9 kapsamında aktarımdır; maskeleme riski azaltır, yükümlülüğü kaldırmaz (Standart Sözleşme + bildirim).
