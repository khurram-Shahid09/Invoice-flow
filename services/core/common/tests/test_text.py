import pytest

from common.text import business_domain, normalize_invoice_number, normalize_tax_id


@pytest.mark.parametrize("raw", ["INV-0042", "inv 42", "INV/042", "INV.42", "Inv#0042", " inv_42 "])
def test_invoice_numbers_compare_as_people_mean_them(raw: str) -> None:
    assert normalize_invoice_number(raw) == "INV42"


def test_different_invoice_numbers_stay_different() -> None:
    assert normalize_invoice_number("INV-2291") != normalize_invoice_number("INV-2219")
    assert normalize_invoice_number("2026-09-4471") == "2026094471"


def test_tax_ids() -> None:
    assert normalize_tax_id("3520117-4") == normalize_tax_id("3520 1174") == "35201174"


@pytest.mark.parametrize(
    ("email", "domain"),
    [
        ("Accounts@AlNoor-Traders.test", "alnoor-traders.test"),
        ("someone@gmail.com", ""),
        ("not-an-email", ""),
        ("x@localhost", ""),
    ],
)
def test_business_domain(email: str, domain: str) -> None:
    assert business_domain(email) == domain
