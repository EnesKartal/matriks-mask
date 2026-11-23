"""Hem ad/soyad hem de Türkçe sözcük olan token'ların elle derlenmiş listesi (common_words_tr.txt).

Dosyada yalnız elle derlenmiş girdiler bulunur: weak (yaygın ad + sözcük), strong (finans/kurumsal sözcük olan
adlar) ve exclude ("yalnızca ad" olan istisnalar). Ad listesi ile sözcük listesinin (tr_words.txt) kesişimine
dayanan strong girdiler pakette tutulmaz; matriks_pii.data.common_words() bunları çalışma anında ekler.

Kullanım: python scripts/build_common_words.py   (önce scripts/build_name_lists.py)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from matriks_pii.text_utils import fold_key  # noqa: E402

DATA = ROOT / "matriks_pii" / "data"

# altyazılarda sık geçtiği için listeye giren ama Türkçe'de sözcük anlamı zayıf olan adlar
NAME_ONLY = set(
    "ali emre ahmet mehmet mustafa muhammed meryem hasan huseyin ibrahim ismail osman murat omer fatma zeynep "
    "elif hatice emine burak kemal cem serkan tom david jane martin anna robert daniel eric elizabeth helen "
    "marie elena linda angela nina albert norman simon maria sara janet melissa rita diana lara leon hanna "
    "burke kirk baker isa sezar ken jan eva tim sam susan".split()
)

# altyazı derleminde seyrek ama Türkçe sözcük olan ad/soyadlar
EXTRA = (
    "doğan şahin bulut ekin nur mert ozan cihan çelik aydın yudum pınar ege güneş deniz can umut barış kaya yıldız "
    "demir hava gül türk toprak onur kurt bahar zafer yağmur mutlu sevgi aslan ordu cuma yılmaz kılıç "
    "demirci sevinç bayram kara akın arslan çiçek kartal şimşek polat koç özgür erdem tan ay ulus "
    "savaş sonmez acar yalçın keskin tuna ırmak kervan bozkurt kocaman sarı uçar ateş yiğit cesur deniz gök "
    "kahraman metin elmas inci mercan lale nergis menekşe sümbül gonca papatya yasemin "
    "ayçiçek hilal yıldırım şafak seher sabah akşam gece bulut rüzgar fırtına şeker bal süt pınar ırmak dere "
    "vadi dağ tepe ova orman çınar meşe kavak servi söğüt ılık sıcak serin duru berrak parlak nazik sevgili "
    "hayat umut huzur barış özlem hasret sevda vefa sadık emin güven inanç iman şükran minnet saygı onur gurur "
    "zafer başarı ümit ışık nur ziya fer çelik demir bakır gümüş altın elmas zümrüt yakut inci mercan sedef "
    "kumru serçe bülbül kartal şahin doğan atmaca turna kuğu ceylan ahu aslan kaplan pars kurt tilki selva"
).split()


# altyazı derleminde seyrek ama finans/kurumsal metinde sık geçen, ad listesinde de bulunan sözcükler
DOMAIN = (
    "hacim kıymet fiyat faiz kur borsa hisse endeks temettü sermaye getiri vade teminat bilanço kâr zarar "
    "piyasa pazar alım satım kredi mevduat yatırım fon portföy tahvil bono kupon ihraç halka arz "
    "değer varlık yükümlülük gelir gider bütçe vergi stopaj komisyon marj oran seviye destek direnç "
    "hedef tavsiye rapor analiz sektör şirket holding banka sigorta enerji maden çimento tekstil gıda "
    "otomotiv inşaat ulaşım turizm teknoloji yazılım bilişim lojistik tarım petrol altın gümüş döviz "
    "dolar euro sterlin yen lira kuruş milyon milyar trilyon nakit bakiye hesap kart şube merkez"
).split()


MODERN = (
    "yiğit arda bora ege efe mert berk emir kerem alp kaan aras doruk çınar eymen ayaz miraç poyraz atlas kuzey "
    "defne ela duru nehir asel eylül ecrin azra öykü ada derin deniz su melis lina inci yağmur toprak umut barış"
).split()


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    from matriks_pii import data

    names = data.first_names() | data.last_names()
    weak = {fold_key(w) for w in EXTRA}
    # 2000 sonrası yaygınlaşan, sözcük anlamı da olan adlar: zayıf ceza (eski nüfus verisinde "nadir" görünürler)
    modern = {fold_key(w) for w in MODERN}
    weak |= modern & names
    strong: set[str] = {fold_key(w) for w in DOMAIN if fold_key(w) in names} - weak
    exclude = {fold_key(w) for w in NAME_ONLY}
    hdr = (
        "# Ad/soyad olup aynı zamanda Türkçe sözcük olan token'lar (elle derlendi). Biçim: <sözcük>\\t<weak|strong|exclude>.\n"
        "# weak: yaygın ad + sözcük (Deniz, Umut) → küçük ceza; strong: nadir ad + sık sözcük → büyük ceza.\n"
        "# exclude: çalışma anında hesaplanan strong kümesine alınmayan adlar (matriks_pii/data/__init__.py common_words).\n"
        "# scripts/build_common_words.py ile üretildi. ASCII katlanmış.\n"
    )
    lines = (
        [f"{w}\tweak" for w in sorted(weak)]
        + [f"{w}\tstrong" for w in sorted(strong)]
        + [f"{w}\texclude" for w in sorted(exclude)]
    )
    (DATA / "common_words_tr.txt").write_text(hdr + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"weak={len(weak)} strong(elle)={len(strong)} exclude={len(exclude)} strong(toplam)="
          f"{sum(1 for k in data.common_words().values() if k == 'strong')}")


if __name__ == "__main__":
    main()
