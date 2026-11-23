"""Pozitif/karışık test fixture'larını üretir (tests/fixtures/{detect,revert,streaming,hooks}/*.yaml).

Tüm değerler sentetiktir: TCKN/VKN/IBAN/kart kontrol basamakları algoritmayla üretilir.
Beklentiler elle yazılmıştır (üreteç yalnız şablon × değer çarpımı yapar). Çalıştırma:
    python scripts/build_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from matriks_pii.recognizers.checksums import luhn_complete  # noqa: E402

FIX = ROOT / "tests" / "fixtures"

# ---------------------------------------------------------------- sentetik değerler
TCKN = ["17291716060", "10000000146", "44771278268", "26197306992", "52393849902", "79893557250", "15184715664",
        "17777786808", "98183655308", "67539892278", "20107136426", "49265548698"]
TCKN_BAD = ["17291716050", "10000000178", "12345678901", "44771278269", "26197306991"]
VKN = ["4540536920", "3973535717", "6448549736", "3305304193", "1402606623", "1922851420", "1750066914", "3584099295"]
VKN_BAD = ["4540536921", "3973535711", "6448549737"]
IBAN = ["TR330006100519786457841326", "TR920006101532418854210086", "TR960001006093156159526063",
        "TR090001209533868620643363", "TR930001506680172517175385", "TR020004606251171444815541"]
CARDS = {"visa": "4111111111111111", "mc": "5555555555554444", "troy": "9792000000000003", "visa2": "4543000000000006",
         "mc2": "5406000000000009"}
AMEX = "378282246310005"


def g4(s: str, sep: str = " ") -> str:
    return sep.join(s[i : i + 4] for i in range(0, len(s), 4))


def E(entity: str, value: str) -> dict[str, str]:
    return {"entity": entity, "value": value}


class Book:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.cases: list[dict[str, Any]] = []

    def add(self, text: str, expect: list[dict[str, str]], **kw: Any) -> None:
        c: dict[str, Any] = {"id": f"{self.prefix}-{len(self.cases) + 1:03d}", "text": text, "expect": expect}
        c.update({k: v for k, v in kw.items() if v is not None})
        self.cases.append(c)


def dump(path: Path, cases: list[dict[str, Any]], header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(cases, allow_unicode=True, sort_keys=False, width=200)
    path.write_text(f"# {header}\n# Üretildi: scripts/build_fixtures.py — tüm değerler sentetiktir.\n" + body, encoding="utf-8")


# ================================================================ detect/tckn (35)
def tckn() -> list[dict[str, Any]]:
    b = Book("TCKN")
    t = TCKN
    b.add(f"TC kimlik numaram {t[0]}, lütfen kaydedin.", [E("TCKN", t[0])], masked="TC kimlik numaram <TCKN_1>, lütfen kaydedin.")
    b.add(f"{t[1]} numaralı kimlik sahibi başvurdu.", [E("TCKN", t[1])])
    b.add(f"Başvuru sahibinin kimlik numarası: {t[2]}", [E("TCKN", t[2])])
    b.add(f"TC: {t[3]}", [E("TCKN", t[3])])
    b.add(f"T.C. Kimlik No: {t[4]}", [E("TCKN", t[4])])
    b.add(f'Kimlik no "{t[5]}" olarak girildi.', [E("TCKN", t[5])])
    b.add(f"Kimlik ({t[6]}) doğrulandı.", [E("TCKN", t[6])])
    b.add(f"| Alan | Değer |\n| TCKN | {t[7]} |", [E("TCKN", t[7])])
    b.add(f'{{"tckn": "{t[8]}", "durum": "aktif"}}', [E("TCKN", t[8])])
    b.add(f"Kimlik {t[9]} ve tekrar {t[9]} yazıldı.", [E("TCKN", t[9]), E("TCKN", t[9])],
          masked="Kimlik <TCKN_1> ve tekrar <TCKN_1> yazıldı.")
    b.add(f"İki kişi: {t[10]} ve {t[11]}.", [E("TCKN", t[10]), E("TCKN", t[11])], masked="İki kişi: <TCKN_1> ve <TCKN_2>.")
    b.add(f"tckn={t[0]}&islem=sorgu", [E("TCKN", t[0])])
    b.add(f"Kimlik numarası{t[1]}bitişik yazılmış.", [E("TCKN", t[1])], tags=["borderline"])
    b.add(f"Vatandaşın numarası {t[2]}.", [E("TCKN", t[2])])
    b.add(f"{t[3]}", [E("TCKN", t[3])])
    b.add(f"Numara:{t[4]};", [E("TCKN", t[4])])
    b.add(f"Kimlik numarası\n{t[5]}\nolarak kayıtlı.", [E("TCKN", t[5])])
    b.add(f"VKN yerine TCKN {t[6]} verildi (şahıs şirketi).", [E("TCKN", t[6])])
    b.add(f"Hasta TCKN: {t[7]}, protokol 2026-114.", [E("TCKN", t[7])])
    b.add(f"Kimlik: {t[8]}.", [E("TCKN", t[8])])
    for bad in TCKN_BAD:
        b.add(f"TC kimlik numarası {bad} doğrulanamadı.", [], tags=["invalid_checksum"])
    b.add("Kimlik numarası 07291716092 sıfırla başlıyor.", [], tags=["invalid_checksum"])
    b.add("On haneli 1729171606 numara TCKN değildir.", [])
    b.add("On iki haneli 172917160601 numara TCKN değildir.", [])
    b.add("Boşluklu yazım 172 917 160 60 tanınmaz.", [])
    b.add("Numara 53212345678 kontrol basamağı tutmuyor.", [], tags=["invalid_checksum"])
    b.add(f"IBAN {IBAN[0]} içinde TCKN aranmaz.", [E("IBAN", IBAN[0])], not_expect=["TCKN"])
    b.add(f"Kart {CARDS['visa']} ile ödendi.", [E("KART", CARDS["visa"])], not_expect=["TCKN"])
    b.add("TC kimlik numarası 12345678901 (geçersiz) bağlamla yakalanır.", [E("TCKN", "12345678901")],
          config={"tckn_require_checksum": False}, tags=["invalid_checksum"])
    b.add("Sipariş 12345678901 bağlamsız; checksum kapalıyken de yakalanmaz.", [], config={"tckn_require_checksum": False})
    return b.cases


# ================================================================ detect/vkn (20)
def vkn() -> list[dict[str, Any]]:
    b = Book("VKN")
    v = VKN
    b.add(f"Vergi No: {v[0]}", [E("VKN", v[0])], masked="Vergi No: <VKN_1>")
    b.add(f"VKN {v[1]} olan firma.", [E("VKN", v[1])])
    b.add(f"Vergi kimlik numarası {v[2]} kayıtlı.", [E("VKN", v[2])])
    b.add(f"Vergi Dairesi: Kadıköy VKN: {v[3]}", [E("VKN", v[3])])
    b.add(f"Mükellef {v[4]} beyannamesini verdi.", [E("VKN", v[4])])
    b.add(f"v.k.n. {v[5]}", [E("VKN", v[5])])
    b.add(f"Firmanın vergi numarası {v[6]} ve {v[7]} şubeleri.", [E("VKN", v[6]), E("VKN", v[7])])
    b.add(f'{{"vergi_no": "{v[0]}"}}', [E("VKN", v[0])])
    b.add(f"Vergi levhası: {v[1]}", [E("VKN", v[1])])
    b.add(f"Fatura bilgisi — vergi: {v[2]}", [E("VKN", v[2])])
    b.add(f"Sipariş numarası {v[3]} hazırlanıyor.", [], tags=["no_context"])
    b.add(f"Referans {v[4]} kayda alındı.", [], tags=["no_context"])
    for bad in VKN_BAD:
        b.add(f"Vergi No: {bad} hatalı.", [], tags=["invalid_checksum"])
    b.add(f"Vergi numarası olarak TCKN {TCKN[0]} kullanıldı.", [E("TCKN", TCKN[0])], not_expect=["VKN"])
    b.add(f"VKN {v[5]}, {v[6]} ve {v[7]}", [E("VKN", v[5]), E("VKN", v[6]), E("VKN", v[7])])
    b.add(f"Vergi dairesi Beşiktaş, numara {v[0]}.", [E("VKN", v[0])])
    b.add(f"Tedarikçi VKN'si {v[1]}'dir.", [E("VKN", v[1])])
    b.add(f"Müşteri vergi no {v[2]}", [E("VKN", v[2])])
    return b.cases


# ================================================================ detect/iban (25)
def iban() -> list[dict[str, Any]]:
    b = Book("IBAN")
    i = IBAN
    b.add(f"IBAN: {g4(i[0])}", [E("IBAN", g4(i[0]))], masked="IBAN: <IBAN_1>")
    b.add(f"IBAN {i[1]} hesabına gönderin.", [E("IBAN", i[1])])
    b.add(f"Hesap: {g4(i[2], '-')}", [E("IBAN", g4(i[2], "-"))])
    b.add(f"iban: {g4(i[3]).lower()}", [E("IBAN", g4(i[3]).lower())])
    b.add(f"Alıcı IBAN'ı {i[4]}'dir.", [E("IBAN", i[4])])
    b.add(f"IBAN numaram\n{g4(i[5])}\nteşekkürler", [E("IBAN", g4(i[5]))])
    b.add(f"İki IBAN: {i[0]} ve {i[1]}", [E("IBAN", i[0]), E("IBAN", i[1])], masked="İki IBAN: <IBAN_1> ve <IBAN_2>")
    b.add(f"Aynı IBAN {i[2]} / {g4(i[2])}", [E("IBAN", i[2]), E("IBAN", g4(i[2]))],
          masked="Aynı IBAN <IBAN_1> / <IBAN_1>", tags=["surface_variants"])
    b.add(f'{{"iban":"{i[3]}","tutar":1500}}', [E("IBAN", i[3])])
    b.add("Alman IBAN DE89370400440532013000 ile ödeme.", [E("IBAN", "DE89370400440532013000")])
    b.add("İngiliz IBAN GB29NWBK60161331926819 geçerlidir.", [E("IBAN", "GB29NWBK60161331926819")])
    b.add("Fransız IBAN FR7630006000011234567890189 kayıtlı.", [E("IBAN", "FR7630006000011234567890189")])
    b.add("Almanya: DE89 3704 0044 0532 0130 00", [E("IBAN", "DE89 3704 0044 0532 0130 00")])
    b.add("IBAN TR330006100519786457841327 kontrol basamağı hatalı.", [], tags=["invalid_checksum"])
    b.add("TR33 0006 1005 1978 6457 8413 2 eksik.", [])
    b.add("TR3300061005197864578413267 fazla haneli.", [])
    b.add("TRANSFER 1234 5678 9012 numaralı işlem.", [])
    b.add(f"IBAN içindeki rakamlar TCKN sayılmaz: {i[5]}", [E("IBAN", i[5])], not_expect=["TCKN", "KART", "VKN"])
    b.add(f"Ödeme {i[0]}.", [E("IBAN", i[0])])
    b.add(f"IBAN:{i[1]}", [E("IBAN", i[1])])
    b.add(f"({g4(i[2])})", [E("IBAN", g4(i[2]))])
    b.add(f"IBAN {g4(i[3])} - Ziraat", [E("IBAN", g4(i[3]))])
    b.add(f"Hesap sahibine ait {i[4]} numaralı IBAN.", [E("IBAN", i[4])])
    b.add("ISIN TRATHYAO91M5 IBAN değildir.", [])
    b.add(f"IBAN'ım {i[5]}, kartım yok.", [E("IBAN", i[5])])
    return b.cases


# ================================================================ detect/kart (35)
def kart() -> list[dict[str, Any]]:
    b = Book("KART")
    for name, c in CARDS.items():
        b.add(f"Kart numaram {c} ({name}).", [E("KART", c)])
        b.add(f"Kart: {g4(c)}", [E("KART", g4(c))])
        b.add(f"Kart {g4(c, '-')} ile ödeme.", [E("KART", g4(c, "-"))])
    b.add(f"Amex {AMEX} kullanıldı.", [E("KART", AMEX)])
    b.add("Amex 3782 822463 10005 kullanıldı.", [E("KART", "3782 822463 10005")])
    b.add("Kart 4111 1111 1111 1112 Luhn'dan geçmez.", [])
    b.add("Kart 1234 5678 9012 3456 geçersiz.", [])
    b.add("Kart **** **** **** 1234 ile ödendi.", [])
    b.add("Kod 8888888888888888 BIN dışı.", [])
    b.add(f"19 haneli {luhn_complete('4', 19)} kart.", [E("KART", luhn_complete("4", 19))])
    b.add(f"İki kart {CARDS['visa']} ve {CARDS['mc']}.", [E("KART", CARDS["visa"]), E("KART", CARDS["mc"])])
    b.add(f"Kart {CARDS['troy']}, CVV 123, son kullanma 12/27.",
          [E("KART", CARDS["troy"]), E("KART_CVV", "123"), E("KART_SKT", "12/27")])
    b.add("CVV: 456 bilgisini kimseyle paylaşmayın.", [E("KART_CVV", "456")])
    b.add("Güvenlik kodu 7890 girildi.", [E("KART_CVV", "7890")])
    b.add("CVC2 kodu: 321", [E("KART_CVV", "321")])
    b.add("SKT 03/2028 olan kart.", [E("KART_SKT", "03/2028")])
    b.add("Son kullanma tarihi: 11/26", [E("KART_SKT", "11/26")])
    b.add("Expiry 09/29, kart aktif.", [E("KART_SKT", "09/29")])
    b.add("Fatura dönemi 12/27 sayfasında.", [])
    b.add("CVV kodunu asla paylaşmayın.", [])
    b.add(f"Kart numarası:{CARDS['visa2']}", [E("KART", CARDS["visa2"])])
    b.add(f"Kart {CARDS['mc2']}'ten çekim yapıldı.", [E("KART", CARDS["mc2"])])
    b.add(f"Visa {CARDS['visa']} CVV 999", [E("KART", CARDS["visa"]), E("KART_CVV", "999")])
    b.add(f"Ödeme bilgisi {{\"card\": \"{CARDS['mc']}\"}}", [E("KART", CARDS["mc"])])
    return b.cases


# ================================================================ detect/telefon (45)
PHONE_FORMATS = [
    "0532 234 56 78", "05322345678", "+90 532 234 56 78", "+905322345678", "0 (532) 234 56 78", "(0532) 234 56 78",
    "532 234 56 78", "0532-234-56-78", "0532.234.56.78", "90 532 234 5678", "0090 532 234 56 78", "+90(532)2345678",
    "0532 234 5678",
]


def telefon() -> list[dict[str, Any]]:
    b = Book("TELEFON")
    for f in PHONE_FORMATS:
        b.add(f"Cep telefonum {f}, arayabilirsiniz.", [E("TELEFON", f)])
    landline = ["0212 345 67 89", "0216 444 55 66", "(0312) 456 78 90", "+90 232 345 67 89", "0224 567 89 01",
                "0 242 678 90 12", "0850 222 33 44"]
    for f in landline:
        b.add(f"Ofis: {f}", [E("TELEFON", f)])
    b.add("Cep: 0532 123 45 67", [E("TELEFON", "0532 123 45 67")])
    b.add("Telefon 0505 987 65 43 ve 0555 876 54 32.", [E("TELEFON", "0505 987 65 43"), E("TELEFON", "0555 876 54 32")])
    b.add("Numara 0532 234 56 78 ve tekrar +90 532 234 56 78.", [E("TELEFON", "0532 234 56 78"), E("TELEFON", "+90 532 234 56 78")],
          masked="Numara <TELEFON_1> ve tekrar <TELEFON_1>.", tags=["surface_variants"])
    b.add("Çağrı merkezi 444 0 123", [])
    b.add("Çağrı merkezi 444 0 123", [E("TELEFON", "444 0 123")], config={"phone": {"mask_444": True}})
    b.add("Ücretsiz hat 0800 211 00 00", [])
    b.add("Ücretsiz hat 0800 211 00 00", [E("TELEFON", "0800 211 00 00")], config={"phone": {"mask_800": True}})
    b.add("Geçersiz alan kodu 0 199 234 56 78", [])
    b.add("Sabit hat 0212 123 45 67 abone 1 ile başlar.", [])
    b.add("Kısa numara 234 56 78 yeterli değil.", [])
    b.add("Uzun dizi 053223456789012 telefon değil.", [])
    b.add("Toplantı 28.10.2026 14:30'da.", [])
    b.add("Fiyat 532,34 TL oldu.", [])
    b.add("532 lot alındı, 216 lot satıldı.", [])
    b.add("WhatsApp: 05442345678", [E("TELEFON", "05442345678")])
    b.add("Tel:+905062345678", [E("TELEFON", "+905062345678")])
    b.add("GSM 0 543 234 56 78 aktif.", [E("TELEFON", "0 543 234 56 78")])
    b.add("Fax (0212) 234-56-78", [E("TELEFON", "(0212) 234-56-78")])
    b.add('{"telefon": "05322345678"}', [E("TELEFON", "05322345678")])
    b.add("Beni 0532 234 56 78'den arayın.", [E("TELEFON", "0532 234 56 78")])
    b.add("Mobil 0561 234 56 78 yeni hat.", [E("TELEFON", "0561 234 56 78")])
    b.add("Kanun 5411 sayılı, madde 73.", [])
    b.add("Tarih 2024-05-32 değil.", [])
    return b.cases


# ================================================================ detect/eposta (15), ip (10)
def eposta() -> list[dict[str, Any]]:
    b = Book("EPOSTA")
    for e in ["ayse.demir@ornek.com.tr", "ahmet_yilmaz+test@mail.example.com", "info@ornek-sirket.com.tr", "AHMET@ORNEK.COM",
              "çağrı.öztürk@örnek.com.tr", "a.b-c@sub.domain.co.uk"]:
        b.add(f"E-posta adresim {e}, yazabilirsiniz.", [E("EPOSTA", e)])
    b.add("mailto:destek@ornek.com.tr bağlantısı", [E("EPOSTA", "destek@ornek.com.tr")])
    b.add("İki adres: a1@x.com ve b2@y.org", [E("EPOSTA", "a1@x.com"), E("EPOSTA", "b2@y.org")])
    b.add("<ayse@ornek.com>", [E("EPOSTA", "ayse@ornek.com")])
    b.add("ahmet.yilmaz@firma.com.tr adresine yazın.", [E("EPOSTA", "ahmet.yilmaz@firma.com.tr")], not_expect=["KISI"])
    b.add("@ahmet etiketi mention'dır.", [])
    b.add("a@b geçerli değildir.", [])
    b.add("E-posta (kullanici at ornek nokta com) gizlenmiş.", [])
    b.add('{"email":"x.y@z.io"}', [E("EPOSTA", "x.y@z.io")])
    b.add("Adres: Ayse.Demir@Ornek.Com.Tr", [E("EPOSTA", "Ayse.Demir@Ornek.Com.Tr")])
    return b.cases


def ip() -> list[dict[str, Any]]:
    b = Book("IP")
    b.add("İstemci IP 192.168.1.15 adresinden bağlandı.", [E("IP", "192.168.1.15")])
    b.add("Sunucu 10.0.0.1:8080 portunda.", [E("IP", "10.0.0.1")])
    b.add("IPv6 2001:db8::8a2e:370:7334 kaydedildi.", [E("IP", "2001:db8::8a2e:370:7334")])
    b.add("Kaynak 203.0.113.34, hedef 8.8.8.8", [E("IP", "203.0.113.34"), E("IP", "8.8.8.8")])
    b.add("Sürüm 1.2.3.4 yayımlandı.", [])
    b.add("v2.0.1.3 güncellemesi.", [])
    b.add("256.1.1.1 geçersiz.", [])
    b.add("MAC 00:1A:2B:3C:4D:5E görüldü.", [])
    b.add("MAC 00:1A:2B:3C:4D:5E görüldü.", [E("MAC", "00:1A:2B:3C:4D:5E")], config={"entities": {"MAC": "MASK"}})
    b.add("Ondalık 3.14 sayı.", [])
    return b.cases


# ================================================================ detect/plaka (25)
def plaka() -> list[dict[str, Any]]:
    b = Book("PLAKA")
    for p in ["34 ABC 123", "06 A 1234", "35 AB 1234", "16 AB 123", "01 A 12345", "81 ZZ 999", "34-ABC-123", "34 TAB 12",
              "06 CD 123"]:
        b.add(f"Aracın plakası {p} olarak kayıtlı.", [E("PLAKA", p)])
    b.add("Plaka: 34ABC123", [E("PLAKA", "34ABC123")])
    b.add("Araç 06AB1234 servisteydi.", [E("PLAKA", "06AB1234")])
    b.add("Kod 34ABC123 depo etiketi.", [])
    b.add("00 AB 123 geçersiz il.", [])
    b.add("82 AB 123 geçersiz il.", [])
    b.add("34 QWX 123 yasak harf.", [])
    b.add("34 BIN 500 lot.", [])
    b.add("34 THYAO 12 lot.", [])
    b.add("12 05 2024 tarih.", [])
    b.add("34 TL 100 fiyat.", [])
    b.add("34 A 123 eksik rakam.", [])
    b.add("İki araç: 34 ABC 123 ve 06 DEF 45.", [E("PLAKA", "34 ABC 123"), E("PLAKA", "06 DEF 45")])
    b.add("Plakası 34 ABC 123'tür.", [E("PLAKA", "34 ABC 123")])
    b.add('{"plaka":"35 KL 2468"}', [E("PLAKA", "35 KL 2468")])
    b.add("Ruhsat sahibi aracın plakası 41 PR 567.", [E("PLAKA", "41 PR 567")])
    b.add("Plaka 34 ŞK 123 Türkçe harf içeremez.", [])
    return b.cases


# ================================================================ detect/kimlik_belgeleri (25)
def kimlik() -> list[dict[str, Any]]:
    b = Book("KIMLIK")
    b.add("Pasaport numaram U12345678.", [E("PASAPORT", "U12345678")])
    b.add("Passport no: A98765432", [E("PASAPORT", "A98765432")])
    b.add("pasaport no u23456789", [E("PASAPORT", "u23456789")])
    b.add("U12345678 depo kodu.", [])
    b.add("Kimlik kartı seri no A12B34567", [E("KIMLIK_SERI", "A12B34567")])
    b.add("Nüfus cüzdanı seri numarası ABC123456", [E("KIMLIK_SERI", "ABC123456")])
    b.add("Ehliyet numarası 123456.", [E("EHLIYET", "123456")])
    b.add("Sürücü belgesi no: 654321", [E("EHLIYET", "654321")])
    b.add("SGK sicil no 1234567890", [E("SGK", "1234567890")])
    b.add("Sigorta sicil numarası 9876543", [E("SGK", "9876543")])
    b.add("İşyeri sicil numarası 12345678901234567890123456", [E("SGK", "12345678901234567890123456")])
    b.add("Nüfusa kayıtlı olduğu cilt no: 12, aile sıra no: 345, sıra no: 6",
          [E("NUFUS_KAYIT", "12"), E("NUFUS_KAYIT", "345"), E("NUFUS_KAYIT", "6")])
    b.add("Sıra no 1, 2, 3 satırlar.", [])
    b.add("SGK prim oranı %20,5.", [])
    b.add("Sigorta sicil kayıtları arşivde tutulur; arşiv raf kodu, ilgili yönetmelik hükümlerine göre, ayrı bir listede 9876543 olarak saklanır.", [])
    b.add("Ehliyet sınavı 50 soru.", [])
    b.add('{"pasaport_no": "Pasaport U87654321"}', [E("PASAPORT", "U87654321")])
    b.add("Kod 123456 SMS ile gönderildi.", [])
    b.add("Pasaport: P12345678, ehliyet: 112233", [E("PASAPORT", "P12345678"), E("EHLIYET", "112233")])
    b.add("SSK no 12345678", [E("SGK", "12345678")])
    b.add("Emekli sicil numarası 7654321", [E("SGK", "7654321")])
    b.add("Kimlik kartı belge no: XYZ987654", [E("KIMLIK_SERI", "XYZ987654")])
    b.add("Pasaport başvurusu için randevu alındı.", [])
    b.add("Bağ-Kur no 22334455", [E("SGK", "22334455")])
    b.add("Ehliyetimin numarası 998877", [E("EHLIYET", "998877")])
    return b.cases


# ================================================================ detect/dogum (25)
def dogum() -> list[dict[str, Any]]:
    b = Book("DOGUM")
    for d in ["12.03.1985", "1/2/1990", "05-11-1978", "12 Mart 1985", "3 Ağustos 2001", "1985-03-12"]:
        b.add(f"Doğum tarihi: {d}", [E("DOGUM_TARIHI", d)])
    b.add("D.T. 01.01.1970", [E("DOGUM_TARIHI", "01.01.1970")])
    b.add("15.06.1992 doğumluyum.", [E("DOGUM_TARIHI", "15.06.1992")])
    b.add("Kendisi 23 Nisan 1999'da doğdu.", [E("DOGUM_TARIHI", "23 Nisan 1999")])
    b.add("İşlem tarihi 28.10.2026.", [])
    b.add("Kuruluş 1856.", [])
    b.add("Tebliğ 12 Mart 1985 tarihli.", [])
    b.add("Doğum günü partisi 12.05.2026'da yapılacak.", [E("DOGUM_TARIHI", "12.05.2026")], tags=["borderline"])
    b.add("Yaşam boyu 01.01.2000 tarihinden beri.", [])
    b.add("Doğum tarihleri: 01.02.1980 ve 03.04.1982", [E("DOGUM_TARIHI", "01.02.1980"), E("DOGUM_TARIHI", "03.04.1982")])
    b.add("Doğum yeri: Kadıköy", [E("DOGUM_YERI", "Kadıköy")])
    b.add("Doğum yeri ve tarihi: İzmir / 05.05.1975", [E("DOGUM_YERI", "İzmir"), E("DOGUM_TARIHI", "05.05.1975")])
    b.add("1980 Trabzon doğumlu.", [E("DOGUM_YERI", "Trabzon")])
    b.add("Erzurum'da doğdu.", [E("DOGUM_YERI", "Erzurum")])
    b.add("İzmir'e taşındı.", [])
    b.add("Ankara güzel bir şehir.", [])
    b.add('{"dogum_tarihi": "Doğum: 10.10.1990"}', [E("DOGUM_TARIHI", "10.10.1990")])
    b.add("Valör 30.10.2026, vade 12.03.2027.", [])
    b.add("Doğum: 7 Temmuz 1965", [E("DOGUM_TARIHI", "7 Temmuz 1965")])
    b.add("Lozan 24 Temmuz 1923'te imzalandı.", [])
    return b.cases


# ================================================================ detect/finans_kimlikleri (30)
def finans() -> list[dict[str, Any]]:
    b = Book("FINANS")
    b.add("Hesap No: 1234567", [E("HESAP_NO", "1234567")])
    b.add("Yatırım hesap numaram 98765432.", [E("HESAP_NO", "98765432")])
    b.add("Hesap numarası 123-4567890-1", [E("HESAP_NO", "123-4567890-1")])
    b.add("Müşteri No: 556677", [E("MUSTERI_NO", "556677")])
    b.add("Müşteri numaranız 12345678 olarak tanımlandı.", [E("MUSTERI_NO", "12345678")])
    b.add("Cari kod 400123", [E("MUSTERI_NO", "400123")])
    b.add("Mersis no 0123456789000015", [E("MERSIS", "0123456789000015")])
    b.add("MERSİS numarası 4540536920000017", [E("MERSIS", "4540536920000017")])
    b.add("ETTN 550e8400-e29b-41d4-a716-446655440000", [E("ETTN", "550e8400-e29b-41d4-a716-446655440000")])
    b.add("UUID 550e8400-e29b-41d4-a716-446655440000 kayda atandı.", [])
    b.add("IMEI 356938035643809", [E("IMEI", "356938035643809")])
    b.add("IMEI 356938035643800 geçersiz.", [])
    b.add("Şasi no WVWZZZ1JZXW000001", [E("SASI_NO", "WVWZZZ1JZXW000001")])
    b.add("VIN: 1HGCM82633A004352", [E("SASI_NO", "1HGCM82633A004352")])
    b.add("BTC 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", [])
    b.add("BTC 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", [E("KRIPTO_CUZDAN", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")],
          config={"entities": {"KRIPTO_CUZDAN": "MASK"}})
    b.add("ETH 0x742d35Cc6634C0532925a3b844Bc454e4438f44e", [E("KRIPTO_CUZDAN", "0x742d35Cc6634C0532925a3b844Bc454e4438f44e")],
          config={"entities": {"KRIPTO_CUZDAN": "MASK"}})
    b.add("Şifre: Gizli123!", [E("SIFRE", "Gizli123!")])
    b.add("password=Abc12345", [E("SIFRE", "Abc12345")])
    b.add("Parolam: kedi2026", [E("SIFRE", "kedi2026")])
    b.add("PIN kodu 5321 SIM kartta.", [E("SIFRE", "5321")])
    b.add("Şifre sıfırlama bağlantısı gönderildi.", [])
    b.add("MKK sicil no MK-001234", [E("MKK_SICIL", "MK-001234")],
          config={"extra_regex": [{"entity": "MKK_SICIL", "pattern": r"MK-[0-9]{6}", "score": 0.9}]})
    b.add("Hesap sayısı 1234567 oldu.", [])
    b.add("Müşteri kodu 1020304050 CRM'de.", [])
    b.add("Abone numarası 98765432109 pasif.", [])
    b.add("Hesap no 51978 kısa.", [])
    b.add('{"hesap_no": "Hesap no 7654321"}', [E("HESAP_NO", "7654321")])
    b.add("Müşteri numarası 445566 ve hesap no 7788990", [E("MUSTERI_NO", "445566"), E("HESAP_NO", "7788990")])
    b.add("Account no 11223344", [E("HESAP_NO", "11223344")])
    return b.cases


# ================================================================ detect/adres (35)
def adres() -> list[dict[str, Any]]:
    b = Book("ADRES")
    full = [
        "Atatürk Mah. Gül Sok. No:5 D:3 34710 Kadıköy/İstanbul",
        "Cumhuriyet Mahallesi Lale Sokak No: 12 Daire 4 Çankaya/Ankara",
        "Bağdat Caddesi No:250 Kat:3 Kadıköy İstanbul",
        "Kızılay Mah. Atatürk Bulvarı No:45 Çankaya Ankara",
        "Barbaros Bulvarı No:100 Beşiktaş/İstanbul",
        "Alsancak Mah. 1453 Sok. No:7 Konak/İzmir",
        "Yeni Mah. Çınar Cad. No: 8/2 Nilüfer/Bursa",
        "Levent Mah. Büyükdere Cad. No:185 Kat:12 Şişli",
        "Kordon Apt. Daire 5 Kat:2 Karşıyaka",
        "Mavi Sitesi B Blok Daire 12 Ataşehir/İstanbul",
        "Gül Sok. No:3 Üsküdar",
        "Ahmet Yılmaz Sok. No:4 Maltepe",
    ]
    for a in full:
        b.add(f"Adresim: {a}", [E("ADRES", a)], not_expect=["KISI"])
    b.add("No:5 Kadıköy", [E("ADRES", "No:5 Kadıköy")])
    b.add("34710 Kadıköy/İstanbul", [E("ADRES", "34710 Kadıköy/İstanbul")])
    b.add("Kadıköy çarşısı kalabalıktı.", [])
    b.add("Posta kodu 34000 tek başına.", [])
    b.add("Mahalle baskısı deyimi.", [])
    b.add("Katılım bankacılığı büyüdü.", [])
    b.add("1600 Pennsylvania Avenue, Washington DC 20500", [])
    b.add("No: 5 madde uyarınca.", [])
    b.add("Teslimat adresi:\nAtatürk Mah. Gül Sok.\nNo:5 Kadıköy/İstanbul",
          [E("ADRES", "Atatürk Mah. Gül Sok.\nNo:5 Kadıköy/İstanbul")], tags=["borderline"])
    b.add("Şirket merkezi: Maslak Mah. Ahi Evran Cad. No:6 Sarıyer/İstanbul",
          [E("ADRES", "Maslak Mah. Ahi Evran Cad. No:6 Sarıyer/İstanbul")])
    b.add("Adres Gül Sok. No:3 Kadıköy, telefon 0532 234 56 78",
          [E("ADRES", "Gül Sok. No:3 Kadıköy"), E("TELEFON", "0532 234 56 78")])
    b.add("İki adres: Gül Sok. No:3 Kadıköy ve Lale Cad. No:9 Bornova.",
          [E("ADRES", "Gül Sok. No:3 Kadıköy"), E("ADRES", "Lale Cad. No:9 Bornova")])
    b.add('{"adres": "Atatürk Cad. No:1 Merkez/Sivas"}', [E("ADRES", "Atatürk Cad. No:1 Merkez/Sivas")])
    b.add("Sokak hayvanları için mama.", [])
    b.add("Plaza çalışanları dışarı çıktı.", [])
    b.add("Blok zinciri teknolojisi.", [])
    b.add("İstanbul'da hava yağmurlu.", [])
    b.add("Cadde üzerinde trafik var.", [])
    b.add("Kat: 3 yazan etiket.", [])
    b.add("D: sürücüsü doldu.", [])
    b.add("Residence projeleri arttı.", [])
    b.add("Adresi Fatih Mah. Vatan Cad. No:12/3 Fatih İstanbul'dur.",
          [E("ADRES", "Fatih Mah. Vatan Cad. No:12/3 Fatih İstanbul'dur")], tags=["borderline"])
    return b.cases


# ================================================================ detect/kisi (80)
def kisi() -> list[dict[str, Any]]:
    b = Book("KISI")
    full = ["Ahmet Yılmaz", "Ayşe Demir", "Mehmet Öztürk", "Fatma Şahin", "Mustafa Çelik", "Zeynep Arslan", "Emre Koç",
            "Elif Aydın", "Burak Kurt", "Merve Polat", "Hasan Doğan", "Hüseyin Kaya", "AHMET YILMAZ", "Ali Rıza Yıldız",
            "Gülşen Er", "Cem Karaca"]
    for n in full:
        b.add(f"Dün {n} ile görüştüm.", [E("KISI", n)])
    hon = [("Sayın Gürkan", "Gürkan"), ("Sn. Akın", "Akın"), ("Dr. Selim", "Selim"), ("Av. Nesrin", "Nesrin"),
           ("Prof. Halil", "Halil"), ("Bay Kemal", "Kemal"), ("Bayan Sevim", "Sevim")]
    for s, n in hon:
        b.add(f"{s} toplantıya katıldı.", [E("KISI", n)])
    for n in ["Ahmet Bey", "Ayşe Hanım", "Mehmet Beyefendi", "Zehra Hanımefendi", "Aydın Bey"]:
        b.add(f"{n} aradı.", [E("KISI", n.split()[0])])
    b.add("YILMAZ, Ahmet başvurdu.", [E("KISI", "YILMAZ, Ahmet")], tags=["borderline"])
    b.add("Öztürk, Mehmet raporu imzaladı.", [E("KISI", "Öztürk, Mehmet")])
    b.add("Raporu A. Öztürk imzaladı.", [E("KISI", "A. Öztürk")])
    b.add("Dün Deniz aradı.", [E("KISI", "Deniz")])
    b.add("Deniz çok güzel.", [])
    b.add("Bugün Mehmet geldi.", [E("KISI", "Mehmet")])
    b.add("Mehmet geldi.", [E("KISI", "Mehmet")])
    b.add("Müşteri Mehmet aradı.", [E("KISI", "Mehmet")])
    b.add("Müşteri adı: Ayşe", [E("KISI", "Ayşe")])
    b.add("Annesinin adı Fatma.", [E("KISI", "Fatma")])
    b.add("Baba adı: Hüseyin", [E("KISI", "Hüseyin")])
    b.add("Ahmet isimli müşteri geldi.", [E("KISI", "Ahmet")])
    b.add("Ahmet Yılmaz'ın dosyası.", [E("KISI", "Ahmet Yılmaz")], masked="<KISI_1>'ın dosyası.")
    b.add("Ayşe'nin hesabı açıldı.", [E("KISI", "Ayşe")], tags=["borderline"])
    b.add("Dosyayı Ayşe'ye ilettim.", [E("KISI", "Ayşe")])
    b.add("Raporu Mehmet’e gönder.", [E("KISI", "Mehmet")])
    b.add("Raporu Mehmetʼe gönder.", [E("KISI", "Mehmet")])
    b.add("AHMET'İN imzası eksik.", [E("KISI", "AHMET")], tags=["borderline"])  # apostroflu BÜYÜK ad
    b.add("Dün Ahmetin aradığını söyledi.", [E("KISI", "Ahmet")])
    b.add("Ayşe Demir'le görüştüm.", [E("KISI", "Ayşe Demir")])
    b.add("Aydın'a gittim.", [])
    b.add("Tatil için Aydın'a gittik.", [])
    b.add("15 Mayıs tarihinde toplantı.", [])
    b.add("Mustafa Kemal Atatürk 1881'de doğdu.", [], tags=["tarihi_kisi"])
    b.add("Türk Hava Yolları uçağı indi.", [])
    b.add("Koç Holding kâr açıkladı.", [])
    b.add("Ahmet Yılmaz geldi. Ahmet çok yorgundu.", [E("KISI", "Ahmet Yılmaz"), E("KISI", "Ahmet")],
          masked="<KISI_1> geldi. <KISI_2> çok yorgundu.")
    b.add("Ahmet Yılmaz, AHMET YILMAZ ve Ahmet Yılmaz aynı kişi.",
          [E("KISI", "Ahmet Yılmaz"), E("KISI", "AHMET YILMAZ"), E("KISI", "Ahmet Yılmaz")],
          masked="<KISI_1>, <KISI_1> ve <KISI_1> aynı kişi.", tags=["surface_variants"])
    b.add("ahmet.yilmaz@ornek.com adresine yaz.", [E("EPOSTA", "ahmet.yilmaz@ornek.com")], not_expect=["KISI"])
    b.add('{"ad_soyad": "Zeynep Arslan"}', [E("KISI", "Zeynep Arslan")])
    b.add("| Ad | Soyad |\n| Elif | Aydın |", [], tags=["borderline"])
    b.add("- Katılımcılar: Emre Koç, Merve Polat", [E("KISI", "Emre Koç"), E("KISI", "Merve Polat")])
    b.add("Sigortalı Hatice Güneş başvurdu.", [E("KISI", "Hatice Güneş")])
    b.add("Kızlık soyadı Çelik.", [E("KISI", "Çelik")], tags=["borderline"])
    b.add("ahmet yılmaz küçük harfle yazdı.", [E("KISI", "ahmet yılmaz")], tags=["lowercase"])
    b.add("müşteri: şule önal, tel 0532 234 56 78", [E("KISI", "şule önal"), E("TELEFON", "0532 234 56 78")], tags=["lowercase"])
    b.add("selam ben zeynep kaya, şifremi unuttum", [E("KISI", "zeynep kaya")], tags=["lowercase"])
    b.add("ayşe demir toplantıya katılmıyor.", [E("KISI", "ayşe demir")], tags=["lowercase"])
    b.add("mehmet öztürk raporu gönderdi.", [E("KISI", "mehmet öztürk")], tags=["lowercase"])
    b.add("Jerome Powell konuştu.", [])
    b.add("THYAO ve GARAN yükseldi.", [])
    b.add("Yıldız Pazar'da işlem gördü.", [])
    b.add("Dün Kıymet Hanım geldi.", [E("KISI", "Kıymet")])
    b.add("Dr. Ayşe Kaya muayene etti.", [E("KISI", "Ayşe Kaya")])
    b.add("Sayın Ahmet Yılmaz, başvurunuz alındı.", [E("KISI", "Ahmet Yılmaz")])
    b.add("Merhaba Selin Erdem, hoş geldiniz.", [E("KISI", "Selin Erdem")])
    b.add("Personel Murat Aksoy izinde.", [E("KISI", "Murat Aksoy")])
    b.add("Kefil Osman Tekin imzaladı.", [E("KISI", "Osman Tekin")])
    b.add("Alıcı: İbrahim Kılıç", [E("KISI", "İbrahim Kılıç")])
    b.add("Gönderen Esra Özkan.", [E("KISI", "Esra Özkan")])
    b.add("Tanık Kerem Bulut ifade verdi.", [E("KISI", "Kerem Bulut")])
    b.add("Mehmet'in hesabı dondu.", [E("KISI", "Mehmet")])
    b.add("Emir Bey bugün aradı.", [E("KISI", "Emir")])
    b.add("Müşteri temsilcimiz Büşra Yıldırım size dönecek.", [E("KISI", "Büşra Yıldırım")])
    b.add("Yetkili: Okan Şimşek", [E("KISI", "Okan Şimşek")])
    b.add("Başvuran Seda Karakaya, TCKN 44771278268.", [E("KISI", "Seda Karakaya"), E("TCKN", "44771278268")])
    b.add("CC: Tolga Erdoğan, Pınar Aksu", [E("KISI", "Tolga Erdoğan"), E("KISI", "Pınar Aksu")])
    b.add("Saygılarımla,\nGökhan Yücel\nPortföy Yöneticisi", [E("KISI", "Gökhan Yücel")])
    b.add("Hesap sahibi: SERKAN DOĞRU", [E("KISI", "SERKAN DOĞRU")], tags=["borderline"])
    b.add("Kemal'le konuştum, Ayşe'ye de ilettim.", [E("KISI", "Kemal"), E("KISI", "Ayşe")])
    b.add("Deniz Yılmaz'ın portföyü güncellendi.", [E("KISI", "Deniz Yılmaz")])
    return b.cases


# ================================================================ detect/ozel_nitelikli (50)
def ozel() -> list[dict[str, Any]]:
    b = Book("OZEL")
    P = "Müşterimiz Ahmet Yılmaz"
    K = E("KISI", "Ahmet Yılmaz")
    b.add(f"{P} diyabet hastasıdır.", [K, E("OZEL_SAGLIK", "diyabet hastasıdır")])
    b.add(f"{P} kanser tedavisi görüyor.", [K, E("OZEL_SAGLIK", "kanser tedavisi")])
    b.add(f"{P} kan grubu A Rh+.", [K, E("OZEL_SAGLIK", "kan grubu A Rh+")])
    b.add(f"{P} engelli raporu sundu.", [K, E("OZEL_SAGLIK", "engelli raporu")])
    b.add(f"{P} depresyon nedeniyle izinli.", [K, E("OZEL_SAGLIK", "depresyon")])
    b.add(f"{P} hamile olduğunu bildirdi.", [K, E("OZEL_SAGLIK", "hamile")])
    b.add("Ben diyabetim.", [E("OZEL_SAGLIK", "diyabetim")])
    b.add("Şeker hastasıyım, insülin kullanıyorum.", [E("OZEL_SAGLIK", "Şeker hastasıyım"), E("OZEL_SAGLIK", "insülin")])
    b.add(f"{P} DNA testi yaptırdı.", [K, E("OZEL_GENETIK", "DNA testi")])
    b.add(f"{P} BRCA1 taşıyıcısı.", [K, E("OZEL_GENETIK", "BRCA1 taşıyıcısı")])
    b.add(f"{P} parmak izi verisi alındı.", [K, E("OZEL_BIYOMETRIK", "parmak izi verisi")])
    b.add(f"{P} retina taraması yaptırdı.", [K, E("OZEL_BIYOMETRIK", "retina taraması")])
    b.add(f"{P} eşcinsel olduğunu açıkladı.", [K, E("OZEL_CINSEL", "eşcinsel")])
    b.add(f"{P} hapis cezası aldı.", [K, E("OZEL_CEZA", "hapis cezası")])
    b.add(f"{P} sabıkalı.", [K, E("OZEL_CEZA", "sabıkalı")])
    b.add(f"{P} denetimli serbestlikte.", [K, E("OZEL_CEZA", "denetimli serbestlikte")])
    b.add(f"{P} gözaltına alındı.", [K, E("OZEL_CEZA_GENIS", "gözaltına alındı")])
    b.add(f"{P} Alevi'dir.", [K, E("OZEL_DIN", "Alevi'dir")])
    b.add(f"{P} Müslüman.", [K, E("OZEL_DIN", "Müslüman")])
    b.add(f"{P} ateist.", [K, E("OZEL_DIN", "ateist")])
    b.add(f"{P}, Kürt kökenli.", [K, E("OZEL_ETNIK", "Kürt kökenli")])
    b.add(f"{P} Arap kökenli.", [K, E("OZEL_ETNIK", "Arap kökenli")])
    b.add(f"{P} CHP üyesi.", [K, E("OZEL_SIYASI", "CHP üyesi")])
    b.add(f"{P} parti üyesi.", [K, E("OZEL_SIYASI", "parti üyesi")])
    b.add(f"{P} başörtülü.", [K, E("OZEL_KIYAFET", "başörtülü")])
    b.add(f"{P} sendika üyesi.", [K, E("OZEL_UYELIK", "sendika üyesi")])
    b.add(f"{P} dernek üyesi.", [K, E("OZEL_UYELIK", "dernek üyesi")])
    b.add(f"{P} laik.", [K, E("OZEL_FELSEFI", "laik")])
    b.add("CHP kurultayı toplandı.", [])
    b.add("Kanser araştırmalarına bütçe ayrıldı.", [])
    b.add("Diyabet nedir?", [])
    b.add("Lazım olan belgeler.", [])
    b.add("Rumeli yakasında kira arttı.", [])
    b.add("Transfer işlemi tamamlandı.", [])
    b.add("Geyik muhabbeti uzadı.", [])
    b.add("Roman okudum, beğendim.", [])
    b.add(f"{P} Suriyeli.", [K], not_expect=["OZEL_ETNIK"])
    b.add("Parmak izi teknolojisi yaygınlaştı.", [])
    b.add(f"{P} diyabet hastasıdır.", [K, E("OZEL_SAGLIK", "diyabet hastasıdır")],
          masked="Müşterimiz <KISI_1> <OZEL_SAGLIK_1>.")
    b.add(f"{P} CHP üyesi.", [K, E("OZEL_SIYASI", "CHP üyesi")], masked="Müşterimiz <KISI_1> CHP üyesi.")
    b.add(f"{P} CHP üyesi.", [K, E("OZEL_SIYASI", "CHP üyesi")], masked="Müşterimiz <KISI_1> <OZEL_SIYASI_1>.",
          config={"profile": "strict"})
    b.add(f"TCKN {TCKN[0]} olan hasta HIV pozitif.", [E("TCKN", TCKN[0]), E("OZEL_SAGLIK", "HIV pozitif")])
    b.add("Hasta kemoterapi alıyor.", [E("OZEL_SAGLIK", "kemoterapi")])
    b.add("Çalışanımız ameliyat oldu.", [E("OZEL_SAGLIK", "ameliyat oldu")])
    b.add("Tutuklu sayısı arttı.", [])
    b.add("Sağlık Bakanlığı kampanya başlattı.", [])
    b.add("Benim kan grubum 0 Rh-.", [E("OZEL_SAGLIK", "kan grubum 0 Rh-")])
    b.add("Kan grubu uyumu hakkında genel bilgi.", [])
    b.add(f"{P} epilepsi hastası, ilaç kullanıyor.", [K, E("OZEL_SAGLIK", "epilepsi hastası"), E("OZEL_SAGLIK", "ilaç kullanıyor")])
    b.add("Sen gey misin diye sordu.", [E("OZEL_CINSEL", "gey")], tags=["borderline"])
    return b.cases


# ================================================================ detect/coklu_varlik (20)
def coklu() -> list[dict[str, Any]]:
    b = Book("COKLU")
    t, i = TCKN[2], IBAN[1]
    b.add(f"Ben Ayşe Demir, TCKN {t}, tel 0532 234 56 78, e-posta ayse@ornek.com, IBAN {i}.",
          [E("KISI", "Ayşe Demir"), E("TCKN", t), E("TELEFON", "0532 234 56 78"), E("EPOSTA", "ayse@ornek.com"), E("IBAN", i)],
          masked="Ben <KISI_1>, TCKN <TCKN_1>, tel <TELEFON_1>, e-posta <EPOSTA_1>, IBAN <IBAN_1>.")
    b.add(f"TCKN:{t},Tel:05322345678", [E("TCKN", t), E("TELEFON", "05322345678")])
    b.add(f"Ad Soyad: Mehmet Öztürk\nTCKN: {TCKN[3]}\nTelefon: 0212 345 67 89\nAdres: Gül Sok. No:3 Kadıköy",
          [E("KISI", "Mehmet Öztürk"), E("TCKN", TCKN[3]), E("TELEFON", "0212 345 67 89"), E("ADRES", "Gül Sok. No:3 Kadıköy")])
    b.add(f'{{"ad":"Zeynep Arslan","tckn":"{TCKN[4]}","iban":"{IBAN[2]}"}}',
          [E("KISI", "Zeynep Arslan"), E("TCKN", TCKN[4]), E("IBAN", IBAN[2])])
    b.add(f"| Ad | TCKN |\n| Emre Koç | {TCKN[5]} |", [E("KISI", "Emre Koç"), E("TCKN", TCKN[5])])
    b.add("Kullanıcı <KISI_1> yazdı; gerçek ad Ahmet Yılmaz.", [E("KISI", "Ahmet Yılmaz")],
          masked="Kullanıcı <KISI_1> yazdı; gerçek ad <KISI_2>.")
    b.add(f"Kart {CARDS['visa']} sahibi Ali Rıza Yıldız, CVV 123.",
          [E("KART", CARDS["visa"]), E("KISI", "Ali Rıza Yıldız"), E("KART_CVV", "123")])
    b.add(f"VKN {VKN[0]} firması, yetkili Hasan Doğan, tel +90 216 444 55 66.",
          [E("VKN", VKN[0]), E("KISI", "Hasan Doğan"), E("TELEFON", "+90 216 444 55 66")])
    b.add(f"Pasaport U12345678 ve TCKN {TCKN[6]}", [E("PASAPORT", "U12345678"), E("TCKN", TCKN[6])])
    b.add(f"Müşteri Elif Aydın ({TCKN[7]}) IBAN {g4(IBAN[3])}",
          [E("KISI", "Elif Aydın"), E("TCKN", TCKN[7]), E("IBAN", g4(IBAN[3]))])
    b.add(f"Doğum tarihi 12.03.1985, doğum yeri İzmir, TCKN {TCKN[8]}",
          [E("DOGUM_TARIHI", "12.03.1985"), E("DOGUM_YERI", "İzmir"), E("TCKN", TCKN[8])])
    b.add("Plaka 34 ABC 123, sahibi Burak Kurt, e-posta burak@ornek.com",
          [E("PLAKA", "34 ABC 123"), E("KISI", "Burak Kurt"), E("EPOSTA", "burak@ornek.com")])
    b.add(f"THYAO 312,50 TL; müşteri Merve Polat TCKN {TCKN[9]}", [E("KISI", "Merve Polat"), E("TCKN", TCKN[9])])
    b.add("1. Ahmet Yılmaz\n2. Ayşe Demir\n3. Mehmet Öztürk",
          [E("KISI", "Ahmet Yılmaz"), E("KISI", "Ayşe Demir"), E("KISI", "Mehmet Öztürk")],
          masked="1. <KISI_1>\n2. <KISI_2>\n3. <KISI_3>")
    b.add(f"IBAN {IBAN[4]} ve kart {g4(CARDS['mc'])}", [E("IBAN", IBAN[4]), E("KART", g4(CARDS["mc"]))])
    b.add("E-posta: ayse@ornek.com, Tel: 0532 234 56 78", [E("EPOSTA", "ayse@ornek.com"), E("TELEFON", "0532 234 56 78")])
    b.add(f"Şifre: Gizli2026 ve TCKN {TCKN[10]}", [E("SIFRE", "Gizli2026"), E("TCKN", TCKN[10])])
    b.add(f"Hesap No: 1234567, IBAN {IBAN[5]}", [E("HESAP_NO", "1234567"), E("IBAN", IBAN[5])])
    b.add("IP 192.168.1.15 kullanıcı Fatma Şahin", [E("IP", "192.168.1.15"), E("KISI", "Fatma Şahin")])
    b.add(f"TCKN {TCKN[11]} TCKN {TCKN[11]}", [E("TCKN", TCKN[11]), E("TCKN", TCKN[11])], masked="TCKN <TCKN_1> TCKN <TCKN_1>")
    return b.cases


# ================================================================ detect/unicode_kenar (20)
def unicode_kenar() -> list[dict[str, Any]]:
    b = Book("UNICODE")
    b.add("Dün Ayşe Demir aradı.", [E("KISI", "Ayşe Demir")])
    b.add("TCKN 1729​1716060 sıfır genişlikli boşluk içeriyor.", [], tags=["v1_limit"])
    b.add("Dün Ahmet Yılmaz‏ aradı.", [E("KISI", "Ahmet Yılmaz")])
    b.add("Ahmet Yılmaz😊 mesaj attı.", [E("KISI", "Ahmet Yılmaz")])
    b.add(f"Satır1\r\nTCKN\t{TCKN[0]}\r\n", [E("TCKN", TCKN[0])])
    b.add("", [])
    b.add("   ", [])
    b.add("1" * 5000, [])
    b.add("ＴＣＫＮ １７２９１７１６０６０ tam genişlik", [E("TCKN", "１７２９１７１６０６０")])  # tam genişlik → ASCII kopyada tespit
    b.add("İSTANBUL ŞUBESİ", [])
    b.add("&lt;b&gt;Ahmet Yılmaz&lt;/b&gt;", [E("KISI", "Ahmet Yılmaz")])
    b.add(f"Kimlik: {TCKN[1]} kayıtlı.", [E("TCKN", TCKN[1])])
    b.add("Dün Ayşe Demir aradı.", [E("KISI", "Ayşe Demir")])
    b.add("İLKNUR ÖZTÜRK başvurdu.", [E("KISI", "İLKNUR ÖZTÜRK")])
    b.add("ırmak kenarında", [])
    b.add("Iğdır'dan geldi.", [])
    b.add(f"«{TCKN[2]}»", [E("TCKN", TCKN[2])])
    b.add(f"TCKN:{TCKN[3]}—kayıt", [E("TCKN", TCKN[3])])
    b.add("<" * 200 + "KISI_1", [])
    b.add("Ünal Şükrü Çağlar geldi.", [E("KISI", "Ünal Şükrü Çağlar")], tags=["borderline"])
    return b.cases


# ================================================================ revert (40)
def revert_cases() -> list[dict[str, Any]]:
    cs: list[dict[str, Any]] = []

    def add(llm: str, expect: str, mp: dict[str, str] | None = None, ents: dict[str, str] | None = None, **kw: Any) -> None:
        c: dict[str, Any] = {"id": f"REVERT-{len(cs) + 1:03d}", "map": mp if mp is not None else {"<KISI_1>": "Ayşe", "<TCKN_1>": "17291716060"},
                             "llm_output": llm, "expect": expect}
        if ents:
            c["entities"] = ents
        c.update(kw)
        cs.append(c)

    for v in ["<KISI_1>", "<KISI_1 >", "< KISI_1>", "[KISI_1]", "{KISI_1}", "<<KISI_1>>", "<kisi_1>", "<KİŞİ_1>",
              "<KISI 1>", "<KISI-1>", "**<KISI_1>**", "&lt;KISI_1&gt;", "[[KISI_1]]", "{{KISI_1}}"]:
        exp = "Merhaba " + ("**Ayşe**" if v.startswith("**") else "Ayşe") + "."
        add(f"Merhaba {v}.", exp)
    add("Sayın KISI_1, hoş geldiniz.", "Sayın Ayşe, hoş geldiniz.")
    add("KISI 1 kişidir.", "KISI 1 kişidir.")
    add("<KISI_1>'in dosyası", "Ayşe'nin dosyası")
    add("<KISI_1>’e ilettim", "Ayşe’ye ilettim")
    add("<KISI_1>'den aldım", "Ayşe'den aldım")
    add("<KISI_1>'yla görüştüm", "Ahmet'le görüştüm", mp={"<KISI_1>": "Ahmet"})
    add("<KISI_1>'a sor", "Mehmet'e sor", mp={"<KISI_1>": "Mehmet"})
    add("<KISI_1>'de kaldım", "Kadıköy'de kaldım", mp={"<KISI_1>": "Kadıköy"})
    add("<KISI_1>'da kaldı", "Zeynep'te kaldı", mp={"<KISI_1>": "Zeynep"})
    add("<TCKN_1>'in sahibi", "17291716060'ın sahibi", ents={"<TCKN_1>": "TCKN"})
    add("Bilinmeyen <KISI_9> var.", "Bilinmeyen <KISI_9> var.")
    add("Bilinmeyen <KISI_9> var.", "Bilinmeyen  var.", config={"unresolved_placeholder": "strip"})
    add("Boş harita <KISI_1>.", "Boş harita <KISI_1>.", mp={})
    add("<KISI_1> <KISI_1> <KISI_1>", "Ayşe Ayşe Ayşe")
    add('{"ad": "<KISI_1>"}', '{"ad": "Ayşe"}')
    add("KART: <KART_1>", "KART: **** **** **** 1111", mp={"<KART_1>": "**** **** **** 1111"}, ents={"<KART_1>": "KART"})
    add("Yarım kalan <KIS", "Yarım kalan ", final=True)
    add("Yarım kalan <KIS", "Yarım kalan <KIS", final=True, config={"truncated_placeholder": "keep"})
    add("Merhaba __KISI_1__.", "Merhaba Ayşe.", mp={"__KISI_1__": "Ayşe"}, config={"placeholder_format": "__{label}_{n}__"})
    add("Merhaba PII_KISI_1.", "Merhaba Ayşe.", mp={"PII_KISI_1": "Ayşe"}, config={"placeholder_format": "PII_{label}_{n}"})
    add("Merhaba [KISI_1].", "Merhaba Ayşe.", mp={"[KISI_1]": "Ayşe"}, config={"placeholder_format": "[{label}_{n}]"})
    add("<KISI_1> ve <KISI_2>", "Kisi_2 ve Mehmet", mp={"<KISI_1>": "Kisi_2", "<KISI_2>": "Mehmet"})
    add("AKISI_1 bitişik", "AKISI_1 bitişik")
    add("<KISI_1>'İN", "AYŞE'NİN", mp={"<KISI_1>": "AYŞE"})
    add("<KISI_12> ve <KISI_1>", "Can ve Ayşe", mp={"<KISI_1>": "Ayşe", "<KISI_12>": "Can"})
    add("Ek yok <KISI_1>.", "Ek yok Ayşe.", config={"suffix_repair": False})
    return cs


# ================================================================ streaming (20)
def streaming_cases() -> list[dict[str, Any]]:
    mp = {"<KISI_1>": "Ayşe Demir", "<TCKN_1>": "17291716060", "<KISI_2>": "Ahmet"}
    outs = [
        "Merhaba <KISI_1>, TCKN'niz <TCKN_1>.",
        "<KISI_1>'e iletildi.",
        "Placeholder yok, düz metin.",
        "a < b ve c > d karşılaştırması uzun bir metin içinde yer alıyor.",
        "<KISI_1><KISI_2>",
        "<KISI_2>'in ve <KISI_1>'in dosyaları",
        "Sonda <KISI_1>",
        "**<KISI_1>** kalın",
        "<<KISI_1>> çift",
        "Sayın KISI_1 hoş geldiniz",
        "<KISI_9> bilinmiyor",
        "Türkçe çok uzun metin " * 5 + "<KISI_1>",
        "<",
        "Kimlik <TCKN_1>'dir.",
        "İki satır\n<KISI_2>\nson",
        "{\"ad\": \"<KISI_1>\"}",
        "<KISI_1 > boşluklu",
        "&lt;KISI_1&gt; html",
        "<KİŞİ_1> türkçe",
        "Ki tap ki kisi kim",
    ]
    return [{"id": f"STREAM-{k + 1:03d}", "map": mp, "full_output": o} for k, o in enumerate(outs)]


def main() -> None:
    det = {
        "tckn": tckn(), "vkn": vkn(), "iban": iban(), "kart": kart(), "telefon": telefon(), "eposta": eposta(), "ip": ip(),
        "plaka": plaka(), "kimlik_belgeleri": kimlik(), "dogum": dogum(), "finans_kimlikleri": finans(), "adres": adres(),
        "kisi": kisi(), "ozel_nitelikli": ozel(), "coklu_varlik": coklu(), "unicode_kenar": unicode_kenar(),
    }
    total = 0
    for name, cases in det.items():
        dump(FIX / "detect" / f"{name}.yaml", cases, f"detect/{name} — {len(cases)} senaryo")
        total += len(cases)
    rv = revert_cases()
    dump(FIX / "revert" / "revert.yaml", rv, f"revert — {len(rv)} senaryo")
    st = streaming_cases()
    dump(FIX / "streaming" / "streaming.yaml", st, f"streaming — {len(st)} senaryo (her biri 5 bölme stratejisiyle)")
    print(f"detect={total} revert={len(rv)} streaming={len(st)}")


if __name__ == "__main__":
    main()
