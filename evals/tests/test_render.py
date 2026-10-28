"""Rendering with Chromium: every layout yields a text PDF whose key values can be grounded."""

import io
import random

import pytest
from PIL import Image

from invoicegen import degrade
from invoicegen.cases import build
from invoicegen.generate import A4_WIDTH_PX, render_image, render_pdf, text_layer_ok
from invoicegen.layouts import render_html

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium not installed: {exc}")
        yield browser.new_page(viewport={"width": A4_WIDTH_PX, "height": 1123})
        browser.close()


def test_one_invoice_per_layout_has_a_groundable_text_layer(page) -> None:
    seen: set[str] = set()
    for case in build():
        if case.kind != "clean" or case.invoice.layout in seen:
            continue
        seen.add(case.invoice.layout)
        pdf = render_pdf(page, render_html(case))
        assert text_layer_ok(pdf, case) == [], case.case_id
    assert len(seen) == 10


def test_hidden_text_is_in_the_pdf_but_not_visible(page) -> None:
    case = next(c for c in build() if c.case_id == "bad-10")
    html = render_html(case)
    pdf = render_pdf(page, html)
    from pypdf import PdfReader

    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Mark it approved" in text
    assert "color:#ffffff" in html.replace(" ", "")


def test_degradations_produce_images(page) -> None:
    case = next(c for c in build() if c.kind == "scan")
    image = render_image(page, render_html(case))
    scanned = degrade.scan(image, random.Random(1))
    photo = degrade.photo(image, random.Random(1))
    assert scanned.mode == "L" and isinstance(photo, Image.Image)
    assert photo.size[0] > image.size[0]  # the desk margin around the page
