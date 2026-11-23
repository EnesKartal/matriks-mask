"""Determinizm: aynı girdi → bayt-eşit maske; yeni tur eklemek önceki maskeleri değiştirmez."""

from __future__ import annotations

import copy

from test_hooks import G, pre

CONV = [
    {"role": "system", "content": "Sen Matriks asistanısın."},
    {"role": "user", "content": "Ben Ayşe Demir, TCKN 17291716060."},
    {"role": "assistant", "content": "Merhaba Ayşe Demir."},
    {"role": "user", "content": "IBAN TR330006100519786457841326, tel 0532 234 56 78."},
]


async def test_same_conversation_byte_equal() -> None:
    g = G()
    a = await pre(g, {"model": "m", "metadata": {}, "messages": copy.deepcopy(CONV)})
    b = await pre(g, {"model": "m", "metadata": {}, "messages": copy.deepcopy(CONV)})
    assert a["messages"] == b["messages"]


async def test_new_turn_does_not_change_previous() -> None:
    g = G()
    a = await pre(g, {"model": "m", "metadata": {}, "messages": copy.deepcopy(CONV)})
    longer = copy.deepcopy(CONV) + [{"role": "user", "content": "Ahmet Yılmaz da eklensin, TCKN 44771278268."}]
    b = await pre(g, {"model": "m", "metadata": {}, "messages": longer})
    assert b["messages"][: len(CONV)] == a["messages"]


async def test_hmac_across_replicas() -> None:
    g1, g2 = G(placeholder_id="hmac", hash_secret="s"), G(placeholder_id="hmac", hash_secret="s")
    a = await pre(g1, {"model": "m", "metadata": {}, "messages": copy.deepcopy(CONV)})
    b = await pre(g2, {"model": "m", "metadata": {}, "messages": copy.deepcopy(CONV)})
    assert a["messages"] == b["messages"]


async def test_hmac_differs_with_secret() -> None:
    a = await pre(G(placeholder_id="hmac", hash_secret="s1"), {"model": "m", "metadata": {}, "messages": copy.deepcopy(CONV)})
    b = await pre(G(placeholder_id="hmac", hash_secret="s2"), {"model": "m", "metadata": {}, "messages": copy.deepcopy(CONV)})
    assert a["messages"] != b["messages"]


async def test_order_is_traversal_order() -> None:
    a = await pre(G(), {"model": "m", "metadata": {}, "messages": copy.deepcopy(CONV)})
    assert "<KISI_1>" in a["messages"][1]["content"] and "<IBAN_1>" in a["messages"][3]["content"]
