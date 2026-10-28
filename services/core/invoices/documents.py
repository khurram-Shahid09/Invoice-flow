"""Turn an upload into a stored document with page images and a text layer (docs/05)."""

import hashlib
import io
from dataclasses import dataclass
from functools import partial

import pdfplumber
import pypdfium2 as pdfium
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageOps

from accounts.models import Organization, User
from common.exceptions import ApiError

from .models import Document, Invoice, Page

MAGIC = {b"%PDF": "application/pdf", b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg"}
RENDER_DPI = 150
LONG_EDGE = 2000
HIDDEN_SIZE_PT = 2.0


def sniff(head: bytes) -> str | None:
    """File type from its first bytes, never from the name (docs/05 "File acceptance")."""
    return next((mime for magic, mime in MAGIC.items() if head.startswith(magic)), None)


@dataclass
class Stored:
    document: Document
    invoice: Invoice
    duplicate_file: bool


def store(org: Organization, user: User | None, name: str, data: bytes) -> Stored:
    mime = sniff(data[:8])
    if mime is None:
        raise ApiError("unsupported_file", f"{name}: only PDF, PNG and JPEG files are accepted.")
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise ApiError("file_too_large", f"{name}: larger than {settings.MAX_UPLOAD_MB} MB.")
    sha = hashlib.sha256(data).hexdigest()
    existing = Document.objects.for_org(org).filter(sha256=sha).first()
    if existing is not None:  # the same file again: link to what we already have
        invoice = existing.invoices.order_by("created_at").first()
        assert invoice is not None
        return Stored(existing, invoice, duplicate_file=True)
    with transaction.atomic():
        document = Document(
            org=org, sha256=sha, filename=name[:255], mime=mime, size=len(data), uploaded_by=user
        )
        document.file.save(name, ContentFile(data), save=False)
        document.save()
        invoice = Invoice.objects.create(org=org, document=document, uploaded_by=user)
    return Stored(document, invoice, duplicate_file=False)


def _save_page(document: Document, number: int, image: Image.Image, words: list[dict]) -> Page:
    image.thumbnail((LONG_EDGE, LONG_EDGE))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "PNG", optimize=True)
    page = Page(document=document, number=number, words=words)
    page.image.save(f"{number}.png", ContentFile(buffer.getvalue()), save=False)
    page.save()
    return page


def _is_white(color: object) -> bool:
    if not isinstance(color, tuple | list) or len(color) not in (1, 3, 4):
        return False
    if len(color) == 4:  # CMYK
        return all(c <= 0.03 for c in color)
    return all(c >= 0.97 for c in color[:3])


def _is_hidden(char: dict, dark_boxes: list[tuple[float, float, float, float]]) -> bool:
    """Tiny text, or white text that isn't sitting on a coloured box (e.g. a header band)."""
    if float(char.get("size") or 99) < HIDDEN_SIZE_PT:
        return True
    if not _is_white(char.get("non_stroking_color")):
        return False
    x, y = (char["x0"] + char["x1"]) / 2, (char["top"] + char["bottom"]) / 2
    return not any(x0 <= x <= x1 and top <= y <= bottom for x0, top, x1, bottom in dark_boxes)


def _keep(obj: dict, boxes: list[tuple[float, float, float, float]]) -> bool:
    return obj.get("object_type") != "char" or not _is_hidden(obj, boxes)


def _dark_boxes(page) -> list[tuple[float, float, float, float]]:
    return [
        (r["x0"], r["top"], r["x1"], r["bottom"])
        for r in page.rects
        if r.get("fill") and not _is_white(r.get("non_stroking_color"))
    ]


def render(document: Document) -> list[Page]:
    """Page images for the viewer and the AI; words with boxes for grounding."""
    document.pages.all().delete()
    data = document.file.open("rb").read()
    if document.mime != "application/pdf":
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        document.page_count, document.has_text_layer = 1, False
        document.save(update_fields=["page_count", "has_text_layer", "updated_at"])
        return [_save_page(document, 1, image, [])]

    pages: list[Page] = []
    hidden: list[str] = []
    pdf = pdfium.PdfDocument(data)
    with pdfplumber.open(io.BytesIO(data)) as plumber:
        for index, (pdfium_page, plumber_page) in enumerate(zip(pdf, plumber.pages, strict=True)):
            if index >= settings.MAX_PAGES:
                break
            image = pdfium_page.render(scale=RENDER_DPI / 72).to_pil()
            width, height = float(plumber_page.width), float(plumber_page.height)
            boxes = _dark_boxes(plumber_page)
            visible = plumber_page.filter(partial(_keep, boxes=boxes))
            hidden_chars = [c["text"] for c in plumber_page.chars if _is_hidden(c, boxes)]
            if hidden_chars:
                hidden.append("".join(hidden_chars))
            words = [
                {
                    "t": w["text"],
                    "b": [
                        round(w["x0"] / width, 4),
                        round(w["top"] / height, 4),
                        round(w["x1"] / width, 4),
                        round(w["bottom"] / height, 4),
                    ],
                }
                for w in visible.extract_words(keep_blank_chars=False, use_text_flow=True)
            ]
            pages.append(_save_page(document, index + 1, image, words))
    document.page_count = len(pages)
    document.has_text_layer = sum(len(p.words) for p in pages) >= 5
    document.hidden_text = " ".join(hidden)[:2000]
    document.save(update_fields=["page_count", "has_text_layer", "hidden_text", "updated_at"])
    return pages
