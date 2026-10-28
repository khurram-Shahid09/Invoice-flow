"""Cover / thumbnail (1920x1080) from the captured stills: demo/out/cover.png.

    cd evals && uv run python ../demo/scripts/make_cover.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "demo" / "out" / "shots"
OUT = ROOT / "demo" / "out" / "cover.png"


def uri(name: str) -> str:
    return (SHOTS / f"{name}.png").as_uri()


HTML = f"""<!doctype html><html><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; margin: 0; }}
  body {{ width: 1920px; height: 1080px; overflow: hidden; font-family: "Segoe UI", sans-serif;
         background: radial-gradient(1200px 800px at 85% 20%, #134e4a 0%, #06201e 55%, #041513 100%); color: #ecfeff; }}
  .left {{ position: absolute; left: 110px; top: 150px; width: 700px; }}
  .tag {{ display: inline-block; padding: 8px 18px; border-radius: 999px; background: rgba(45,212,191,.15);
          color: #5eead4; font-size: 22px; font-weight: 600; letter-spacing: .5px; }}
  h1 {{ font-size: 112px; font-weight: 800; letter-spacing: -2px; margin-top: 26px; }}
  .line {{ font-size: 40px; color: #99f6e4; margin-top: 8px; font-weight: 600; }}
  .sub {{ font-size: 26px; color: #a5c9c5; margin-top: 26px; line-height: 1.45; }}
  .stats {{ display: flex; gap: 18px; margin-top: 46px; }}
  .stat {{ background: rgba(255,255,255,.06); border: 1px solid rgba(94,234,212,.25); border-radius: 18px; padding: 18px 24px; }}
  .stat b {{ display: block; font-size: 44px; color: #fff; }}
  .stat span {{ font-size: 19px; color: #a5c9c5; }}
  .stack {{ margin-top: 46px; font-size: 21px; color: #7fb3ad; }}
  .win {{ position: absolute; border-radius: 16px; overflow: hidden; background: #fff;
          box-shadow: 0 40px 90px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.08); }}
  .bar {{ height: 34px; background: #e5e7eb; display: flex; align-items: center; gap: 8px; padding-left: 14px; }}
  .bar i {{ width: 12px; height: 12px; border-radius: 50%; background: #f87171; display: block; }}
  .bar i:nth-child(2) {{ background: #fbbf24; }} .bar i:nth-child(3) {{ background: #34d399; }}
  .win img {{ display: block; width: 100%; }}
  .badge {{ position: absolute; padding: 12px 20px; border-radius: 14px; font-size: 22px; font-weight: 700;
            box-shadow: 0 16px 40px rgba(0,0,0,.4); }}
</style></head><body>
  <div class="left">
    <span class="tag">AI ACCOUNTS-PAYABLE AGENT</span>
    <h1>InvoiceFlow</h1>
    <div class="line">Invoices in. Approved bills out.</div>
    <div class="sub">Reads supplier invoices with AI, checks them against the purchase order and goods receipt, catches duplicates and fraud, and posts approved bills to Odoo.</div>
    <div class="stats">
      <div class="stat"><b>0</b><span>false approvals</span></div>
      <div class="stat"><b>100%</b><span>correct decisions</span></div>
      <div class="stat"><b>97</b><span>test invoices</span></div>
    </div>
    <div class="stack">Gemini · Django · Celery · PostgreSQL · Next.js · Odoo</div>
  </div>
  <div class="win" style="left:880px; top:120px; width:940px; transform: rotate(-1.5deg)">
    <div class="bar"><i></i><i></i><i></i></div><img src="{uri("03-inbox-sorted")}">
  </div>
  <div class="win" style="left:1000px; top:470px; width:860px; transform: rotate(1.2deg)">
    <div class="bar"><i></i><i></i><i></i></div><img src="{uri("06-bank-change")}">
  </div>
  <div class="badge" style="left:930px; top:420px; background:#fee2e2; color:#b91c1c">⚠ Bank account changed: blocked</div>
  <div class="badge" style="left:1500px; top:80px; background:#dcfce7; color:#15803d">✓ Posted to Odoo</div>
</body></html>"""


def main() -> None:
    page_file = OUT.with_suffix(".html")
    page_file.write_text(HTML, encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(page_file.as_uri())
        page.wait_for_function("() => [...document.images].every(i => i.complete && i.naturalWidth > 0)")
        page.screenshot(path=str(OUT))
        browser.close()
    page_file.unlink()
    print(OUT)


if __name__ == "__main__":
    main()
