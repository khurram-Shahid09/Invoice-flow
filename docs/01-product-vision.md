# 01 · Product Vision

## One line

**An AI accounts-payable agent that reads every supplier invoice, checks it like a careful accountant, and only asks a person when something is actually wrong.**

## The problem

Accounts payable (AP) is the most common back-office process in any company that buys things. For each invoice someone must:

1. Find it (email attachments, WhatsApp photos, paper scans).
2. Type it into the ERP: vendor, invoice number, dates, currency, line items, tax, total.
3. Check it: is the math right, did we order this (purchase order), did we receive it (goods receipt), did we already pay it?
4. Get approval from the right manager, and chase them.
5. Post it, then pay it on time.

Typical numbers for a mid-size team (industry ranges, to be validated with pilots):
- 4–8 minutes of handling per invoice, much more for exceptions.
- 1–3% of invoices are duplicates or have errors that cause overpayment if missed.
- Fraud via fake "updated bank details" is one of the most common business payment scams.

## Who it's for

| Persona | Pain | What they get |
|---|---|---|
| **AP clerk** (primary user) | Types the same fields all day; blamed for typos | A queue of pre-filled invoices; only fixes what's flagged |
| **Approver** (department manager) | Approval emails without context | One-click approve or reject, with the reason, the PO and the page |
| **Finance controller** (buyer) | Duplicate payments, audit findings, month-end crunch | Rules they control, a full audit trail, straight-through-processing metrics |
| **Admin / IT** | Another tool to secure | Roles, segregation of duties, encrypted bank details, ERP connector with least privilege |

**First market:** small and mid-size companies (20–500 staff) on Odoo or similar ERPs, and accounting firms that process invoices for many clients. Pakistan, the Gulf and remote clients worldwide.

## Positioning

| Alternative | Weakness InvoiceFlow addresses |
|---|---|
| Manual entry | Slow, error-prone, no consistent checks |
| OCR with templates (classic capture tools) | Needs a template per layout; breaks on new vendors; no matching logic |
| Big AP suites | Expensive, long implementations, built for large enterprises |
| "Chat with your PDF" AI tools | Can hallucinate values and let the model "decide"; no controls, no audit |

**InvoiceFlow's stance:** *AI reads, rules decide, people approve exceptions.* That's what finance teams and auditors can accept.

## Principles

1. **Grounded or rejected.** An extracted value must be traceable to the document. If not, the field is flagged, never guessed.
2. **Deterministic decisions.** Matching, approval routing and posting follow explicit, versioned rules. AI output is input to rules, never a decision.
3. **Explain everything.** Every exception has a plain-English reason and a link to the evidence.
4. **Humans for exceptions only.** The goal is straight-through processing for clean invoices, not "a person checks everything again".
5. **Idempotent and auditable.** Nothing is posted twice; every change is logged with who, what and when.
6. **Cheap per invoice.** One AI call per document in the normal case, with a target under $0.01 per invoice on Gemini Flash.

## Success metrics

| Metric | MVP target (eval set) | Pilot target |
|---|---|---|
| Field-level extraction accuracy (header fields) | ≥ 97% | ≥ 95% on real invoices |
| Line-item accuracy | ≥ 92% | ≥ 90% |
| Straight-through processing (clean invoices that need no touch) | ≥ 70% of clean set | ≥ 50% |
| **False approvals** (a seeded bad invoice auto-approved) | **0** | **0** |
| Duplicate detection recall | 100% of seeded duplicates | ≥ 98% |
| Median processing time (arrival → ready) | < 30 s | < 60 s |
| AI cost per invoice | < $0.01 | < $0.02 |

## What it is not (MVP)

- Not a payment system: it doesn't move money. It hands approved bills to the ERP, where payment already happens.
- Not a general document AI: invoices and credit notes only (receipts and LCs later, see [15](15-roadmap-build-plan.md)).
- Not a replacement for the ERP: Odoo stays the system of record.

## Relationship to WatchOnce

WatchOnce automates **websites without APIs**. InvoiceFlow automates **documents and decisions**. When a vendor or customer system only has a web portal (for example uploading bills to a supplier portal), InvoiceFlow can hand off to a WatchOnce workflow (v0.2, see [09](09-erp-integration.md)). Together they cover most of what an AI automation engineer is hired to build.
