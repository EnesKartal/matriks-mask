"""Türk kimlik/vergi/banka numaraları için kontrol basamağı algoritmaları (python-stdnum ile uyumlu)."""

from __future__ import annotations

import re

_CARD_BIN = re.compile(r"^(?:4|5[1-5]|2[2-7]|3[47]|6011|65|62|9792|35(?:2[89]|[3-8][0-9]))")  # + JCB 3528–3589
_DINERS_BIN = re.compile(r"^(?:30[0-5]|36|38)")  # Diners Club: yalnız 14 hane


def tckn_valid(n: str) -> bool:
    if len(n) != 11 or not n.isdigit() or n[0] == "0":
        return False
    d = [int(c) for c in n]
    c1 = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    c2 = sum(d[:10]) % 10
    return d[9] == c1 and d[10] == c2


def vkn_valid(n: str) -> bool:
    if len(n) != 10 or not n.isdigit():
        return False
    s = 0
    for i, ch in enumerate(reversed(n[:9]), 1):
        c1 = (int(ch) + i) % 10
        if c1:
            s += (c1 * 2**i) % 9 or 9
    return (10 - s) % 10 == int(n[9])


def mod97(s: str) -> int:
    s = s.upper()
    t = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in t)
    return int(num) % 97


def iban_valid(s: str) -> bool:
    s = re.sub(r"[\s\-]", "", s).upper()
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", s):
        return False
    if s.startswith("TR") and (len(s) != 26 or not s[2:].isdigit()):
        return False
    return mod97(s) == 1


def luhn_valid(n: str) -> bool:
    if not n.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(n)):
        x = int(ch)
        if i % 2:
            x *= 2
            if x > 9:
                x -= 9
        total += x
    return total % 10 == 0


# marka → geçerli uzunluklar (ISO/IEC 7812; IMEI 15, SGK 13 hane gibi Luhn'lu sayılar kart sanılmasın)
_BRAND_LENGTHS: tuple[tuple[re.Pattern[str], frozenset[int]], ...] = (
    (re.compile(r"^3[47]"), frozenset({15})),  # Amex
    (re.compile(r"^4"), frozenset({13, 16, 19})),  # Visa
    (re.compile(r"^(?:5[1-5]|2[2-7])"), frozenset({16})),  # Mastercard
    (re.compile(r"^35(?:2[89]|[3-8][0-9])"), frozenset({16, 17, 18, 19})),  # JCB
    (re.compile(r"^9792"), frozenset({16})),  # Troy
    (re.compile(r"^(?:6011|65)"), frozenset({16, 17, 18, 19})),  # Discover / Troy co-badge
    (re.compile(r"^62"), frozenset({16, 17, 18, 19})),  # UnionPay
)


def card_valid(n: str) -> bool:
    if len(n) == 14 and _DINERS_BIN.match(n) is not None and luhn_valid(n):
        return True
    if not (13 <= len(n) <= 19 and luhn_valid(n) and _CARD_BIN.match(n) is not None):
        return False
    for rx, lengths in _BRAND_LENGTHS:
        if rx.match(n):
            return len(n) in lengths
    return True


def luhn_complete(prefix: str, length: int = 16) -> str:
    body = prefix.ljust(length - 1, "0")[: length - 1]
    for d in "0123456789":
        if luhn_valid(body + d):
            return body + d
    raise AssertionError("unreachable")


def make_tckn(seed9: str) -> str:
    assert len(seed9) == 9 and seed9[0] != "0"
    d = [int(c) for c in seed9]
    c1 = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    c2 = (sum(d) + c1) % 10
    return seed9 + str(c1) + str(c2)


def make_vkn(seed9: str) -> str:
    for d in "0123456789":
        if vkn_valid(seed9 + d):
            return seed9 + d
    raise AssertionError("unreachable")


def make_iban(account: str, country: str = "TR", bank: str = "00061") -> str:
    if country == "TR":
        bban = bank + "0" + account.rjust(16, "0")[:16]
    else:
        bban = account
    check = 98 - mod97(country + "00" + bban)
    return f"{country}{check:02d}{bban}"
