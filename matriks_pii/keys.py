"""Çoklu worker/replika kurulumu için sır üretici.

    python -m matriks_pii.keys            # .env / docker-compose biçimi
    python -m matriks_pii.keys --k8s      # kubectl create secret komutu

Üretilen değerler bir kez oluşturulup TÜM LiteLLM örneklerine aynı verilmelidir (secret manager / k8s Secret).
Değerler yalnız standart çıktıya yazılır; hiçbir yere kaydedilmez.
"""

from __future__ import annotations

import argparse
import base64
import secrets


def generate() -> dict[str, str]:
    return {
        "MATRIKS_PII_SESSION_SECRET": secrets.token_urlsafe(48),  # oturum jetonu HMAC sırrı (64 karakter)
        "MATRIKS_PII_STORE_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),  # Redis AES-256-GCM anahtarı
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--k8s", action="store_true", help="kubectl create secret generic komutu yazdır")
    a = ap.parse_args()
    keys = generate()
    if a.k8s:
        args = " ".join(f"--from-literal={k}='{v}'" for k, v in keys.items())
        print(f"kubectl create secret generic matriks-pii {args}")
    else:
        for k, v in keys.items():
            print(f"{k}={v}")


if __name__ == "__main__":
    main()
