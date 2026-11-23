## Ne değişti / What changed

<!-- Kısa açıklama; ilgili issue: #... / Short description; related issue: #... -->

## Kontrol listesi / Checklist

- [ ] Yalnız sentetik veri; gerçek kişisel veri veya gerçek anahtar yok / Synthetic data only; no real personal data or credentials
- [ ] Yeni tespit kuralı için pozitif (`tests/fixtures/detect/`) ve negatif (`tests/fixtures/negative/`) örnek / Positive and negative fixtures for new detection rules
- [ ] `ruff check matriks_pii scripts tests` ve `mypy matriks_pii --ignore-missing-imports`
- [ ] `pytest -q` ve `python scripts/corpus_report.py` (yanlış pozitif = 0 / false positives = 0)
- [ ] Varsayılan davranış değiştiyse CHANGELOG'da **Breaking** + eski davranışa dönüş bayrağı / Breaking changes noted in CHANGELOG with an opt-out flag
