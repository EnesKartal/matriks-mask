from __future__ import annotations

import importlib


def test_import_and_version() -> None:
    m = importlib.import_module("matriks_pii")
    assert m.__version__
    assert m.TurkishPIIGuardrail.__name__ == "TurkishPIIGuardrail"


def test_data_packaged() -> None:
    from matriks_pii import data

    assert len(data.first_names()) > 5000 and len(data.last_names()) > 20000
    assert len(data.geo().provinces) == 81
    assert len(data.special_terms()) > 200


def test_litellm_loads_by_module_path() -> None:
    from litellm.proxy.types_utils.utils import get_instance_fn

    cls = get_instance_fn("matriks_pii.guardrail.TurkishPIIGuardrail")
    g = cls(guardrail_name="matriks-pii", event_hook="pre_call", default_on=True, profile="strict")
    assert g.cfg.profile == "strict"
