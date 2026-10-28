"""Run the eval set through the real pipeline (docs/13-testing-and-evals.md).

    uv run python manage.py run_evals                          # offline answer keys: checks E3 on all 97
    uv run python manage.py run_evals --provider gemini --cases clean-01,scan-03,bad-10

Each case runs in its own savepoint on a fresh copy of the seed ERP (fake adapter), then rolls
back, so nothing is left behind. Gemini answers are cached in evals/reports/cache by file hash
and model, so a case never costs a free-tier request twice. Writes evals/reports/<date>-<provider>.md.
"""

import hashlib
import json
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Organization
from erp.demo import apply_vendor_settings
from erp.models import ErpConnection
from erp.sync import sync_connection
from extraction import providers, service
from extraction.schema import HEADER_FIELDS, Extraction
from invoices.documents import store
from invoices.models import Invoice
from invoices.tasks import process_invoice

DATA = Path(settings.REPO_ROOT) / "evals" / "data" / "generated"
REPORTS = Path(settings.REPO_ROOT) / "evals" / "reports"
CACHE = REPORTS / "cache"
COMPARED = [f for f in HEADER_FIELDS if f not in ("vendor_email",)]


class Rollback(Exception):
    pass


def _same(field: str, got: str | None, want: Any) -> bool:
    if want is None:
        return got is None
    if got is None:
        return False
    try:
        return Decimal(str(got)) == Decimal(str(want))
    except (InvalidOperation, ValueError):
        return str(got).strip().lower() == str(want).strip().lower()


def _cached_extract(provider: str):
    real = providers.extract

    def extract(images, texts, filename):
        if provider != "gemini":
            return real(images, texts, filename)
        key = hashlib.sha256(
            b"".join(images) + "|".join(settings.GEMINI_MODELS).encode()
        ).hexdigest()[:24]
        path = CACHE / f"{key}.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return providers.Result(Extraction.model_validate(data["extraction"]), **data["meta"])
        result = real(images, texts, filename)
        CACHE.mkdir(parents=True, exist_ok=True)
        meta = {
            k: getattr(result, k)
            for k in ("provider", "model", "input_tokens", "output_tokens", "ms", "trusted", "meta")
        }
        path.write_text(
            json.dumps({"extraction": result.extraction.model_dump(), "meta": meta}),
            encoding="utf-8",
        )
        return result

    return extract


class Command(BaseCommand):
    help = "Score extraction accuracy and decisions on the generated eval invoices."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--provider", choices=["fake", "gemini"], default="fake")
        parser.add_argument("--cases", default="", help="Comma-separated case ids (default: all)")

    def handle(self, *args, provider: str, cases: str, **options) -> None:
        manifest = DATA / "manifest.json"
        if not manifest.is_file():
            raise CommandError(
                "Generate the dataset first: cd evals && uv run python -m invoicegen.generate"
            )
        all_cases = {c["id"]: c for c in json.loads(manifest.read_text(encoding="utf-8"))["cases"]}
        wanted = [c.strip() for c in cases.split(",") if c.strip()] or list(all_cases)
        settings.LLM_PROVIDER = provider
        service.extract = _cached_extract(provider)
        settings.MEDIA_ROOT = REPORTS / "media-tmp"

        rows = []
        for n, case_id in enumerate(wanted):
            if provider == "gemini" and n:
                time.sleep(5)  # stay under the free tier's per-minute limit
            case = all_cases[case_id]
            try:
                with transaction.atomic():
                    rows.append(self._run_case(case, all_cases))
                    raise Rollback
            except Rollback:
                pass
            except providers.ExtractionError as exc:
                self.stderr.write(f"{case_id}: {exc}")
                break
            self.stdout.write(
                f"{case_id:9s} {rows[-1]['route']:16s} expected {case['expected']['route']:16s} {'ok' if rows[-1]['route_ok'] else 'MISS'} {rows[-1]['reason'][:90]}"
            )
        if rows:
            self._report(rows, provider)

    def _run_case(self, case: dict, all_cases: dict) -> dict:
        org = Organization.objects.create(name="Indus Retail (Pvt) Ltd (eval)")
        sync_connection(ErpConnection.objects.create(org=org, kind="fake"))
        apply_vendor_settings(org)
        invoice = None
        for cid in [*case["expected"].get("after", []), case["id"]]:
            source = all_cases[cid]
            stored = store(
                org, None, source["file"], (DATA / "files" / source["file"]).read_bytes()
            )
            process_invoice(stored.invoice.id)
            invoice = Invoice.objects.get(pk=stored.invoice.id)
        assert invoice is not None
        truth = json.loads((DATA / "truth" / f"{case['id']}.json").read_text(encoding="utf-8"))
        fields_ok = {
            f: _same(f, invoice.fields.get(f, {}).get("value"), truth.get(f)) for f in COMPARED
        }
        line_ok = []
        for got, want in zip(invoice.lines, truth["lines"], strict=False):
            for f in ("quantity", "unit_price", "line_total"):
                line_ok.append(_same(f, (got.get(f) or {}).get("value"), want.get(f)))
        line_ok += [False] * abs(len(invoice.lines) - len(truth["lines"])) * 3
        route = invoice.decision.get("route", invoice.status)
        codes = {c["code"] for c in invoice.checks}
        expected = case["expected"]
        return {
            "id": case["id"],
            "kind": case["kind"],
            "route": route,
            "route_ok": route == expected["route"],
            "reason": invoice.status_reason,
            "codes_ok": set(expected["codes"]) <= codes,
            "false_approval": case["kind"] == "bad" and route == "straight_through",
            "fields_ok": sum(fields_ok.values()),
            "fields_total": len(fields_ok),
            "field_misses": [f for f, ok in fields_ok.items() if not ok],
            "lines_ok": sum(line_ok),
            "lines_total": len(line_ok),
            "tokens": invoice.extraction.get("input_tokens", 0)
            + invoice.extraction.get("output_tokens", 0),
            "ms": invoice.extraction.get("ms", 0),
        }

    def _report(self, rows: list[dict], provider: str) -> None:
        def pct(a: int, b: int) -> str:
            return f"{100 * a / b:.1f}%" if b else "–"

        n = len(rows)
        fields = (sum(r["fields_ok"] for r in rows), sum(r["fields_total"] for r in rows))
        lines = (sum(r["lines_ok"] for r in rows), sum(r["lines_total"] for r in rows))
        summary = [
            ("Invoices", str(n)),
            ("Header fields correct (E1)", pct(*fields)),
            ("Line amounts correct (E1)", pct(*lines)),
            ("Correct route (E3)", pct(sum(r["route_ok"] for r in rows), n)),
            ("Expected check codes raised (E3)", pct(sum(r["codes_ok"] for r in rows), n)),
            (
                "**False approvals on the safety set**",
                f"**{sum(r['false_approval'] for r in rows)}**",
            ),
        ]
        if provider == "gemini":
            summary.append(
                (
                    "Average tokens / time per invoice",
                    f"{sum(r['tokens'] for r in rows) // n} / {sum(r['ms'] for r in rows) / n / 1000:.1f} s",
                )
            )
        lines_md = [
            f"# Eval report · {provider} · {date.today().isoformat()}",
            "",
            "Generated by `manage.py run_evals` (docs/13-testing-and-evals.md).",
            "",
            "| Metric | Result |",
            "|---|---|",
            *[f"| {k} | {v} |" for k, v in summary],
            "",
            "| Case | Kind | Route | OK | Fields | Missed fields |",
            "|---|---|---|---|---|---|",
            *[
                f"| {r['id']} | {r['kind']} | {r['route']} | {'✅' if r['route_ok'] and r['codes_ok'] else '❌'} | {r['fields_ok']}/{r['fields_total']} | {', '.join(r['field_misses'])} |"
                for r in rows
            ],
        ]
        REPORTS.mkdir(parents=True, exist_ok=True)
        path = REPORTS / f"{date.today().isoformat()}-{provider}.md"
        path.write_text("\n".join(lines_md) + "\n", encoding="utf-8")
        for k, v in summary:
            self.stdout.write(f"{k.strip('*')}: {v.strip('*')}")
        self.stdout.write(f"-> {path}")
