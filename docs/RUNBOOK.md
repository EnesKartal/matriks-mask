# matriks-pii — İşletim el kitabı (runbook)

Bu belge nöbetçi/SRE içindir: her hata kodu ve metrik için **belirti → tanı → eylem**. Hiçbir adım kişisel veri
görüntülemeyi gerektirmez; loglar, denetim izi ve metrikler değersizdir.

Ön koşullar: `python -m matriks_pii.selftest --config config.yaml` çalıştırılabilir; Prometheus metrikleri için
`litellm_settings.callbacks: ["prometheus"]` ve `pip install "matriks-pii[metrics]"`.

## Hızlı tanı

```bash
python -m matriks_pii.selftest --config /app/config.yaml           # tam kontrol (depo, sondajlar, gecikme)
python -m matriks_pii.selftest --config /app/config.yaml --quick   # < 2 sn
python -m matriks_pii.selftest --config /app/config.yaml --probe "örnek metin"   # hangi varlıklar, hangi skorla (değersiz)
```

Denetim izinde her kayıtta `guardrail_version` ve `config_hash` vardır: pod'lar arası farklılık (yarım kalmış
dağıtım, farklı config) buradan görülür.

## Hata kodları

| Kod (HTTP) | Belirti | Olası neden | Eylem |
|---|---|---|---|
| `matriks_pii_session_missing` (500) | Yanıt yerine hata; `matriks_pii_events_total{event="session_missing"}` artıyor | (1) `session_store.ttl_seconds` < LiteLLM `request_timeout` (uzun yanıtlar); (2) Redis bellek tahliyesi (`maxmemory-policy`); (3) pod'lar arası farklı `MATRIKS_PII_SESSION_SECRET`; (4) çok worker + `memory` deposu ve LiteLLM'in kancaları farklı süreçte çalıştırması; (5) sır rotasyonu sırasında `session_secret_previous` verilmemesi | `config_hash`/sürüm farkını audit'te kontrol edin; TTL'i `request_timeout`'tan büyük yapın; Redis'te `noeviction` veya ayrı DB; sır rotasyonunu aşağıdaki prosedürle yapın. Geçici olarak `revert_fail_mode: open` yanıtları yer tutuculu döndürür (KVKK açısından sızıntı değildir ama kullanıcı deneyimi bozulur). Uyarı eşiği: `session_missing / post_call > %1 (5 dk)` |
| `matriks_pii_store_unavailable` (503) | PII içeren isteklerde 503; PII'siz istekler geçer | Redis erişilemiyor/zaman aşımı; devre kesici açık (3 ardışık hata → 10 sn) | Redis sağlığı, ağ, TLS sertifikası, parola. `redis_timeout_seconds` (vars. 2 sn). Devre 10 sn sonra kendiliğinden kapanır. `fail_mode: open` maskeli isteği geçirir ama yanıt geri çevrilemez |
| `matriks_pii_guardrail_failure` (500) | İstek reddedildi | Guardrail içinde beklenmeyen istisna (log: `matriks_pii pre_call hatası: <Tip>`) | Tip adına bakın. Gerekirse sorun giderme süresince `MATRIKS_PII_DEBUG_TRACEBACK=1` (yalnız `LITELLM_MODE` ≠ `PRODUCTION`; yığın izi kullanıcı metni parçası taşıyabilir) |
| `matriks_pii_revert_failure` (500) | Yanıt geri çevrilemedi | Beklenmeyen yanıt biçimi | Log tip adı + çağrı türü; çözülene kadar `revert_fail_mode: open` (yer tutuculu yanıt) |
| `matriks_pii_text_too_large` (413) | Büyük istek reddedildi | Tek metin > `max_text_chars` (vars. 2 MB) veya toplam > `max_request_chars` (vars. 4 MB) | İstemci tarafında bölme; gerekiyorsa sınırları yükseltin (bellek/gecikme etkisini ölçün) |
| `matriks_pii_blocked` (400) | İstek reddedildi, `entity` alanı var | Politika: strict'te `SIFRE` ve `GIZLI_ANAHTAR`, `BLOCK` yapılandırılmış varlıklar | Beklenen davranış. Ani artış istemci gerilemesine işaret eder (`events_total{event="blocked"}`) |

## Metrik uyarıları (öneri)

| Metrik | Eşik | Anlam / eylem |
|---|---|---|
| `matriks_pii_events_total{event="session_missing"}` / post_call | > %1, 5 dk | yukarıdaki tablo |
| `matriks_pii_events_total{event="store_unavailable"}` | > 0, 1 dk | Redis |
| `matriks_pii_events_total{event="unresolved_placeholder"}` / post_call | > %2, 15 dk | Model yer tutucu uyduruyor/bozuyor → `placeholder_instruction: system_suffix` açın; `label_aliases` ile çevrilen etiketleri ekleyin |
| `matriks_pii_hook_seconds{hook="pre_call"}` p99 | > 50 ms | NER açık mı (`ner_backend`), `analysis_threads` yetersiz mi, çok büyük istekler mi |
| `matriks_pii_events_total{event="ner_failed"}` | > 0 | NER zaman aşımı/hata: `ner_timeout_seconds`, CPU/GPU boyutu; geçici `ner_fail_mode: lexicon` veya `ner_backend: none` |
| `matriks_pii_events_total{event="audit_write_failed"}` | > 0 | Disk dolu / izin; audit dizini |
| `matriks_pii_scores_total` dağılımı | KISI 0.5–0.6 kovasında ani artış | Yanlış pozitif kayması olabilir → örnek metinle `--probe`, gerekiyorsa `allow_list` |

## Yanlış pozitif / negatif bildirimi

1. Kullanıcıdan **sentetikleştirilmiş** örnek alın (gerçek veri değil).
2. `python -m matriks_pii.selftest --config ... --probe "metin"` ile hangi tanıyıcının hangi skorla eşleştiğini görün.
3. Kalıcı çözüm: `allow_list` (asla maskelenmeyecek ifade; TCKN/IBAN/kart/anahtar için çalışmaz) veya
   `deny_list` / `extra_regex` (her zaman maskelenecek). Genel bir kural hatasıysa issue + negatif/detect fixture'ı.

## Sır ve anahtar rotasyonu (kesintisiz)

1. Yeni değerleri üretin: `python -m matriks_pii.keys`.
2. Tüm örneklere: `MATRIKS_PII_SESSION_SECRET=<yeni>`, `MATRIKS_PII_SESSION_SECRET_PREVIOUS=<eski>`,
   `MATRIKS_PII_STORE_KEY=<yeni>`, `MATRIKS_PII_STORE_KEY_PREVIOUS=<eski>`.
3. Kademeli yeniden başlatma (rolling restart). Eski sırla imzalanmış jetonlar ve eski anahtarla şifrelenmiş oturumlar
   bu sürede geçerlidir.
4. `session_store.ttl_seconds` kadar bekleyin, `*_PREVIOUS` değişkenlerini kaldırıp tekrar kademeli başlatın.

## Kademeli yayın ve geri alma

- **Gölge mod:** `dry_run: true` → hiçbir şey maskelenmez/engellenmez; `would_mask` / `would_block` sayımları
  `guardrail_information`, denetim izi ve metriklerde. Önerilen: staging'de 5 iş günü, üretimde 1 hafta.
- **Anahtar bazlı canary:** ikinci bir guardrail örneği `default_on: false` ile tanımlanır, seçili API anahtarlarının
  `guardrails` listesine eklenir.
- **Geri alma:** wheel + config **çift olarak** geri alınır. Yeni sürümün config anahtarları eski sürümde başlangıç
  hatası verir (`extra="forbid"`); acil durumda `MATRIKS_PII_IGNORE_UNKNOWN_KEYS=1` tanınmayan anahtarları uyarıyla atlar.
- Davranış bayrakları (eski davranışa dönüş): `gemini_native: false`, `response_json_preserve_format: false`,
  `suffix_repair_attached: false` (vars.), `label_aliases: {}`, `ner_backend: none`.

### Aşama kapılarını ölçme (`scripts/rollout_report.py`)

Denetim izi (`audit_log`) değersizdir; rapor yalnız sayımları okur. Çıkış kodu kapı ihlalinde 1'dir.

```bash
# 1) gölge mod sonunda: sayımlar beklentiyle uyumlu mu, guardrail hatası var mı?
python scripts/rollout_report.py /var/log/matriks-pii/audit.*.jsonl --guardrail matriks-pii
python scripts/rollout_report.py /var/log/matriks-pii/audit.*.jsonl --expect beklenen.json   # {"KISI": 120, ...}

# 2) canary sonunda: oturum kaybı ≤ %1, hata 0, istek başına oranlar gölge moda göre ±%15 içinde
python scripts/rollout_report.py canary/audit.*.jsonl --guardrail matriks-pii-canary \
    --baseline shadow/audit.*.jsonl --max-change 0.15 --max-session-missing 0.01
```

Kapılar: gölge modda `failures = 0`; canary'de `failures = 0`, `session_missing / post_call ≤ %1`, KISI ve 20'den çok
örneği olan her varlıkta istek başına oran değişimi ≤ %15. Prova: `tests/e2e/test_rollout_rehearsal.py` aynı kapıları
holdout-2 trafiğiyle gerçek proxy üzerinde koşturur.
