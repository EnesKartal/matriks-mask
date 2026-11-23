# Sektör örnek dosyalarının ölçüm kümeleri

Her `<sektör>.jsonl`, `examples/sektor/<sektör>.yaml` için pozitif ve negatif örneklerdir (`--corpus` biçimi, satır
başına bir JSON; `"entities": []` = hiçbir şey maskelenmemeli). Tüm değerler sentetiktir.
`tests/test_sektor_ornekleri.py` her dosyayı kendi kümesiyle ölçer (P = R = 1).

    matriks-pii selftest --config examples/sektor/havayolu.yaml --corpus tests/fixtures/sektor/havayolu.jsonl
