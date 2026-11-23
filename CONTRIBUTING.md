# Katkı rehberi / Contributing

Katkılarınız için teşekkürler. Issue ve pull request'ler Türkçe veya İngilizce olabilir.
Contributions are welcome; issues and pull requests may be written in Turkish or English.

## Geliştirme ortamı

```bash
git clone https://github.com/MatriksData/matriks-pii && cd matriks-pii
python -m venv .venv && source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev,fast,metrics,redis]"
export PYTHONUTF8=1                                         # Windows: set PYTHONUTF8=1
export MATRIKS_PII_HASH_SECRET=0123456789abcdef0123456789abcdef   # strict örnek config'in selftest'i için
```

## Pull request öncesi

```bash
ruff check matriks_pii scripts tests
mypy matriks_pii --ignore-missing-imports
pytest -q                                   # birim + fixture testleri
python scripts/corpus_report.py             # varsayılan sözlük modunda yanlış pozitif = 0 olmalı
python -m matriks_pii.selftest --config examples/config.yaml
pytest -q -m e2e tests/e2e                  # gerçek LiteLLM proxy (yerel echo sunucusu; dış ağ gerekmez)
```

İsteğe bağlı: `pytest -m benchmark`, `pytest -m redis_live` (`MATRIKS_PII_REDIS_URL`), `pytest -m ner`,
`python scripts/external_bench.py --download && pytest -m external`.

## Kurallar

- **Yalnız sentetik veri.** Fixture'lara, testlere, issue'lara ve PR açıklamalarına gerçek kişisel veri, gerçek müşteri
  metni veya gerçek API anahtarı koymayın. TCKN/VKN/IBAN/kart değerlerini kontrol basamağı algoritmasıyla üretin;
  anahtar örneklerinde açıkça sahte değer kullanın (`AKIAIOSFODNN7EXAMPLE`, `ghp_EXAMPLE…`).
- **Yeni tespit kuralı = pozitif + negatif örnek.** `tests/fixtures/detect/` altına beklenen tespiti, `tests/fixtures/negative/`
  altına yanlış pozitif tuzağını ekleyin. Elle yazılan dosyalar `*_ek.yaml` / `*_x.yaml` adlarını kullanır;
  `scripts/build_fixtures.py` üretilmiş dosyaları yeniden yazar.
- **Holdout kümeleri** (`tests/fixtures/holdout/`) değerlendirme içindir; kümeye özel kural yazmayın.
- **Değersiz loglama.** Log, hata iletisi, metrik etiketi ve denetim izine hiçbir koşulda ham değer yazılmaz.
- **Varsayılanlar fail-closed kalır.** Varsayılan davranışı değiştiren değişiklikler CHANGELOG'da **Breaking** olarak ve
  eski davranışa dönüş bayrağıyla belirtilir.
- Commit mesajları kısa ve konu bazlıdır (`fix(revert): …`, `feat(policy): …`, `docs: …`).

## Güvenlik açıkları

Herkese açık issue açmayın; [`SECURITY.md`](SECURITY.md).

## Lisans

Katkılarınız projenin [Apache License 2.0](LICENSE) lisansı altında yayımlanır (lisansın 5. maddesi);
ayrı bir katkıcı lisans sözleşmesi (CLA) istenmez. `matriks_pii/data/tr_words.txt` CC BY-SA 4.0
lisanslıdır ([`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)).
