"""Coğrafi koordinat (`KONUM`): KVKK'da lokasyon verisi — yalnız bir KİŞİYLE ilişkili olduğunda.

Koşullar: (1) koordinat bağlamı (konum, koordinat, GPS, enlem/boylam, lat/lng, harita...) VE (2) kişiye bağlılık: aynı
cümlede kişi/kimlik span'i, 1./2. şahıs ya da müşteri işaretçisi, iyelikli konum sözcüğü ("konumum", "evimin konumu").
Yapısal `lat=…&lng=…` / `"latitude": …` biçimi (uygulama verisi) kişiye bağlı sayılır. Faz 2'de çalışır (kişi span'leri
hazırken). Türkiye sınır kutusu kullanılmaz: "USD/TRY 41.0082, EUR/TRY 28.9784" gibi kur çiftleri aynı biçimdedir.
"""

from __future__ import annotations

import re

from ..text_utils import fre
from .base import AnalysisContext, Recognizer, Span, ctx_prefix_re
from .special_category import _BIND_ENTITIES, _MARKERS

_LAT = r"-?(?:[0-8]?[0-9]|90)\.[0-9]{3,8}"
_LON = r"-?(?:1[0-7][0-9]|[0-9]?[0-9]|180)\.[0-9]{3,8}"
# sondaki cümle noktası koordinatın parçası değildir ("son konum 39.6936, 41.1198.")
_END = r"(?![0-9]|\.[0-9])"
_COORD_RE = re.compile(rf"(?<![0-9.\-])(?P<lat>{_LAT})\s*[,;/]\s*(?P<lon>{_LON}){_END}")
# lat=41.0082&lng=28.9784 / "latitude": 41.0, "longitude": 28.9 — span ilk sayıdan son sayıya
_LATLNG_RE = re.compile(
    rf"(?i:lat(?:itude)?)[\"']?\s*[:=]\s*(?P<lat>{_LAT})[\"']?\s*[,&;]\s*[\"']?(?i:lng|lon|long|longitude)[\"']?\s*[:=]\s*"
    rf"(?P<lon>{_LON}){_END}"
)
# önek eşleşmesi "latife/Londra/geometri/pinti"yi de yakalar; ayrıca koordinat çifti şart olduğu için zararsız
_CTX = ctx_prefix_re(
    "konum", "koordinat", "gps", "enlem", "boylam", "lat", "lng", "lon", "latitude", "longitude", "harita", "location",
    "geo", "pin", "adres pini",
)
_PERSONAL_LOC = fre(
    r"(?<![a-z])(?:konumum|konumumu|konumu|konumunu|konumunuz|konumumuz|evim|evimin|evinin|evinizin|bulunduğum|bulunduğu|"
    r"bulunduğunuz|adresim|adresimin|yerim|nerede|neredeyim|şu an|şuan)(?![a-z])"
)
# konum bir kişinin/kişisel kaydın parçası sayılır: kişi ve iletişim kimliklerinin yanında cihaz/araç/sözleşme kimlikleri
_LOC_BIND = _BIND_ENTITIES | frozenset({"IMEI", "PLAKA", "SASI_NO", "POLICE_NO", "MKK_SICIL", "EHLIYET", "KIMLIK_SERI", "IP",
                                         "MAC", "MUSTERI_NO", "HESAP_NO"})
# para/kur/sürüm bağlamı: önde 40 karakter içinde ya da hemen arkada para birimi ("…, 28.9784 TL"); daha uzaktaki
# "maaşı 142.000 TL" koordinatı geçersiz kılmaz
_NOT_COORD = re.compile(r"(?i)\b(?:usd|eur|gbp|try|tl|fiyat|kur|sürüm|versiyon|version|puan|endeks)\b")
_CURRENCY_AFTER = re.compile(r"(?i)^[\s,;.]{0,3}(?:tl|usd|eur|gbp|try|₺|\$|€|%)(?![a-zçğıöşü])")


class LocationRecognizer(Recognizer):
    name = "location"
    entities = ("KONUM",)
    phase = 2

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out: list[Span] = []
        if "." not in text:
            return out
        for m in _LATLNG_RE.finditer(text):
            s, e = m.start("lat"), m.end("lon")
            out.append(Span(s, e, "KONUM", text[s:e], 0.9, self.name, f"{m['lat']},{m['lon']}"))
        taken = [(sp.start, sp.end) for sp in out]
        for m in _COORD_RE.finditer(text):
            s, e = m.start(), m.end()
            if any(a < e and s < b for a, b in taken):
                continue
            if (_NOT_COORD.search(text[max(0, s - 40) : s]) or _CURRENCY_AFTER.match(text[e : e + 8])
                    or not ctx.has_context(s, e, _CTX, window=40)):
                continue
            if not self._bound(ctx, s, e):
                continue  # "Koordinatlar 41.0082, 28.9784 noktasını gösteriyor": kişiyle ilişkisiz → kişisel veri değil
            out.append(Span(s, e, "KONUM", text[s:e], 0.85, self.name, f"{m['lat']},{m['lon']}"))
        return out

    @staticmethod
    def _bound(ctx: AnalysisContext, s: int, e: int) -> bool:
        ss, se = ctx.sentence_of(s)
        lo, hi = max(ss, s - 200), min(se, e + 200)
        if ctx.prior_in(lo, hi, _LOC_BIND):
            return True
        seg = ctx.casefolded[lo:hi]
        return _MARKERS.search(seg) is not None or _PERSONAL_LOC.search(seg) is not None
