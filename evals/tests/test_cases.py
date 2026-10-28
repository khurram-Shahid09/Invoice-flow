"""The dataset is right by construction: counts, arithmetic, answer keys and expectations."""

from collections import Counter
from decimal import Decimal

import pytest

from invoicegen.cases import STRAIGHT_THROUGH_LIMIT, build
from invoicegen.layouts import LAYOUTS
from invoicegen.model import Case
from invoicegen.seed import load, pk_iban


@pytest.fixture(scope="module")
def cases() -> list[Case]:
    return build()


def test_dataset_size_matches_docs_13(cases) -> None:
    assert Counter(c.kind for c in cases) == {
        "clean": 60,
        "scan": 10,
        "photo": 10,
        "bad": 12,
        "demo": 5,
    }
    assert len({c.case_id for c in cases}) == len(cases)
    assert len({c.filename for c in cases}) == len(cases)


def test_all_ten_layouts_are_used(cases) -> None:
    assert {c.invoice.layout for c in cases} == set(LAYOUTS)


def test_same_seed_same_dataset() -> None:
    first, second = build(7), build(7)
    assert [c.truth() for c in first] == [c.truth() for c in second]
    assert [c.truth() for c in build(8)] != [c.truth() for c in first]


def test_answer_key_arithmetic_adds_up(cases) -> None:
    for case in cases:
        truth = case.truth()
        lines = sum(Decimal(line["line_total"]) for line in truth["lines"])
        assert Decimal(truth["subtotal"]) == lines, case.case_id
        computed = (
            Decimal(truth["subtotal"])
            + Decimal(truth["tax_total"])
            + Decimal(truth["shipping"] or 0)
        )
        if case.case_id == "bad-07":
            assert Decimal(truth["total"]) == computed + 10000  # the deliberate error
        else:
            assert Decimal(truth["total"]) == computed, case.case_id


def test_fields_a_layout_does_not_print_are_null_in_the_key(cases) -> None:
    for case in cases:
        truth, layout = case.truth(), LAYOUTS[case.invoice.layout]
        if "vendor_email" in layout.hidden:
            assert truth["vendor_email"] is None
        if "product_code" in layout.hidden:
            assert all(line["product_code"] is None for line in truth["lines"])
        if not layout.prints_po:
            assert truth["po_number"] is None
        if not layout.prints_due_date:
            assert truth["due_date"] is None


def test_po_invoices_use_seed_prices_and_vendors(cases) -> None:
    seed = load()
    by_number = {po.number: po for po in seed.purchase_orders.values()}
    for case in cases:
        po_number = case.invoice.po_number
        if case.kind != "clean" or po_number is None:
            continue
        po = by_number[po_number]
        assert case.invoice.vendor == po.vendor.party
        prices = {line.product.code: line.price for line in po.lines}
        for line in case.invoice.lines:
            assert line.unit_price == prices[line.product_code]


def test_expected_routes(cases) -> None:
    for case in cases:
        if case.kind in ("clean", "scan", "photo") and case.expected.route == "straight_through":
            assert case.invoice.total <= STRAIGHT_THROUGH_LIMIT, case.case_id
    routes = Counter(c.expected.route for c in cases if c.kind == "clean")
    assert routes["straight_through"] >= 10 and routes["review"] >= 4


def test_no_bad_invoice_may_go_straight_through(cases) -> None:
    bad = [c for c in cases if c.kind == "bad"]
    assert all(c.expected.route != "straight_through" and c.expected.codes for c in bad)
    assert {code for c in bad for code in c.expected.codes} == {
        "DUP_EXACT",
        "DUP_FUZZY",
        "BANK_CHANGED",
        "PO_PRICE_VARIANCE",
        "GRN_QTY_OVER_RECEIVED",
        "MATH_TOTAL",
        "VENDOR_UNKNOWN",
        "DATE_FUTURE",
        "HIDDEN_TEXT",
        "CURRENCY_MISMATCH",
    }


def test_degraded_copies_share_their_answer_key(cases) -> None:
    clean = {c.case_id: c for c in cases if c.kind == "clean"}
    for case in (c for c in cases if c.kind in ("scan", "photo")):
        twin = next(
            c for c in clean.values() if c.invoice.invoice_number == case.invoice.invoice_number
        )
        assert {**case.truth()} == {**twin.truth()}
        assert case.manifest_entry()["has_text_layer"] is False


def test_demo_files_match_the_demo_script(cases) -> None:
    demo = {c.case_id: c for c in cases if c.kind == "demo"}
    assert demo["demo-1"].filename == "INV-2291.pdf" and demo["demo-1"].invoice.pages == 2
    assert demo["demo-2"].file_format == "jpg"
    assert demo["demo-4"].expected.after == ["demo-1"]
    assert demo["demo-5"].invoice.hidden_text


def test_ibans_are_valid() -> None:
    for vendor in load().vendors.values():
        iban = vendor.party.bank_account or ""
        rearranged = iban[4:] + iban[:4]
        assert int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1
    assert pk_iban("JSBL", "0000921004377182").startswith("PK")
