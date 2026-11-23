# Third-party notices / Üçüncü taraf bildirimleri

matriks-pii source code is licensed under the Apache License 2.0 (see `LICENSE` and `NOTICE`). The package also ships data files derived
from the third-party sources below. Each keeps its own license.

matriks-pii kaynak kodu Apache-2.0 lisanslıdır (`LICENSE`, `NOTICE`). Paket, aşağıdaki üçüncü taraf kaynaklardan türetilmiş veri
dosyaları da içerir; her biri kendi lisansına tabidir. Dosya bazında eşleme: `matriks_pii/data/LICENSES.md`.

| Kaynak | Paketteki dosyalar | Lisans |
|---|---|---|
| [mkozturk/trnames](https://github.com/mkozturk/trnames) | `first_names_tr.txt`, `last_names_tr.txt`, `popular_first_names_tr.txt`, `frequent_first_names_tr.txt`, `frequent_last_names_tr.txt` | MIT |
| [hermitdave/FrequencyWords](https://github.com/hermitdave/FrequencyWords) (`content/2018/tr/tr_50k.txt`, OpenSubtitles 2018) | `tr_words.txt` (yalnız bu dosya) | **CC BY-SA 4.0** |
| [ubeydeozdmr/turkiye-api](https://github.com/ubeydeozdmr/turkiye-api) (`datasets/2025`) | `il_ilce_tr.json` | MIT |

Sözcük listesi (`tr_words.txt`) başka bir veri dosyasının üretiminde kullanılmaz. "Hem ad hem sık sözcük" seçimleri
(ör. Telefon, Arı, Sağlam) pakette dosya olarak tutulmaz; kullanıcının ortamında, çalışma anında hesaplanır
(`matriks_pii/data/__init__.py`).

Paketle dağıtılmayan, çalışma zamanında isteğe bağlı indirilen bileşenler:

- `ner_backend: hf` seçilirse Hugging Face modeli [`akdeniz27/bert-base-turkish-cased-ner`](https://huggingface.co/akdeniz27/bert-base-turkish-cased-ner)
  kullanıcının ortamına indirilir. Modelin lisansını kullanmadan önce model sayfasından kontrol edin.
- `scripts/external_bench.py --download` ölçüm için [Werea-co/Werea-KVKK-Bench](https://huggingface.co/datasets/Werea-co/Werea-KVKK-Bench)
  (Apache-2.0) ve [cagrigungor/turkish-pii-masking-benchmark](https://huggingface.co/datasets/cagrigungor/turkish-pii-masking-benchmark)
  (CC0) veri setlerini indirir; bu veriler depoya ve pakete girmez.

---

## FrequencyWords — `tr_words.txt` (CC BY-SA 4.0)

`matriks_pii/data/tr_words.txt` is an adaptation of `tr_50k.txt` from
[FrequencyWords](https://github.com/hermitdave/FrequencyWords) by Hermit Dave, built from the OpenSubtitles 2018 corpus.
Changes: frequency counts removed; Turkish characters folded to ASCII (ı→i, ç→c, ğ→g, ö→o, ş→s, ü→u) and words
lower-cased; single-character and non-alphabetic tokens removed and duplicates merged after folding
(`scripts/build_name_lists.py`).

The adapted file is licensed under the Creative Commons Attribution-ShareAlike 4.0 International License
(<https://creativecommons.org/licenses/by-sa/4.0/>). It is **not** covered by the Apache License of this project.
If you redistribute a modified version of this file, it must remain under CC BY-SA 4.0 with attribution.

Türkçe: `tr_words.txt`, Hermit Dave'in FrequencyWords projesindeki `tr_50k.txt` listesinden (OpenSubtitles 2018)
türetilmiştir; sıklık değerleri çıkarılmış, Türkçe karakterler katlanmış (ı→i, ç→c…), tek karakterli ve harf dışı
sözcükler çıkarılmış, katlama sonrası tekrarlar birleştirilmiştir. Dosya CC BY-SA 4.0 lisanslıdır ve
projenin Apache-2.0 lisansı kapsamında değildir. Değiştirilmiş hâli yeniden dağıtılırsa aynı lisans ve atıf korunmalıdır.

---

## trnames — MIT

MIT License

Copyright (c) 2021 Kaan Öztürk

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## turkiye-api — MIT

MIT License

Copyright (c) 2022-2026 Ubeyde Emir Özdemir

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
