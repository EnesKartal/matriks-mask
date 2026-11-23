"""SIFRE yanlış pozitifleri (test ortamında görülen vakalar), SIFRE varsayılan MASK ve embedding'de BLOCK yerine maskeleme."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from matriks_pii.config import TurkishPIIConfig
from matriks_pii.engine import PIIEngine
from matriks_pii.guardrail import TurkishPIIGuardrail

ENGINE = PIIEngine(TurkishPIIConfig.build({}))

# Gerçek sır değil: düz sözcük, yer tutucu, değişken/ortam değişkeni adı, teknik terim.
NOT_SECRET = [
    "the keychain password is never printed",
    "password is never printed",
    "the password is hashed",
    "password: hashed",
    "password",
    "parola alani",
    "kullanici sifre alani",
    "the password field is hashed",
    "keychain is used",
    "parola sudur: abc",
    "Password: ***",
    "password=***",
    '"Password": "***"',
    "<Password>***</Password>",
    "Username ve Password alanlari zorunludur",
    "Password: string",
    "password: required",
    "password = self.password",
    'password=os.getenv("DB_PASS")',
    "password: ${DB_PASSWORD}",
    "password={password}",
    "password=%s",
    "password: {{ secrets.db }}",
    "Password (554) is sent in Logon",
    "password is sent in tag 554",
    "password: process.env.DB_PASSWORD",
    "PASSWORD=DB_PASSWORD_PROD",
    "password=user_pw",
    "password: <redacted>",
    "password: xxxx",
    "password: ...",
    "Şifre: yok",
    "şifre: boş",
    "şifre: gizli",
    "hash: sha256, password: sha256",
    "Şifreniz en az 8 karakter olmalıdır.",
]

# Gerçek sır: rakam veya sembol içeren değer.
SECRET = [
    ("Şifre: Gizli123!", "Gizli123!"),
    ("password=Abc12345", "Abc12345"),
    ("Parolam: kedi2026", "kedi2026"),
    ("PIN kodu 5321 SIM kartta.", "5321"),
    ("the password is hunter2", "hunter2"),
    ("password: MyPass123", "MyPass123"),
    ("pwd=P@ss-w0rd", "P@ss-w0rd"),
    ("şifrem 4512 unutma", "4512"),
    ("sifresi 1234", "1234"),
    ('{"password": "Qw3rty!9"}', "Qw3rty!9"),
]


@pytest.mark.parametrize("text", NOT_SECRET)
def test_not_secret(text: str) -> None:
    assert [s for s in ENGINE.detected(text) if s.entity == "SIFRE"] == []


@pytest.mark.parametrize(("text", "value"), SECRET)
def test_secret(text: str, value: str) -> None:
    assert [text[s.start:s.end] for s in ENGINE.detected(text) if s.entity == "SIFRE"] == [value]


def _g() -> TurkishPIIGuardrail:
    return TurkishPIIGuardrail(guardrail_name="matriks-pii", default_on=True, event_hook=["pre_call", "post_call"])


async def test_embedding_block_entity_masked_not_rejected() -> None:
    d = {"model": "e", "input": ["Şifre: Gizli123! ve TCKN 17291716060"], "metadata": {}}
    g = TurkishPIIGuardrail(guardrail_name="matriks-pii", default_on=True, event_hook=["pre_call", "post_call"],
                            entities={"SIFRE": "BLOCK"})
    out = await g.async_pre_call_hook(user_api_key_dict=None, cache=None, data=d, call_type="aembedding")
    assert out["input"] == ["Şifre: <SIFRE_1> ve TCKN <TCKN_1>"]


async def test_chat_block_entity_still_rejected() -> None:
    d = {"model": "m", "messages": [{"role": "user", "content": "Şifre: Gizli123!"}], "metadata": {}}
    g = TurkishPIIGuardrail(guardrail_name="matriks-pii", default_on=True, event_hook=["pre_call", "post_call"],
                            entities={"SIFRE": "BLOCK"})
    with pytest.raises(HTTPException) as ei:
        await g.async_pre_call_hook(user_api_key_dict=None, cache=None, data=d, call_type="acompletion")
    assert ei.value.status_code == 400 and ei.value.detail["entity"] == "SIFRE"
    assert d["messages"][0]["content"] == "Şifre: <SIFRE_1>"


async def test_chat_password_masked_by_default_and_shown_as_stars() -> None:
    g = _g()
    d = {"model": "m", "messages": [{"role": "user", "content": "Şifre: Gizli123! ile giriş yapamıyorum"}], "metadata": {}}
    out = await g.async_pre_call_hook(user_api_key_dict=None, cache=None, data=d, call_type="acompletion")
    assert out["messages"][0]["content"] == "Şifre: <SIFRE_1> ile giriş yapamıyorum"
    sid = g._session_id(out)
    session = await g.store.get(sid)
    assert session.map == {"<SIFRE_1>": "****"}  # geri yükleme yok, uzunluk da sızmaz


def test_strict_profile_still_blocks_password() -> None:
    assert TurkishPIIConfig.build({"profile": "strict"}).action("SIFRE") == "BLOCK"
