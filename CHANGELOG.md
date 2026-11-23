# Değişiklik günlüğü

## 0.3.3 — 2026-11-05

Herkese açık yayın hazırlığı. Tespit, maskeleme ve geri çevirme davranışı değişmedi.

- **Lisans Apache-2.0** (önceki taslakta MIT): `LICENSE`, `NOTICE` (telif sahibi Matriks Finansal Teknolojiler A.Ş.,
  marka notu, üçüncü taraf veri atıfları), `THIRD_PARTY_NOTICES.md` (trnames ve turkiye-api MIT metinleri, FrequencyWords
  `tr_50k` için CC BY-SA 4.0 atfı). Paket lisans ifadesi `Apache-2.0 AND MIT AND CC-BY-SA-4.0`; lisans dosyaları wheel'e
  girer. Derleme için setuptools ≥ 77 gerekir (pip bunu derleme ortamına kendisi kurar).
- Sözcük listesi (`tr_words.txt`, CC BY-SA 4.0) artık başka bir veri dosyasının üretiminde kullanılmıyor: "hem ad hem
  sözcük" seçimleri (`rare_word_*_tr.txt` ve `common_words_tr.txt`'nin listeden türetilen kısmı) pakette tutulmaz,
  çalışma anında hesaplanır. Yerlerine yalnız trnames'ten üretilen `frequent_first_names_tr.txt`,
  `frequent_last_names_tr.txt` geldi; `last_names_tr.txt` tüm soyadları içerir. Hesaplanan kümeler öncekiyle birebir aynıdır.
- README: "KVKK uyumlu" yerine "KVKK uyum süreçlerini destekleyen"; tespit garantisi olmadığı, veri sorumluluğu ve
  Matriks'e veri gönderilmediği notları; marka notu; başka ürünlerle karşılaştırma tablosu kaldırıldı; KVKK rehberlerinin
  tam adları.
- Paket metadata'sı: yazar, GitHub adresleri, sınıflandırıcılar, `py.typed`.
- `SECURITY.md`, `CONTRIBUTING.md`, `.dockerignore`, GitHub CI izinleri.
- Test fixture'larındaki gerçekçi görünen sahte anahtarlar açıkça sahte (`EXAMPLE`) değerlerle değiştirildi.
- Test verisinde gerçek bir kişiye ait olabilecek değerler ayrılmış örnek değerlerle değiştirildi: ücretsiz e-posta
  sağlayıcılarındaki ad.soyad adresleri `example.com/.net/.org` (RFC 2606), Türk İSS bloklarındaki genel IP'ler belgeleme
  adresleri (RFC 5737). `extra_regex` örneği nötr `KURUM_LISANS` adını kullanır.
- `examples/custom_callbacks.py` (kullanılmayan test yardımcısı kopyası) kaldırıldı.
- `examples/Dockerfile` resmî LiteLLM 1.106.x imajında derlenmiyordu (imajda pip ve `useradd` yok); `ensurepip` ve
  BusyBox `adduser` ile düzeltildi.

## 0.3.2 — 2026-11-05

Test ortamındaki denemelerden çıkan düzeltmeler.

- **Breaking — SIFRE varsayılanı BLOCK → MASK:** şifre LLM'e `<SIFRE_1>` olarak gider, yanıtta `****` görünür
  (geri yükleme yok, uzunluk da sızmaz); istek reddedilmez. `strict` profil BLOCK'ta kalır. Eski davranış:
  `entities: {SIFRE: BLOCK}`.
- **Yer tutucu talimatı:** `placeholder_instruction: system_suffix` metni yenilendi. Model yer tutucuyu gerçek değer gibi
  kullanır, değeri tekrar etmesi istenirse yer tutucuyu yazar, maskelemeden ve veriyi göremediğinden söz etmez,
  yer tutucuyu kısaltmaz. (Model "numaranız bana `<TCKN_...>` olarak ulaşıyor" gibi yanıtlar veriyordu.)
- **Geri çevirme:** markdown kaçışlı biçimler (`<KISI\_1>`, `\<KISI_1\>`, `\[KISI_1\]`) ve numarasız genel biçim
  (`<TCKN_...>`, `<TCKN_…>`, `<TCKN_X>`, `<TCKN_N>`) geri çevrilir. Genel biçim yalnız o etikette tek değer varsa
  çevrilir; birden çok değer varsa olduğu gibi kalır ve `unresolved` sayılır. Akışta da geçerli.

## 0.3.1 — 2026-11-05

Test ortamında (arka plan işleri ve sohbet) görülen SIFRE yanlış pozitiflerinin düzeltmesi.

- **SIFRE:** parola alanından sonraki değer artık yalnız rakam veya sembol içeriyorsa sır sayılır. Yalnız harften oluşan
  sözcükler ("password is never printed", "password: hashed", "Password: string", "şifre: yok"), yer tutucular (`***`,
  `<redacted>`, `${...}`, `{password}`, `%s`), değişken ve ortam değişkeni adları (`self.password`, `DB_PASSWORD`,
  `os.getenv(...)`) ve teknik terimler (`sha256`) engellenmez. `Şifre: Gizli123!`, `pwd=P@ss-w0rd`, `PIN kodu 5321`
  engellenmeye devam eder. Regresyon seti: `tests/test_sifre_fp.py`.
- **Embedding:** `/embeddings` isteğinde BLOCK aksiyonlu varlık (ör. SIFRE) isteği reddetmez; değer maskelenip istek
  geçirilir (embedding metin döndürmez). Sayaç: `events_total{event="blocked_masked_embedding"}`.

## 0.3.0 — 2026-10-28

Üretim hazırlık incelemesinin tamamı. 0.1.1 ile 0.2.1 arası ayrı paket olarak yayımlanmadı; içerikleri bu sürümdedir.
Aşağıdaki alt bölümler kademeli açılabilecek aşamalardır; her aşamanın açma/kapama bayrağı bölüm içinde yazılıdır.
Kademeli yayın (gölge mod → canary → tümü) ve kapıların `scripts/rollout_report.py` ile ölçümü: `docs/RUNBOOK.md`.
`tests/e2e/test_rollout_rehearsal.py` bu kapıları gerçek proxy üzerinde holdout-2 trafiğiyle prova eder.

### Doğrulama (2026-10-28)

- `pytest -q`: 2284 geçti (0.1.0: 1323). e2e 27 test, dört ayrı proxy yığını: temel, mesaj logu kapalı, işletim, kademeli yayın provası.
  Benchmark 8, dış veri seti, NER ve `redis_live` (gerçek Redis 7 kapsayıcısı) geçti. `corpus_report` ve selftest geçti.
- 0.3.0 wheel'i temiz bir sanal ortama LiteLLM 1.106.5 ile kuruldu. Kurulu paket üzerinde tüm kapılar
  geçti: `tests/test_smoke.py`, birim test paketi ve e2e dâhil 2321 test, benchmark, dış veri seti, `redis_live` (gerçek Redis 7),
  NER (torch 2.14.1 CPU + transformers 5.21.0, gerçek model), `corpus_report`, iki örnek config ile selftest ve holdout-2
  `--corpus` ölçümü.
- Biçimler arası eşdeğerlik matrisi `tests/test_parity.py` (5 biçim × 15 özellik).
- Yeni negatif tuzaklar NEG-531…588 (toplam 588; varsayılan sözlük modunda FP = 0).
- Kör holdout-2 (345 satır, uygulama kodundan bağımsız yazıldı): `balanced` F2 0.938 → genel düzeltmeler sonrası 0.993.
- Dış veri seti (turkish-pii-masking-benchmark, `strict`): P 0.978 R 0.944 F2 0.950 (poliçe no ve koordinat artık
  kapsamda olduğu için payda büyüdü).
- 2 KB gecikme p50 ≈ 2.9 ms (0.1.0: 2.6 ms; yeni tanıyıcılar dâhil).

### Değişen test beklentileri

- KISI-046 (`AHMET'İN` artık tespit edilir), UNICODE-009 (tam genişlik TCKN tespit edilir), REVERT-024 ve
  `test_engine` (`17291716060'ın`), NEG-114 ve NEG-477 metinleri, `test_session_missing_returns_none` →
  `…_closed_raises` + `open` varyantı, oturum tekrar oynatma (replay) testi 500 bekler.

### Geri alma

Wheel ve config birlikte 0.1.0'a döndürülür. Yalnız wheel geri alınırsa yeni anahtarlar 0.1.0'da başlangıç hatası verir;
acil durumda `MATRIKS_PII_IGNORE_UNKNOWN_KEYS=1`. Ayrıntı: `docs/RUNBOOK.md`, `docs/LITELLM_KURULUM.md` §9.3.

### 0.3.0 — Gemini native ve NER

- **Breaking:** Gemini native rotası (`/v1beta/models/*:generateContent`, `:streamGenerateContent`) artık geri çevrilir
  (`gemini_native: false` eski "yalnız maskele" davranışı).
- NER: cümle bazlı parçalama (`ner_max_chars`), çağrı başına zaman aşımı, `ner_fail_mode: closed|lexicon`,
  ön yükleme (`ner_preload`), ayrılmış iş parçacığı havuzu.
- Testler: 58 yeni negatif tuzak, kanca fixture'ları (çok turlu, config), özellik ve eşzamanlılık testleri, eşdeğerlik
  matrisi, holdout-2. CI: Python 3.10–3.13, Windows, gerçek Redis, wheel kurulumu, `pip-audit`, NER, selftest;
  `constraints/prod.txt`; Dockerfile sabit LiteLLM etiketi, root olmayan kullanıcı, `HEALTHCHECK`.
- Holdout-2'den çıkan genel düzeltmeler: bağlamsal kurallarda aynı değere birden çok bağlam uyarsa örtüşen ifadelerde
  özgül olan, ayrık ifadelerde değere en yakın olan kazanır ("MKK sicil no" ⊃ "sicil no"); marka bazlı kart uzunluğu
  (IMEI/SGK gibi Luhn'lu sayılar kart sayılmaz); öz-bildirim biçimleri ("diyabetim var") kişiye bağlıysa yakalanır;
  dil adı ("Kürtçe") etnik köken sayılmaz; koordinatta cümle sonu noktası.
- Denetim izi ve metriklerde varlık sayımı, proxy gövde kopyası (`proxy_server_request.body`) da maskelendiği için iki kat
  sayılıyordu; artık her oluşum bir kez sayılır (kademeli yayın provası buldu).
- `/completions` akışında (`choices[].text`) yer tutucular geri çevrilmeden istemciye gidiyordu; artık geri çevrilir
  (e2e ile doğrulandı).
- Akışta `__{label}_{n}__` biçiminde kapanış `__`'nin yeni açılış sanılması düzeltildi (özellik testi buldu).

### 0.2.1 — yeni varlıklar, allow/deny list

- **Breaking:** `GIZLI_ANAHTAR` yeni varsayılan MASK, yanıtta `****` (geri yüklenmez); `strict` profilde BLOCK.
- Yeni varlıklar `GIZLI_ANAHTAR`, `KONUM` (kişiye bağlı koordinat), `POLICE_NO`, `MKK_SICIL`, `ADRES_KODU`,
  `TICARET_SICIL` (varsayılan IGNORE); gizlenmiş e-posta (`ahmet [at] gmail.com`); `allow_list` / `deny_list`.
- Performans: tam genişlik denetimi tek regex, gizli anahtar desen tetikleyicileri, bağlam ön kontrolü.

### 0.2.0 — Türkçe tespit ve morfoloji

- **Breaking:** sayısal değerlerde ek onarımı: `<TCKN_1>'i` → `17291716060'ı` (ünlü uyumu sayının okunuşuna göre).
- "Ahmet YILMAZ", "YILMAZ Ahmet", "Mehmet Ali KAYA'ya".
- Küçük harfli sıradan sözcükler (ilaç, sigorta, portföy, yatırım…) artık önceki adı kurum sanmaz.
- Akrabalık/işlev sözcükleri (Eşim, Müşterimiz…) ada yapışmaz; aynı kişi tek yer tutucu alır.
- "AHMET'in", "Ahmetin", "Ad: ahmet".
- Kırsal adres çapaları (Köyü, Mevkii, Kyü., Mvk., Beldesi), Bulv., P.K., "Cad. + no + ilçe";
  unvanlar (Öğr. Gör., Dt., Psk., Kaymakam, Vali…) ve "nine/dede".
- Tireli çift soyad, "Ahmet ve Ayşe", sekme ayracı, "oğlu/kızı", "Sayın A. Yılmaz", "imza: A. Yılmaz", küçültme ekleri.
- Sendika/kurum üyeliği span'i kişi adını yutmaz; "hepatit B taşıyıcısı" sağlık; Rehber 2025 terim eksikleri
  (gebe, bağımlılık, Down sendromu, intihar girişimi, protez…; mezhep/tarikat; Rotary; tesettürlü; "ehliyetine el konuldu").
- 0812, "numarasından" bağlamı ve kayıt numarası koruması, harf O ile sıfır; JCB/Diners; MERSİS ofseti; pasaport
  7 hane/boşluklu; eski nüfus cüzdanı; noktalı TCKN; TR'siz etiketli IBAN; 2 haneli yıl; küçük harf plaka; tam genişlik rakamlar.
- Damak l'si (Kemal'e, Celal'i, Hilal'e); `â → e`, `û → ü`.
- Geçmiş/rivayet kopulası (`'ydi`, `'ymış`), 3. tekil iyelik, `-ki` + belirtme.
- BÜYÜK değer → BÜYÜK ek (`AHMET'İN`); küçük değerde BÜYÜK ek küçülür.
- Rakamla biten değerlerde ek onarımı ("No: 5'te", "100'de").
- `<KISI_01>`, `<KISI _1>`, `<PERSON_1>` (`label_aliases`, yalnız parantezli), apostrofsuz ek
  (`suffix_repair_attached`, varsayılan kapalı).
- Yanıt içeriğindeki JSON metnin girintisi korunur (`response_json_preserve_format`).

### 0.2.0-rc — işletim

- `dry_run: true` gölge modu: istek değişmez, `would_mask` / `would_block` sayımları loglanır.
- Prometheus metrikleri (`matriks_pii_*`, çoklu süreç uyumlu, etiketlerde değer yok) — `pip install "matriks-pii[metrics]"`.
- `python -m matriks_pii.selftest` (`--quick`, `--json`, `--probe`, `--corpus`): Kubernetes `startupProbe` ve CI için.
- `docs/RUNBOOK.md` (hata kodları, metrik uyarıları, rotasyon, kademeli yayın, geri alma),
  `docs/KVKK_VERI_KATEGORILERI.md` (varlık → VERBİS kategorisi → KVKK maddesi).

### 0.1.1 — güvenlik ve dayanıklılık düzeltmeleri

- **Breaking:** oturum bulunamazsa `revert_fail_mode: closed` (varsayılan) ile yanıt HTTP 500
  `matriks_pii_session_missing` ile reddedilir; önceden yer tutuculu yanıt istemciye gidiyordu.
- **Breaking:** depo erişilemezse PII içeren istek HTTP 503 `matriks_pii_store_unavailable` alır; PII içermeyen
  istek depoya hiç dokunmaz ve geçer. Redis'te 3 ardışık hatada devre 10 sn açılır.
- **Breaking:** boyut sınırı: `max_text_chars` / `max_request_chars` aşılırsa HTTP 413 `matriks_pii_text_too_large`
  (fail_mode'dan bağımsız; metin ham gitmez).
- **Breaking:** yapılandırma doğrulaması: sayısal sınırlar (`ttl_seconds ≥ 60`, `holdback_max_chars 16..512`,
  `context_window 1..500` …), bilinmeyen varlık adı ve yanlış tipte sır başlangıçta hata verir; iletiler değer içermez.
- **Breaking:** varsayılanlar `session_store.max_sessions` 100.000 → 10.000; `analysis_cache.ttl_seconds` 600 → 300;
  `config_hash` değişir, sırlar ve `redis_url` artık hash'e girmez; asgari LiteLLM 1.106.1 (1.106.1 ve 1.106.5 ile test edildi).
- Ham SSE baytlarında artımlı UTF-8 çözücü; çok baytlı karakterin ortasından bölünen parçalarda yer tutucu sızıntısı
  kapandı. CRLF tampon düzeyinde normalize edilir.
- `apply_guardrail` kendi değersiz kaydını yazar (`records_own_guardrail_information`); istisna metni loglara gitmez.
- Desteklenmeyen çağrı yolu da fail-closed ve maskeli hata.
- Redis: bağlantı/soket zaman aşımı, atomik `GETDEL`, şifre çözme hatasında `None`, `require_tls`,
  `encryption_key_previous` ve `session_secret_previous` ile kesintisiz sır rotasyonu.
- Düz metin sır uyarısı (`MATRIKS_PII_STRICT_SECRETS=1` ile hata); `MATRIKS_PII_IGNORE_UNKNOWN_KEYS=1` acil geri
  alma kapısı; `MATRIKS_PII_DEBUG_TRACEBACK` `LITELLM_MODE=PRODUCTION`'da yok sayılır.
- Hmac yer tutucu çakışmasında kimlik 6 → 8 → 10 → 12 karaktere uzar; `<KISI_01>` geri çevrilir.
- Önbellekte toplam span sınırı, 64 KB üstü metin önbelleğe girmez; ayrılmış analiz havuzu
  (`analysis_threads`); audit dosyası açık tutulur, yazma hatası hız sınırlı loglanır, skor kovaları eklenir.

## 0.1.0 — 2026-10-28

- İlk sürüm: LiteLLM `CustomGuardrail` (`matriks_pii.guardrail.TurkishPIIGuardrail`).
- 28 temel varlık + 12 KVKK m.6 özel nitelikli veri kategorisi; checksum (TCKN, VKN, IBAN mod-97, Luhn+BIN, Troy, IMEI).
- Türkçe ad tespiti: 7k ad / 23.9k soyad sözlüğü, bağlam, apostrof ve bitişik ek çözümleme, kurum adı dışlaması.
- Geri çevirme: biçimden türetilen yer tutucu tanıma, LLM bozulmalarına dayanıklılık, ünlü uyumuna göre ek onarımı.
- Streaming: choice/alan bazlı tampon (≤48 karakter), usage parçası sıralaması, finish_reason'sız akış sonu.
- Chat, completions, embeddings, Responses API, Anthropic Messages; tool çağrısı JSON argümanları.
- Değersiz loglama, proxy log/spend log maskeleme (`mask_logs`), JSONL denetim izi, fail-closed varsayılan.
- Bellek (TTL+LRU) ve AES-GCM şifreli Redis oturum deposu; `sequence` ve `hmac` yer tutucu kimlikleri.
- Testler: 497 pozitif/karışık + 530 negatif fixture, hypothesis özellik testleri, kanca testleri, gerçek proxy ile e2e.

### 0.1.0 — son inceleme düzeltmeleri

- BLOCK ve fail-closed yolunda istek, hata loglarına düşmeden önce maskelenir/temizlenir.
- `skip_system_message_in_guardrail` artık istek gövdesinden okunmaz (istemci sistem mesajı maskelemesini kapatamaz).
- JSON sayıları, JSON anahtarları, `\u` kaçışlı JSON, istekteki `reasoning_content`, Responses `prompt.variables`,
  `reasoning`/`custom_tool_call_output`/`mcp_*` öğeleri, Anthropic `document`/`search_result` blokları maskelenir.
- Desteklenmeyen çağrı türleri (rerank, görsel, ses, MCP) varsayılan olarak maskelenir (`unsupported_call_types`).
- Akışta tool argümanları JSON kaçışlı geri çevrilir; Responses API olayları ve Anthropic ham SSE geri çevrilir.
- Oturum kimliği HMAC imzalı; aynı istekte ikinci pre-call (vector store) mevcut oturumu sürdürür; başarısız çağrıda oturum silinir.
- Log maskelemede bu isteğin bilinen değerleri kesin olarak değiştirilir; `served_output_texts` ve senkron `logging_hook` kapsandı.
- İmzalı Anthropic `thinking` bloklarına dokunulmaz.
- O(n²) noktalar (çakışma ayıklama, maske birleştirme, cümle/span arama) ve geri izlemeli regex'ler doğrusallaştırıldı.
- Bağımsız değerlendirme kümesinden çıkan genel iyileştirmeler: küçük harfli ad-soyad, form/JSON alan bağlamı, apostroflu
  özel ad kanıtı, modern adlar, ülke/tarihî kişi listesi, gruplu TCKN, ayraçsız telefon kuralı, tarih/sürüm bağlamları.
- İkinci inceleme turu: oturum jetonu çağrı kimliği + API anahtarına bağlandı (başka isteğe kopyalanamaz);
  desteklenmeyen çağrıda `block` öncesi maskeleme; log değer önbelleği yalnız `mask_logs` açıkken, 60 sn TTL ve süpürmeli;
  NaN/Infinity içeren JSON çökmez; istekte sayı olan alan yanıtta sayı olarak geri yüklenir; CRLF ayraçlı SSE;
  tuple log alanları ve aynı çağrının tekrar loglanması maskelenir.
- `scan_response` (yanıtta LLM'in ürettiği yeni PII maskelenir; strict profilde açık), HF NER adaptörü testleri
  (sahte pipeline + gerçek `akdeniz27/bert-base-turkish-cased-ner` modeli), surrogate modu gerekçesiyle v2'ye ertelendi.
- Dış veri setleriyle ölçüm (`scripts/external_bench.py`, `pytest -m external`): turkish-pii-masking-benchmark strict
  F2 0.651 → 0.958, Werea-KVKK-Bench P=1.000 F2 0.606 → 0.677. Genel iyileştirmeler: `checksum_policy: context`
  (strict profilde; etiketli ama kontrol basamağı hatalı TCKN/VKN/IBAN/KART/IMEI), yazıyla yazılmış sayılar
  (`number_words`), form alanı + değer kuralları ("etnik köken alanı …", "adli kaydı …"), sendika adları (`…-Sen`, `…-İş`),
  kan grubu, nadir ad-soyad çiftleri, gruplu SGK/hesap no, ehliyet harf öneki, TRON cüzdanı, iki noktasız şifre ifadeleri.
- Performans: önek ağacı regex'leri (özel kategori terimleri, kurum adları), bağlamsız kural atlaması, ek soyma için
  küme araması — 2 KB p50 3.1 → 2.5 ms; `_UNION_NAME` geri izlemesi sınırlandı (patolojik "Ahmet "×20000 girdisi < 2 s).
- Fixture tabanlı kanca senaryoları (`tests/fixtures/hooks/`, 46 senaryo), `scripts/build_org_names.py` (isteğe bağlı KAP
  unvan listesi), e2e: özel kategori LOG sayımı `guardrail_information`'da ve fail-closed'da sağlayıcıya istek gitmemesi.
- Çoklu worker/replika: `session_secret` ve `session_store.encryption_key` yapılandırma alanları (`os.environ/…` destekli);
  `redis` deposunda ikisi de zorunlu (eksikse proxy başlamaz); `python -m matriks_pii.keys` sır üretici; sırlar
  `config_hash`'e girmez. Önceden sır modül düzeyinde süreç başına rastgele üretiliyordu ve ayrı süreçlerde oturum doğrulanamazdı.
