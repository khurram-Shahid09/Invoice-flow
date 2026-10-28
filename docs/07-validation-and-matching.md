# 07 · Validation & Matching

All checks are **deterministic Python rules**. Each rule returns zero or more:

```python
@dataclass
class CheckResult:
    code: str            # "MATH_TOTAL", "PO_PRICE_VARIANCE", "BANK_CHANGED"...
    severity: Literal["info", "warning", "blocking"]
    message: str         # plain English, shown to people
    fields: list[str]    # which fields to highlight
    data: dict           # numbers behind the message (expected, actual, tolerance)
```

Rules are registered in an ordered list, versioned (`rules_version` saved on every check run), and configurable per org (tolerances, thresholds, on/off).

## 1. Document validation

| Code | Rule | Severity |
|---|---|---|
| `REQ_FIELDS` | vendor, invoice number, invoice date, currency and total are present | blocking |
| `MATH_LINE` | each line: qty × unit price × (1 − discount) ≈ line total (±0.01) | blocking |
| `MATH_SUBTOTAL` | Σ line totals ≈ subtotal (±0.05) | blocking |
| `MATH_TOTAL` | subtotal − discount + tax + shipping ≈ total (±0.05) | blocking |
| `TAX_RATE` | tax rate is one of the org's allowed rates (e.g. 0, 5, 16, 18%) | warning |
| `DATE_FUTURE` | invoice date ≤ today + 1 day | blocking |
| `DATE_OLD` | invoice date within the last 365 days (configurable) | warning |
| `DUE_BEFORE_INVOICE` | due date ≥ invoice date | warning |
| `CURRENCY_MISMATCH` | currency = vendor's currency, or the PO's currency | blocking |
| `LOW_TRUST_FIELD` | any required field with low trust (see [06](06-ai-extraction.md)) | blocking |
| `CREDIT_NOTE` | document type is a credit note → separate flow (link to the original invoice) | info |

## 2. Vendor matching

Order of attempts against the vendor master (synced from the ERP):

1. Tax id exact match.
2. Bank account exact match (decrypted comparison inside the worker).
3. Sender email domain → vendor (learned from past invoices; free-mail domains excluded).
4. Name fuzzy match (`rapidfuzz.token_set_ratio` ≥ 92 and a unique best match).

| Code | Result | Severity |
|---|---|---|
| `VENDOR_MATCHED` | matched, with the method used | info |
| `VENDOR_AMBIGUOUS` | 2+ candidates; clerk picks | blocking |
| `VENDOR_UNKNOWN` | no match; "create vendor in ERP" is offered to admins only | blocking |

## 3. Purchase order matching

**Find the PO:**
1. Use the extracted PO number when it's an open PO of this vendor.
2. Otherwise, look for an open PO of this vendor whose remaining amount covers the invoice and whose lines match ≥ 80% by value.
3. Otherwise, no PO.

**Match lines** (invoice line → PO line):
1. Product code exact.
2. Description similarity ≥ 85 (rapidfuzz) with the same unit.
3. Unit price within tolerance as a tie-breaker.

**2-way match (invoice ↔ PO)** and **3-way match (↔ goods receipt)**:

| Code | Rule | Default tolerance | Severity |
|---|---|---|---|
| `PO_NOT_FOUND` | vendor requires PO (setting) and none found | – | blocking |
| `PO_CLOSED` | PO cancelled or fully billed | – | blocking |
| `PO_LINE_UNMATCHED` | invoice line with no PO line | – | blocking |
| `PO_PRICE_VARIANCE` | unit price differs from PO | ±2% or ±1.00, whichever is larger | blocking above, info within |
| `PO_QTY_OVER_ORDERED` | invoiced qty (incl. earlier bills) > ordered qty | 0 | blocking |
| `GRN_QTY_OVER_RECEIVED` | invoiced qty (incl. earlier bills) > received qty | 0 | blocking (3-way only) |
| `GRN_PENDING` | goods not received yet | – | blocking, auto re-checked on ERP sync |
| `PO_TOTAL_VARIANCE` | invoice total vs matched PO lines total | ±1% | warning |

When `GRN_PENDING` is the only blocker, the invoice waits in `needs_review` with "Waiting for goods receipt". The 15-minute ERP sync re-runs checks, and it moves on automatically when the receipt arrives.

## 4. Non-PO invoices (utilities, services, subscriptions)

- Vendors on the org's **non-PO list** skip PO matching.
- **Expense account suggestion:**
  - from the vendor's last 5 bills (the most common account), deterministically
  - if there's no history: a small AI suggestion from the chart of accounts, with an explanation, **always requiring approval** (`ACCOUNT_SUGGESTED`, warning)

## 5. Duplicate detection

| Code | Rule | Severity |
|---|---|---|
| `DUP_EXACT` | same vendor + same normalised invoice number (in InvoiceFlow or in ERP bills) | blocking |
| `DUP_FILE` | same file hash already processed | blocking |
| `DUP_FUZZY` | same vendor + total within 0.5% + invoice date within 7 days | blocking (reviewer can mark "not a duplicate", with a reason) |
| `DUP_CROSS_VENDOR` | same invoice number + same total under a different vendor | warning |

Each duplicate result links to the earlier invoice and its status (posted, paid).

## 6. Fraud and risk signals

| Code | Rule | Severity |
|---|---|---|
| `BANK_CHANGED` | invoice bank account ≠ vendor master account | **blocking, always**, even under thresholds; requires an admin to verify by phone (checkbox + note) |
| `BANK_INVALID` | IBAN checksum fails | blocking |
| `NEW_VENDOR` | vendor created < 30 days ago | warning |
| `AMOUNT_OUTLIER` | total > 3 × vendor's median of the last 12 bills | warning |
| `SENDER_MISMATCH` | sender domain differs from the vendor's known domains | warning |
| `HIDDEN_TEXT` | hidden or tiny text found in the PDF text layer | warning |
| `ROUND_AMOUNT` | total is a round number ≥ 10,000 with no lines | info |

## 7. Routing decision

```
if any blocking result:                        → needs_review (clerk fixes or escalates)
elif straight_through_allowed(invoice):        → approved (actor = "system", rule list stored)
else:                                          → awaiting_approval (approver from matrix)
```

`straight_through_allowed`:
- all required fields high or medium trust (medium allowed only when the math passes)
- vendor matched by tax id, bank or domain (not by name alone)
- PO 3-way matched, or vendor on the non-PO list with a historical account
- no warnings from section 6
- total ≤ org's straight-through limit (default 50,000 PKR / 250 USD)

The decision record stores the inputs, the rule results and the rules version, so any decision can be replayed and explained later.
