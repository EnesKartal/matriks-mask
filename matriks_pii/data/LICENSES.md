# Paketlenmiş veri dosyalarının kaynakları ve lisansları

Lisans metinleri ve atıflar: depo kökündeki `THIRD_PARTY_NOTICES.md` ve `NOTICE` (wheel'de `*.dist-info/licenses/` altında).

| Dosya | Kaynak | Lisans | Not |
|---|---|---|---|
| `first_names_tr.txt`, `last_names_tr.txt`, `popular_first_names_tr.txt`, `frequent_first_names_tr.txt`, `frequent_last_names_tr.txt` | [mkozturk/trnames](https://github.com/mkozturk/trnames) | MIT | ASCII katlanmış; yalnız trnames verisinden (ad, soyad ve kümülatif olasılık eşikleri) üretilir (`scripts/build_name_lists.py`) |
| `tr_words.txt` | [hermitdave/FrequencyWords](https://github.com/hermitdave/FrequencyWords) `tr_50k` (OpenSubtitles 2018) | **CC BY-SA 4.0** | Yalnız sözcük listesi (sıklık değerleri yok); Türkçe karakterler katlanmış, tek karakterli/harf dışı sözcükler çıkarılmış. Proje Apache-2.0 lisansının dışındadır; değiştirilmiş hâli de CC BY-SA 4.0 ve atıfla dağıtılmalıdır. Başka bir veri dosyasının üretiminde kullanılmaz. |
| `common_words_tr.txt` | Proje ekibi tarafından elle derlendi (ad listesindeki sözcük-adlar) | Proje lisansı (Apache-2.0) | `scripts/build_common_words.py` |
| `il_ilce_tr.json` | [ubeydeozdmr/turkiye-api](https://github.com/ubeydeozdmr/turkiye-api) `datasets/2025` + elle eklenen semt adları | MIT | İl, ilçe, mahalle adları ve posta kodları (`scripts/build_geo.py`) |
| `honorifics_tr.txt`, `org_suffixes_tr.txt`, `org_names_tr.txt`, `special_category/*.txt` | Proje ekibi tarafından elle derlendi | Proje lisansı (Apache-2.0) | Özel nitelikli veri terimleri KVKK Özel Nitelikli Kişisel Veri Rehberi (2025) örneklerinden derlendi |

"Hem ad hem sözcük" olan adlar/soyadlar (Telefon, Hacim, Arı, Sağlam) ve sık sözcük olan adların "strong" kümesi pakette
dosya olarak tutulmaz; `matriks_pii/data/__init__.py` bunları çalışma anında ad listeleri ile `tr_words.txt`'den hesaplar.

`tr_words.txt` başka bir sözlükle değiştirilmek istenirse `scripts/_raw/tr_50k.txt` yerine kendi sözcük listenizi
(satır başına `sözcük sıklık`, sıklığa göre azalan) koyup `python scripts/build_name_lists.py` çalıştırın; değişiklikten sonra
negatif set ve holdout ölçümleri (`python scripts/corpus_report.py`, `pytest tests/test_holdout.py`) yeniden çalıştırılmalıdır.
