"""Write the eval dataset to disk.

    cd evals
    uv run python -m invoicegen.generate                 # -> evals/data/generated/
    uv run python -m invoicegen.generate --only demo     # just the demo invoices

Output:
    files/<name>.pdf|jpg     what InvoiceFlow receives
    truth/<case id>.json     the correct extraction (docs/06 schema)
    manifest.json            every case: kind, file, layout, vendor, expected route and codes

Each text PDF is checked after rendering: its invoice number and total must be findable in the
PDF's text layer, which is what grounding (docs/06) relies on.
"""

import argparse
import io
import json
import random
import re
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright
from pypdf import PdfReader

from . import degrade
from .cases import build
from .layouts import render_html
from .model import Case

OUT = Path(__file__).resolve().parents[1] / "data" / "generated"
A4_WIDTH_PX = 794  # 210 mm at 96 dpi


def render_pdf(page: Page, html: str) -> bytes:
    page.set_content(html, wait_until="load")
    return page.pdf(format="A4", print_background=True, margin={"top": "0", "bottom": "0"})


def render_image(page: Page, html: str) -> Image.Image:
    page.set_content(html, wait_until="load")
    png = page.screenshot(full_page=True)
    return Image.open(io.BytesIO(png)).convert("RGB")


def text_layer_ok(pdf: bytes, case: Case) -> list[str]:
    text = " ".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
    flat = re.sub(r"\s+", " ", text)
    missing = [
        value
        for value in (case.invoice.invoice_number, f"{case.invoice.total:,.2f}")
        if value not in flat
    ]
    return missing


def write_case(page: Page, case: Case, files: Path) -> None:
    html = render_html(case)
    target = files / case.filename
    rng = random.Random(case.case_id)
    if case.file_format == "pdf":
        pdf = render_pdf(page, html)
        if missing := text_layer_ok(pdf, case):
            raise SystemExit(f"{case.case_id}: text layer lacks {missing}")
        target.write_bytes(pdf)
    elif case.file_format == "scan_pdf":
        degrade.scan(render_image(page, html), rng).save(target, "PDF", resolution=150)
    else:
        degrade.photo(render_image(page, html), rng).save(target, "JPEG", quality=88)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--only", choices=["clean", "scan", "photo", "bad", "demo"])
    args = parser.parse_args(argv)

    cases = build(args.seed)
    selected = [c for c in cases if args.only in (None, c.kind)]
    files, truth = args.out / "files", args.out / "truth"
    files.mkdir(parents=True, exist_ok=True)
    truth.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": A4_WIDTH_PX, "height": 1123}, device_scale_factor=2
        )
        for i, case in enumerate(selected, start=1):
            write_case(page, case, files)
            (truth / f"{case.case_id}.json").write_text(
                json.dumps(case.truth(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(f"[{i:3d}/{len(selected)}] {case.case_id:9s} {case.filename}", flush=True)
        browser.close()

    manifest = {"seed": args.seed, "cases": [c.manifest_entry() for c in cases]}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(selected)} files to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
