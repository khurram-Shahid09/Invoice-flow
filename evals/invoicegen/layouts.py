"""Ten vendor invoice layouts (docs/13-testing-and-evals.md "Synthetic invoice generator").

Each layout differs the way real suppliers do: label words ("Invoice No.", "Bill #", "Ref"),
date and amount formats, tax per line or per document, which fields are printed at all, and
one with an Urdu heading. ``shows`` lists fields the layout does NOT print, so the answer key
expects ``null`` for them.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .model import Case

TEMPLATES = Path(__file__).with_name("layouts")


@dataclass(frozen=True)
class Layout:
    name: str
    date_style: str  # see fmt_date
    money_style: str  # see fmt_money
    tax_per_line: bool = False
    hidden: frozenset[str] = field(default_factory=frozenset)  # fields this layout never prints
    prints_po: bool = True
    prints_due_date: bool = True
    prints_terms: bool = True

    @property
    def template(self) -> str:
        return f"{self.name}.html.j2"

    def shows(self) -> dict[str, bool]:
        return {name: False for name in self.hidden}


LAYOUTS: dict[str, Layout] = {
    layout.name: layout
    for layout in [
        Layout("classic", "dmy_slash", "plain"),
        Layout("band", "dmy_mon", "rs", hidden=frozenset({"product_code"})),
        Layout("grid", "iso", "plain", tax_per_line=True, hidden=frozenset({"vendor_email"})),
        Layout(
            "taxinvoice",
            "dmy_dot",
            "dash",
            hidden=frozenset({"vendor_email", "unit"}),
            prints_due_date=False,
        ),
        Layout("twocol", "long", "pkr", hidden=frozenset({"product_code"})),
        Layout("compact", "dmy_slash", "plain", hidden=frozenset({"bank_name", "unit"})),
        Layout("service", "dmy_mon", "pkr", hidden=frozenset({"product_code"})),
        Layout("tech", "iso", "plain"),
        Layout(
            "utility",
            "dmy_mon",
            "rs",
            hidden=frozenset({"product_code", "unit"}),
            prints_po=False,
            prints_terms=False,
        ),
        Layout(
            "cleaning",
            "dmy_slash",
            "plain",
            hidden=frozenset({"product_code", "vendor_address"}),
            prints_po=False,
            prints_terms=False,
        ),
    ]
}

VENDOR_LAYOUT = {
    "V01": "classic",
    "V02": "band",
    "V03": "grid",
    "V04": "taxinvoice",
    "V05": "twocol",
    "V06": "compact",
    "V07": "service",
    "V08": "tech",
    "N01": "utility",
    "N02": "utility",
    "N03": "cleaning",
}


def fmt_date(value: date, style: str) -> str:
    return {
        "dmy_slash": f"{value:%d/%m/%Y}",
        "dmy_mon": f"{value:%d-%b-%Y}",
        "dmy_dot": f"{value:%d.%m.%Y}",
        "iso": value.isoformat(),
        "long": f"{value:%B} {value.day}, {value.year}",
    }[style]


def fmt_money(value: Decimal | None, style: str, currency: str = "PKR") -> str:
    if value is None:
        return ""
    plain = f"{value:,.2f}"
    if currency != "PKR":
        return f"{currency} {plain}"
    return {"plain": plain, "rs": f"Rs. {plain}", "dash": f"{plain}/-", "pkr": f"PKR {plain}"}[
        style
    ]


def fmt_qty(value: Decimal) -> str:
    return f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"


def fmt_pct(value: Decimal | None) -> str:
    return "" if value is None else f"{value.normalize():f}%"


_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["j2", "html"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_html(case: Case) -> str:
    layout = LAYOUTS[case.invoice.layout]
    inv = case.invoice
    return _env.get_template(layout.template).render(
        inv=inv,
        shows=lambda name: name not in layout.hidden,
        date=lambda d: fmt_date(d, layout.date_style),
        money=lambda v: fmt_money(v, layout.money_style, inv.currency),
        qty=fmt_qty,
        pct=fmt_pct,
    )
