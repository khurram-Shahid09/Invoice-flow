"""Normalisers shared by ERP sync and the check rules (docs/06, docs/07)."""

import re

# Free-mail domains say nothing about who the sender is (docs/07 "Vendor matching").
FREE_MAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "icloud.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
    }
)


def normalize_invoice_number(value: str) -> str:
    """Compare invoice numbers the way people mean them: ``INV-0042`` == ``inv 42`` == ``INV/042``.

    Upper-cases, drops separators (space - / . _ #) and leading zeros of every number run.
    """
    compact = re.sub(r"[\s\-/._#]", "", value).upper()
    return re.sub(r"\d+", lambda m: str(int(m.group())), compact)


def normalize_tax_id(value: str) -> str:
    return re.sub(r"[\s\-./]", "", value).upper()


def business_domain(email: str) -> str:
    """The sender's company domain, or "" for free-mail addresses and junk."""
    _, _, domain = email.strip().lower().rpartition("@")
    return "" if not domain or "." not in domain or domain in FREE_MAIL_DOMAINS else domain
