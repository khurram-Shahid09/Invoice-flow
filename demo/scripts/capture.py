"""Record the demo story in the real dashboard and Odoo (docs/16-demo-script.md).

Produces demo/out/raw/{clerk,controller,odoo}.webm with marks.json (seconds into each clip),
and full-resolution stills in demo/out/shots/. Uses whatever AI the worker runs (Gemini for
the real demo: about 5 free-tier requests).

Before running: services up (API, worker, dashboard, Odoo), then reset:
    cd services/core
    uv run python ../../infra/odoo/seed.py --reset-bills
    uv run python manage.py seed_demo --reset
    cd ../../evals && uv run python ../demo/scripts/capture.py
"""

import json
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "demo" / "out" / "raw"
SHOTS = ROOT / "demo" / "out" / "shots"
FILES = ROOT / "evals" / "data" / "generated" / "files"
DEMO = [
    "INV-2291.pdf",
    "photo-gulf-packaging.jpg",
    "netlink-internet-oct.pdf",
    "INV2291-resent.pdf",
    "mehran-steel-new-bank.pdf",
]
BASE = "http://localhost:3100"
SIZE = {"width": 1440, "height": 900}
CURSOR = (Path(__file__).with_name("cursor.js")).read_text(encoding="utf-8")


def env(name: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].split("#")[0].strip()
    raise SystemExit(f"{name} missing in .env")


class Clip:
    """One recorded page with time marks."""

    def __init__(self, browser, name: str, scale: int = 1) -> None:
        self.context = browser.new_context(
            viewport=SIZE,
            device_scale_factor=scale,
            record_video_dir=str(RAW / name),
            record_video_size=SIZE,
        )
        self.context.add_init_script(CURSOR)
        self.page = self.context.new_page()
        self.name, self.t0, self.marks = name, time.monotonic(), {}
        self.page.mouse.move(720, 450)

    def mark(self, key: str) -> None:
        self.marks[key] = round(time.monotonic() - self.t0, 2)

    def pause(self, seconds: float) -> None:
        self.page.wait_for_timeout(int(seconds * 1000))

    def point(self, selector: str, *, click: bool = False, steps: int = 28) -> None:
        box = self.page.locator(selector).first.bounding_box()
        assert box, selector
        self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=steps)
        self.pause(0.25)
        if click:
            self.page.mouse.down()
            self.page.mouse.up()

    def shot(self, name: str) -> None:
        self.page.screenshot(path=str(SHOTS / f"{name}.png"))

    def close(self) -> Path:
        video = self.page.video
        self.context.close()
        target = RAW / f"{self.name}.webm"
        Path(video.path()).replace(target)  # type: ignore[union-attr]
        return target


def sign_in(clip: Clip, who: str) -> None:
    page = clip.page
    page.goto(f"{BASE}/login")
    clip.pause(0.8)
    clip.point("input[name=email]", click=True)
    page.keyboard.type(f"{who}@indus-retail.test", delay=35)
    clip.point("input[name=password]", click=True)
    page.keyboard.type(env("DEMO_PASSWORD"), delay=25)
    clip.point("button:has-text('Sign in')", click=True)
    page.wait_for_url("**/inbox", timeout=90_000)
    page.wait_for_load_state("networkidle")


def wait_images(page: Page) -> None:
    page.wait_for_function(
        "() => [...document.images].length > 0 && [...document.images].every(i => i.complete && i.naturalWidth > 0)",
        timeout=30_000,
    )


def open_invoice(clip: Clip, row_text: str) -> None:
    clip.page.goto(f"{BASE}/inbox")
    clip.page.wait_for_selector("tbody tr")
    clip.pause(0.6)
    clip.point(f"tbody tr:has-text('{row_text}') a", click=True)
    clip.page.wait_for_selector("text=What the AI read")
    wait_images(clip.page)
    clip.pause(0.8)


def hover_field(clip: Clip, label: str, hold: float = 1.6) -> None:
    clip.point(f"dt:text-is('{label}')", steps=22)
    clip.pause(hold)


def clerk_part(browser) -> dict:
    clip = Clip(browser, "clerk", scale=2)
    page = clip.page
    clip.mark("start")
    sign_in(clip, "clerk")
    clip.mark("signed_in")
    clip.pause(1.5)
    clip.shot("01-empty-inbox")

    clip.mark("upload")
    page.set_input_files("input[name=files]", [str(FILES / n) for n in DEMO])
    clip.pause(1.0)
    clip.point("button:has-text('Upload invoices')", click=True)
    page.wait_for_selector("text=5 files received", timeout=60_000)
    clip.mark("uploaded")

    busy = "text=/Reading…|Received|Posting…/"
    clip.pause(3)
    clip.shot("02-reading")
    clip.mark("processing")
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        if page.locator("tbody tr").count() >= 5 and page.locator(busy).count() == 0:
            break
        clip.pause(1.0)
    else:
        raise SystemExit("invoices still processing after 10 minutes")
    clip.mark("processed")
    page.mouse.move(1100, 700, steps=20)
    clip.pause(4)
    clip.shot("03-inbox-sorted")
    clip.mark("inbox_read")

    open_invoice(clip, "INV-2291")
    clip.mark("review")
    for label, hold in [("Vendor", 1.4), ("Invoice number", 1.4), ("PO number", 1.4), ("Total", 2.2)]:
        hover_field(clip, label, hold)
    clip.shot("04-review-highlight")
    clip.mark("review_end")

    open_invoice(clip, "INV 2291")
    clip.mark("duplicate")
    hover_field(clip, "Invoice number", 2.5)
    clip.shot("05-duplicate")
    clip.mark("duplicate_end")

    open_invoice(clip, "Mehran")
    clip.mark("bank")
    clip.point("text=BANK_CHANGED", steps=22)
    clip.pause(2.0)
    hover_field(clip, "Bank account", 2.5)
    clip.shot("06-bank-change")
    clip.mark("bank_end")
    clip.pause(0.5)
    path = clip.close()
    return {"clip": path.stem, **clip.marks}


def controller_part(browser) -> tuple[dict, str]:
    clip = Clip(browser, "controller", scale=2)
    page = clip.page
    clip.mark("start")
    sign_in(clip, "controller")
    clip.mark("signed_in")
    clip.point("a:has-text('Approvals')", click=True)
    page.wait_for_selector("tbody tr:has-text('INV-2291')")
    clip.pause(1.5)
    clip.mark("approvals")
    clip.point("tbody tr:has-text('INV-2291') a", click=True)
    page.wait_for_selector("text=Approve and post")
    wait_images(page)
    clip.pause(1.5)
    clip.shot("07-awaiting-approval")
    clip.mark("approve")
    clip.point("button:has-text('Approve and post')", click=True)
    page.wait_for_selector("text=open in Odoo", timeout=120_000)
    clip.pause(1.0)
    clip.point("a:has-text('open in Odoo')", steps=20)
    clip.pause(2.5)
    clip.shot("08-posted")
    clip.mark("posted")
    url = page.locator("a:has-text('open in Odoo')").get_attribute("href") or ""
    path = clip.close()
    return {"clip": path.stem, **clip.marks}, url


def odoo_part(browser, bill_url: str) -> dict:
    clip = Clip(browser, "odoo", scale=2)
    page = clip.page
    page.goto("http://localhost:8069/web/login")
    page.fill("input[name=login]", "admin")
    page.fill("input[name=password]", env("ODOO_ADMIN_PASSWORD"))
    page.click("button[type=submit]")
    page.wait_for_selector(".o_main_navbar", timeout=60_000)  # Odoo keeps a long-poll open: no networkidle
    clip.mark("start")
    page.goto(bill_url)
    page.wait_for_selector(".o_form_view", timeout=60_000)
    clip.pause(3)
    clip.mark("bill")
    for target in ["text=Al-Noor Traders", "text=A4 Paper", "text=148,562"]:
        try:
            clip.point(target, steps=24)
            clip.pause(1.6)
        except AssertionError:
            pass
    clip.shot("09-odoo-bill")
    clip.mark("bill_end")
    path = clip.close()
    return {"clip": path.stem, **clip.marks}


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        marks: dict = {}

        def save() -> None:  # after every part, so a later failure keeps the earlier marks
            (RAW / "marks.json").write_text(json.dumps(marks, indent=2), encoding="utf-8")

        marks["clerk"] = clerk_part(browser)
        save()
        marks["controller"], bill_url = controller_part(browser)
        marks["bill_url"] = bill_url
        save()
        marks["odoo"] = odoo_part(browser, bill_url)
        save()
        browser.close()
    print(json.dumps(marks, indent=2))


if __name__ == "__main__":
    main()
