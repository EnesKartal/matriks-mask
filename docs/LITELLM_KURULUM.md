# matriks-pii — LiteLLM kurulum kılavuzu

Bu belge `matriks-pii` guardrail'inin bir LiteLLM proxy'sine nasıl kurulacağını, yapılandırılacağını ve doğrulanacağını
anlatır. Eklentinin ne yaptığı ve kalite ölçümleri için ana [README](../README.tr.md)'ye bakın.

Test edilen sürümler: **LiteLLM 1.106.1, 1.106.5 ve 1.110.2** (asgari 1.106.1), Python 3.10–3.13.

---

## 1. Kurulum

```bash
pip install "matriks-mask[fast]"
# main dalındaki en son sürüm
pip install "matriks-mask[fast] @ git+https://github.com/MatriksData/matriks-mask"
# veya yerel kopyadan
pip install "/yol/matriks-pii[fast]"
```

| Ek | Ne zaman |
|---|---|
| `fast` | Her zaman önerilir (çok kelimeli terim araması için `pyahocorasick`) |
| `redis` | Oturumların yeniden başlatmada korunması, bellek sınırının süreç dışına taşınması veya çok pod'da Admin UI guardrail testi (bkz. §5) |
| `ner` | Sözlük dışı/yabancı adları yakalamak için opsiyonel HF NER modeli (`transformers` + `torch`, ~500 MB) |

Paket, LiteLLM'in çalıştığı **aynı Python ortamına** kurulmalıdır. Docker için §7.

## 2. Asgari yapılandırma

`config.yaml`:

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: openai/gpt-4o
      api_key: os.environ/OPENAI_API_KEY

guardrails:
  - guardrail_name: matriks-pii
    litellm_params:
      guardrail: matriks_pii.guardrail.TurkishPIIGuardrail
      mode: [pre_call, post_call]   # İKİSİ DE zorunlu: pre_call = maskeleme, post_call = geri çevirme
      default_on: true              # tüm isteklerde çalışır
      profile: balanced             # strict | balanced | minimal

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY

litellm_settings:
  turn_off_message_logging: true    # önerilir (savunma derinliği)
```

Başlatma:

```bash
export PYTHONUTF8=1                 # Windows'ta zorunlu, Linux'ta zararsız
litellm --config config.yaml --port 4000
```

Notlar:

- `mode` listesinde `post_call` yoksa eklenti onu kendisi ekler ve uyarı yazar
  (`matriks_pii: mode listesine post_call eklendi`). Yine de config'de açıkça yazın: Admin UI/DB'den yönetilen
  guardrail'lerde LiteLLM bu alanı ezebilir.
- `mask_logs: true` (varsayılan) olduğunda eklenti `logging_only` kancasını da kendisi ekler; proxy'nin logladığı
  (geri çevrilmiş) yanıt kopyası yeniden maskelenir.
- Geçersiz **değerler** (ör. `profile: strik`, bilinmeyen aksiyon, hatalı `placeholder_format`) proxy'yi başlangıçta
  `ValueError` ile durdurur. Yanlış yazılmış bir **anahtar adı** (ör. `profil:`, `entites:`) ise LiteLLM'in kendi
  guardrail parametresi olabileceği için reddedilmez; LiteLLM'e iletilir ve ayar **uygulanmaz**. Başlangıç logunda
  `matriks_pii: tanınmayan parametreler (yazım hatası olabilir)` uyarısını kontrol edin.

### İstek bazında açma (`default_on: false`)

```yaml
      default_on: false
```

İstemci yalnız istediği çağrıda açar:

```json
{"model": "gpt-4o", "guardrails": ["matriks-pii"], "messages": [...]}
```

## 3. Profiller ve sık kullanılan ayarlar

| Profil | Ne yapar |
|---|---|
| `balanced` (varsayılan) | Kimlik/iletişim/finans verileri MASK; sağlık, genetik, biyometrik, cinsel hayat, ceza MASK; din, etnik köken, siyasi görüş, sendika vb. yalnız sayılır (LOG); `SIFRE` MASK, geri yüklemesiz (strict: BLOCK) |
| `strict` | Tüm KVKK m.6 kategorileri MASK; kripto/MAC/444 hatları MASK; LLM'e "yer tutucuları aynen kullan" talimatı; yanıtta yeni kişisel veri taraması; etiketli ama kontrol basamağı hatalı numaralar da maskelenir |
| `minimal` | Yalnız TCKN, VKN, IBAN, KART, TELEFON, EPOSTA, KISI |

Profil üzerine açık ayarlar yazılabilir:

```yaml
      profile: balanced
      entities:
        KART: {action: MASK, restore: false}  # yanıtta yalnız son 4 hane (PCI)
        SIFRE: BLOCK                           # istek reddedilir (HTTP 400); varsayılan MASK
        PLAKA: IGNORE
      special_categories:
        OZEL_SAGLIK: BLOCK
        OZEL_SIYASI: MASK
      placeholder_format: "__{label}_{n}__"   # <…> Markdown görüntüleyicide yutuluyorsa
      fail_mode: closed                        # guardrail hata verirse istek LLM'e GİTMEZ (HTTP 500)
      revert_fail_mode: closed                 # geri çevirme hatasında yanıt yer tutuculu gitmez
      audit_log: {enabled: true, path: /var/log/litellm/matriks_pii_audit.jsonl}
```

Aksiyonlar: `MASK` (yer tutucu, yanıtta geri çevrilir) · `BLOCK` (HTTP 400, değer içermeyen hata) ·
`LOG` (yalnız denetim izinde sayım) · `IGNORE`.

Ortam değişkenleri LiteLLM geleneğiyle verilir: `hash_secret: os.environ/MATRIKS_PII_HASH_SECRET`.
Tanımlı olmayan bir değişkene başvuru proxy'yi başlangıçta durdurur.

Tüm ayarlar: [README](../README.tr.md#önemli-ayarlar) "Önemli ayarlar"; hazır örnekler: [`examples/`](../examples).

## 4. Desteklenen uç noktalar

| LiteLLM uç noktası | İstekte maskelenen | Yanıtta geri çevrilen |
|---|---|---|
| `/chat/completions` (stream dâhil) | mesajlar, çok parçalı içerik, `name`, `tool_calls` argümanları, tool mesajları | içerik, tool argümanları, `reasoning_content`, `n>1` |
| `/completions` | `prompt` | metin |
| `/embeddings` | `input` (metinler) | — |
| `/responses` (stream dâhil) | `input`, `instructions`, `function_call(_output)` | `output` öğeleri, akış olayları |
| `/v1/messages` (Anthropic, stream dâhil) | `system`, metin, `tool_use`, `tool_result` | `content`, ham SSE |
| `/v1beta/models/{model}:generateContent` ve `:streamGenerateContent` (Gemini native) | `contents[].parts[]`, `systemInstruction`, `functionCall`/`functionResponse` | `candidates[].content.parts[]`, ham SSE çerçeveleri |
| rerank, görsel, ses, MCP | `unsupported_call_types: mask` (varsayılan) ile maskelenir | geri çevrilmez (`pass` / `block` seçilebilir) |

Gemini native rotası için model tanımı örneği (`gemini_native: false` eski "yalnız maskele" davranışına döner):

```yaml
model_list:
  - model_name: gemini-2.5-flash
    litellm_params:
      model: gemini/gemini-2.5-flash
      api_key: os.environ/GEMINI_API_KEY
```

İstemci `POST /v1beta/models/gemini-2.5-flash:generateContent` (veya `:streamGenerateContent?alt=sse`) çağırır.
Anthropic `/anthropic/*` **passthrough** rotasında LiteLLM akış yanıtında post-call guardrail'i çağırmaz; `/v1/messages`
kullanın.

## 5. Birden çok worker / pod / replika

Bir isteğin `pre_call` ve `post_call` kancaları **her zaman aynı süreçte** çalışır; bu yüzden `--num_workers > 1` ve
çok pod'lu kurulumda da `memory` deposu doğru çalışır. Redis **zorunlu değildir**, şu durumlarda önerilir:

- Admin UI "guardrail test" (`apply_guardrail`) çiftlerinin farklı worker/pod'a düşebildiği kurulumlar,
- oturumların süreç yeniden başlatmalarında korunması, bellek sınırının süreç dışına taşınması.

Redis kullanılacaksa oturum ortak ve şifreli tutulur:

1. Sırları **bir kez** üretin, secret manager'a koyun. Tüm örneklere **aynı** değerler verilmelidir:

   ```bash
   python -m matriks_pii.keys          # MATRIKS_PII_SESSION_SECRET=… ve MATRIKS_PII_STORE_KEY=… yazar
   python -m matriks_pii.keys --k8s    # kubectl create secret generic matriks-pii … komutu yazar
   ```

   | Değişken | Ne | Biçim |
   |---|---|---|
   | `MATRIKS_PII_SESSION_SECRET` | oturum jetonunun HMAC imza sırrı | ≥ 32 karakter |
   | `MATRIKS_PII_STORE_KEY` | Redis'teki oturum haritasının AES-256-GCM anahtarı | 32 bayt, base64 |
   | `MATRIKS_PII_REDIS_URL` | Redis adresi (TLS için `rediss://`) | URL |

2. `pip install "matriks-mask[redis,fast]"`

3. `config.yaml`:

   ```yaml
   guardrails:
     - guardrail_name: matriks-pii
       litellm_params:
         guardrail: matriks_pii.guardrail.TurkishPIIGuardrail
         mode: [pre_call, post_call]
         default_on: true
         session_secret: os.environ/MATRIKS_PII_SESSION_SECRET
         session_store:
           backend: redis
           redis_url: os.environ/MATRIKS_PII_REDIS_URL
           encryption_key: os.environ/MATRIKS_PII_STORE_KEY
           ttl_seconds: 3600                 # ≥ LiteLLM request_timeout
   ```

   `redis_url` verilmezse LiteLLM'in `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` değişkenleri kullanılır.

4. Değişkenleri her örneğe verin:

   ```yaml
   # docker-compose
   services:
     litellm:
       env_file: matriks-pii.env
       command: ["--config", "/app/config.yaml", "--num_workers", "4"]
   ```

   ```yaml
   # Kubernetes Deployment
   envFrom:
     - secretRef: {name: matriks-pii}
   ```

Eksik veya hatalı yapılandırma sessizce geçmez. Proxy başlangıçta `ValueError` ile durur:

- `backend: redis` seçili ama sır ya da anahtar yok,
- sır 32 karakterden kısa,
- anahtar 32 baytlık geçerli base64 değil.

Sırlar `config_hash`'e, denetim izine ve loglara yazılmaz.

**Sır değiştirme (rotation):** tüm örnekler aynı anda yeniden başlatılmalıdır. O anda süren isteklerin oturumu
doğrulanamaz; `revert_fail_mode: closed` ile bu yanıtlar yer tutuculu gitmek yerine hata döner.

## 6. Loglama ve gizlilik ayarları

- `turn_off_message_logging: true` önerilir. Eklenti loglara giden kopyaları zaten maskeler; bu ayar ikinci bir savunma
  katmanıdır ve eklentiyle uyumludur (e2e testli).
- **`--detailed_debug` / `LITELLM_LOG=DEBUG` üretimde kapalı olmalıdır.** LiteLLM ham istek gövdesini guardrail
  çalışmadan önce kendisi basar; eklenti bunu engelleyemez.
- Guardrail sırası: başka çıktı tarayıcı guardrail'ler kullanıyorsanız onlar maskeli metni görür. Bu bilinçli bir
  ödünleşimdir: `matriks-pii` girişte ilk, çıkışta son olmalıdır.
- `audit_log` değer içermez: zaman, çağrı kimliği, API anahtarı hash'i, model, varlık türü sayıları, aksiyonlar, süre.
  Saklama süresini kurum, kendi politikasına ve tabi olduğu sektör mevzuatına göre belirler.
- `store_map_in_metadata` yalnız `MATRIKS_PII_ALLOW_DEBUG_MAP=1` ile açılabilir. Üretimde açmayın: harita ham değerleri
  içerir ve metadata, loglama araçlarına gidebilir.

## 7. Docker

[`examples/Dockerfile`](../examples/Dockerfile) resmî LiteLLM imajına paketi ekler:

```bash
docker build -t litellm-matriks-pii -f examples/Dockerfile .
docker run -p 4000:4000 \
  -e OPENAI_API_KEY=... -e LITELLM_MASTER_KEY=... \
  litellm-matriks-pii
```

Çoklu worker için `--env-file matriks-pii.env` ekleyin ve §5'teki config'i kullanın.

## 8. Kurulumu doğrulama

Önce değersiz self-test (proxy başlatmadan; CI'da ve Kubernetes `startupProbe` olarak da kullanılabilir):

```bash
python -m matriks_pii.selftest --config config.yaml           # mode, config, depo gidiş-dönüşü, 12 sondaj, gecikme
python -m matriks_pii.selftest --config config.yaml --quick   # < 2 sn
```

```yaml
# Kubernetes
startupProbe:
  exec: {command: ["python", "-m", "matriks_pii.selftest", "--config", "/app/config.yaml", "--quick"]}
  periodSeconds: 10
  failureThreshold: 6
```

Sonra uçtan uca:

```bash
curl -s http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"Benim adım Ayşe Demir, TCKN 17291716060. Adımı ve numaramı tekrar et."}]}' \
  -D - | grep -i -E "x-litellm-applied-guardrails|content"
```

Beklenen:

- Yanıt başlığında `x-litellm-applied-guardrails: matriks-pii` bulunur.
- İstemci yanıtında gerçek ad ve numara görünür (geri çevrildi).
- Sağlayıcıya giden istekte yalnız `<KISI_1>`, `<TCKN_1>` vardır. LiteLLM spend log'unda veya
  `standard_logging_object.guardrail_information` alanında `masked_entity_count: {"KISI": 1, "TCKN": 1}` görünür.
- `Şifre: Deneme123!` LLM'e `<SIFRE_1>` olarak gider, yanıtta `****` görünür (`SIFRE: BLOCK` ile HTTP 400 `matriks_pii_blocked`).

`17291716060` sentetik, checksum'ı geçerli bir test numarasıdır.

## 9. Sorun giderme

| Belirti | Neden | Çözüm |
|---|---|---|
| Yanıtta `<KISI_1>` gibi yer tutucular kalıyor | `post_call` çalışmıyor, `stream_scope: non_streaming` ya da `revert_fail_mode: open` ile oturum bulunamadı | `mode: [pre_call, post_call]`; `selftest` çıktısındaki uyarılar; `ttl_seconds` > `request_timeout` |
| HTTP 500 `matriks_pii_session_missing` | Oturum bulunamadı (TTL, sır uyuşmazlığı, depo tahliyesi) | [`RUNBOOK.md`](RUNBOOK.md) |
| HTTP 503 `matriks_pii_store_unavailable` | Redis erişilemiyor (devre kesici 10 sn açık kalır) | Redis sağlığı, `redis_timeout_seconds`, TLS/parola |
| HTTP 413 `matriks_pii_text_too_large` | `max_text_chars` / `max_request_chars` aşıldı | istemci tarafında bölün veya sınırı yükseltin |
| Proxy başlarken `matriks_pii yapılandırma hatası: …` | config doğrulaması (sınır, bilinmeyen varlık, tip) | iletideki alan adını düzeltin; ileti sır değerini içermez |
| NER açıkken ilk istek yavaş / proxy başlamıyor | model yükleniyor / yüklenemiyor (`ner_preload: true`) | modeli imaja önceden indirin (`HF_HOME`); `ner_fail_mode: lexicon` geçici çözüm |
| Proxy başlarken `ValueError: redis session_store … session_secret zorunlu` | Redis seçili ama sır yok | `python -m matriks_pii.keys` → değişkenleri tanımlayın |
| `ValueError: ortam değişkeni tanımlı değil: X` | config'de `os.environ/X` var ama değişken yok | değişkeni tanımlayın |
| HTTP 500 `matriks_pii_guardrail_failure` | Guardrail beklenmeyen bir hata aldı; `fail_mode: closed` isteği durdurdu | proxy logunda `matriks_pii pre_call hatası: <HataTürü>`; geçici çözüm `fail_mode: open` (istek **maskesiz** gider; önerilmez) |
| HTTP 500 `matriks_pii_revert_failure` | Geri çevirme hatası | log: `matriks_pii post_call/stream hatası` |
| HTTP 400 `matriks_pii_blocked`, `"entity": "SIFRE"` | BLOCK aksiyonlu veri (şifre vb.) | beklenen davranış; gerekirse `entities: {SIFRE: MASK}` |
| Bir ad maskelenmiyor | Sözlükte olmayan / yabancı ad | `name_detection: {ner_backend: hf}` (`[ner]` eki) veya bağlam ("Müşteri adı: …") |
| Bir kelime gereksiz yere maskeleniyor | yanlış pozitif | `entities: {VARLIK: IGNORE}` geçici; örneği geliştiricilere iletin (değeri değil, cümle yapısını) |
| Kurum kodu/numarası maskelenmeli | yerleşik değil | `extra_regex: [{entity: KURUM_LISANS, pattern: "LIS-[0-9]{8}", score: 0.9, context: "lisans"}]` |

## 9.1 NER modu üretim notları

- `pip install "matriks-mask[ner]"`; CPU için `torch` CPU tekerleği yeterlidir. Model imaja önceden indirilmelidir
  (`HF_HOME` dizini); `ner_preload: true` (varsayılan) model yüklenemezse proxy'nin başlamasını engeller.
- Model 512 token üstünde hata verir: metin cümle sınırında `ner_max_chars` (1200) parçalara bölünür.
- Her çağrı `ner_timeout_seconds` (5 sn) ile sınırlıdır; zaman aşımı/hata `ner_fail_mode: closed` → istek reddedilir,
  `lexicon` → sözlük sonuçlarıyla devam eder (`matriks_pii_events_total{event="ner_failed"}`).
- `ner_max_concurrency` (1) eşzamanlı çıkarım sayısıdır; CPU çekirdeğine göre artırın. Zaman aşımı çalışan çıkarımı
  iptal etmez; yük altında kuyruk büyüyebilir → `matriks_pii_hook_seconds` p99'u izleyin.

## 9.2 Metrikler

`pip install "matriks-mask[metrics]"` ve LiteLLM'de:

```yaml
litellm_settings:
  callbacks: ["prometheus"]
```

`/metrics` altında `matriks_pii_*` sayaçları görünür (etiketlerde değer yoktur). Uyarı önerileri: [`RUNBOOK.md`](RUNBOOK.md).

## 9.3 0.1.x → 0.3.0 yükseltme ve geri alma

Yeni yapılandırma anahtarları (0.1.x bunları tanımaz ve başlangıçta hata verir): `dry_run`, `gemini_native`,
`metrics_enabled`, `response_json_preserve_format`, `suffix_repair_attached`, `label_aliases`, `allow_list`, `deny_list`,
`max_request_chars`, `analysis_threads`, `session_secret_previous`, `analysis_cache.max_total_spans`,
`session_store.{redis_timeout_seconds, refresh_ttl, require_tls, encryption_key_previous}`,
`name_detection.{ner_max_chars, ner_timeout_seconds, ner_fail_mode, ner_preload, ner_max_concurrency}`.

Davranış değişiklikleri: oturum bulunamazsa artık 500 (önceden yer tutuculu yanıt); PII'siz istekte oturum yazılmaz;
`GIZLI_ANAHTAR` varsayılan MASK (yanıtta `****`); Gemini native rotası geri çevrilir; `max_sessions` 100.000 → 10.000;
önbellek TTL 600 → 300 sn; `config_hash` değişir (beklenir); sayısal değerlerde ek onarımı (`17291716060'ı`).
Geri alma: wheel + config çift olarak; acil durumda `MATRIKS_PII_IGNORE_UNKNOWN_KEYS=1`.

## 10. Eklenti dışında kalan KVKK yükümlülükleri

Maskeleme, yurt dışındaki bir LLM'e yapılan aktarımı **ortadan kaldırmaz**; riski azaltan teknik bir tedbirdir.
Ayrıca gerekenler ([README](../README.tr.md#kvkk-ve-sektör-mevzuatı-hukuki-görüş-değildir) "KVKK ve sektör mevzuatı"):

- Standart Sözleşme-2 ve 5 iş günü içinde Kurul'a bildirim,
- sağlayıcıyla veri işleme sözleşmesi,
- DPIA, aydınlatma metni ve VERBİS,
- ihlal müdahale planı,
- tabi olunan sektör mevzuatının (SPK, BDDK vb.) kurum tarafından değerlendirilmesi.
