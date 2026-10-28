"""Printed text -> comparable values (docs/06 "Normalisation")."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

CURRENCY_SYMBOLS = {"RS": "PKR", "RS.": "PKR", "PKR": "PKR", "$": "USD", "USD": "USD", "AED": "AED"}
DATE_FORMATS = {
    "DMY": ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"],
    "MDY": ["%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y", "%m/%d/%y"],
}
UNAMBIGUOUS = ["%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"]


def amount(text: str | None) -> Decimal | None:
    """'Rs. 1,450.00', 'PKR 1,450/-', '(500.00)' -> Decimal."""
    if not text:
        return None
    clean = re.sub(r"(?i)\b(?:rs|pkr|usd|aed)\b\.?|[$\s,]|/-", "", text)
    negative = clean.startswith("(") and clean.endswith(")")
    clean = clean.strip("()%")
    try:
        value = Decimal(clean)
    except InvalidOperation:
        return None
    return -value if negative else value


def parse_date(text: str | None, order: str = "DMY") -> date | None:
    if not text:
        return None
    clean = re.sub(r"\s+", " ", text.strip().rstrip("."))
    for fmt in UNAMBIGUOUS + DATE_FORMATS.get(order, DATE_FORMATS["DMY"]):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue
    return None


def currency(text: str | None, default: str) -> str:
    if not text:
        return default
    return CURRENCY_SYMBOLS.get(text.strip().upper(), text.strip().upper()[:3] or default)


def compact(text: str) -> str:
    """For grounding: lower-case, no spaces or punctuation that layouts vary."""
    return re.sub(r"[\s,.:;/\-()#'\"]", "", text.lower()).replace("rs", "").replace("pkr", "")
