import io

import pytest
from PIL import Image

from accounts.models import Organization
from common.exceptions import ApiError
from invoices.documents import render, sniff, store

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def png(width: int = 1200, height: int = 1600) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, "PNG")
    return buffer.getvalue()


def test_sniff_by_content_not_name() -> None:
    assert sniff(b"%PDF-1.7") == "application/pdf"
    assert sniff(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert sniff(b"PK\x03\x04") is None  # a zip renamed to .pdf


def test_store_dedupes_the_same_file() -> None:
    org = Organization.objects.create(name="Indus")
    first = store(org, None, "photo.png", png())
    again = store(org, None, "copy-of-photo.png", png())
    assert not first.duplicate_file and again.duplicate_file
    assert again.invoice.pk == first.invoice.pk
    other_org = store(Organization.objects.create(name="Other"), None, "photo.png", png())
    assert not other_org.duplicate_file  # dedup is per organisation


def test_rejects_unknown_types_and_huge_files(settings) -> None:
    org = Organization.objects.create(name="Indus")
    with pytest.raises(ApiError, match="only PDF, PNG and JPEG"):
        store(org, None, "invoice.pdf", b"PK\x03\x04 zip")
    settings.MAX_UPLOAD_MB = 0
    with pytest.raises(ApiError, match="larger than"):
        store(org, None, "big.png", png())


def test_render_image_upload() -> None:
    stored = store(Organization.objects.create(name="Indus"), None, "photo.png", png(3000, 4000))
    [page] = render(stored.document)
    assert page.image.width == 1500 and page.image.height == 2000  # long edge capped
    assert page.words == [] and stored.document.has_text_layer is False
