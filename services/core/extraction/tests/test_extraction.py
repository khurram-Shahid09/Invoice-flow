from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from extraction import providers
from extraction.grounding import ground
from extraction.normalize import amount, currency, parse_date
from extraction.schema import Extraction

WORDS = [
    {"t": "Invoice", "b": [0.1, 0.1, 0.2, 0.12]},
    {"t": "No.", "b": [0.21, 0.1, 0.25, 0.12]},
    {"t": "INV-2291", "b": [0.3, 0.1, 0.4, 0.12]},
    {"t": "Total", "b": [0.6, 0.5, 0.7, 0.52]},
    {"t": "Rs.", "b": [0.72, 0.5, 0.75, 0.52]},
    {"t": "148,562.00", "b": [0.76, 0.5, 0.9, 0.52]},
]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Rs. 1,450.00", "1450.00"),
        ("1,450.00/-", "1450.00"),
        ("PKR 72,500", "72500"),
        ("(500.00)", "-500.00"),
        ("n/a", None),
    ],
)
def test_amounts(text, value) -> None:
    assert amount(text) == (Decimal(value) if value else None)


def test_dates_follow_the_org_order_when_ambiguous() -> None:
    assert parse_date("03/04/2026") == date(2026, 4, 3)
    assert parse_date("03/04/2026", "MDY") == date(2026, 3, 4)
    assert parse_date("26-Oct-2026") == parse_date("October 26, 2026") == date(2026, 10, 26)
    assert parse_date("2026-10-26") == date(2026, 10, 26)
    assert currency("Rs.", "PKR") == "PKR" and currency(None, "PKR") == "PKR"


def test_grounding_finds_values_with_their_box() -> None:
    found = ground("148,562.00", 1, "Rs. 148,562.00", [WORDS])
    assert found["grounding"] == "exact" and found["box"] == [0.72, 0.5, 0.9, 0.52]
    assert ground("INV-2291", None, None, [WORDS])["box"] == [0.3, 0.1, 0.4, 0.12]


def test_values_not_on_the_page_are_rejected() -> None:
    hallucinated = ground("P00042", 1, "PO: P00042", [WORDS])
    assert hallucinated["grounding"] == "none" and hallucinated["value"] is None
    assert hallucinated["rejected"] == "P00042"


def test_scans_keep_values_as_model_only() -> None:
    assert ground("INV-2291", 1, "INV-2291", [[]])["grounding"] == "model_only"
    assert ground(None, None, None, [WORDS])["grounding"] == "absent"


def _response(text: str) -> SimpleNamespace:
    usage = SimpleNamespace(prompt_token_count=1200, candidates_token_count=300)
    return SimpleNamespace(parsed=None, text=text, usage_metadata=usage)


def test_gemini_rotates_to_the_next_key_on_quota(monkeypatch, settings) -> None:
    from google.genai import errors

    settings.GEMINI_API_KEYS = ["key-one", "key-two"]
    settings.GEMINI_MODELS = ["gemini-test"]
    providers._exhausted.clear()
    empty = {"value": None, "page": None, "quote": None}
    answer: dict[str, Any] = {
        name: empty
        for name in Extraction.model_fields
        if name not in ("document_type", "lines", "notes_for_reviewer")
    }
    answer.update(document_type="invoice", lines=[])
    used = []

    class Models:
        def __init__(self, key: str) -> None:
            self.key = key

        def generate_content(self, **kwargs):
            used.append(self.key)
            if self.key == "key-one":
                raise errors.ClientError(429, {"error": {"message": "quota exceeded per day"}})
            return _response(Extraction.model_validate(answer).model_dump_json())

    monkeypatch.setattr(
        "google.genai.Client", lambda api_key: SimpleNamespace(models=Models(api_key))
    )
    result = providers._gemini([b"png"], ["text"])
    assert used == ["key-one", "key-two"] and result.meta["key"] == 2
    assert (result.input_tokens, result.output_tokens) == (1200, 300)
    providers._gemini([b"png"], ["text"])
    assert used[-1] == "key-two"  # the exhausted key is skipped for an hour
    providers._exhausted.clear()


def test_identical_pages_reuse_the_cached_answer(settings, tmp_path, monkeypatch) -> None:
    settings.LLM_CACHE_DIR = str(tmp_path)
    calls = []
    empty = {"value": None, "page": None, "quote": None}
    data: dict[str, Any] = {
        n: empty
        for n in Extraction.model_fields
        if n not in ("document_type", "lines", "notes_for_reviewer")
    }
    data.update(document_type="invoice", lines=[])

    def fake_call():
        calls.append(1)
        return providers.Result(Extraction.model_validate(data), "gemini", "m", 10, 5)

    first = providers._cached([b"page"], fake_call)
    again = providers._cached([b"page"], fake_call)
    assert len(calls) == 1 and again.model == first.model == "m" and again.input_tokens == 10
    providers._cached([b"other page"], fake_call)
    assert len(calls) == 2
