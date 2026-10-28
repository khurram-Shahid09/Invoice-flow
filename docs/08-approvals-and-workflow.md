# 08 · Approvals & Workflow

## Roles

| Role | Can |
|---|---|
| **Clerk** | Upload, review, correct fields, resolve review items, submit for approval, retry posting |
| **Approver** | Approve or reject invoices routed to them (and below their limit) |
| **Controller** | Everything an approver can do, at any amount; edit rules, tolerances and the approval matrix; view metrics and the audit log |
| **Admin** | Users and roles, ERP connection, mailbox, budgets, vendor bank verification |

A user can hold several roles. **Segregation of duties** applies in all cases: whoever uploaded, last edited, or marked "not a duplicate" on an invoice can't approve that same invoice.

## Approval matrix

An ordered list of rules per org; the first match wins.

| Field | Example |
|---|---|
| Conditions | amount band (in org currency), vendor category, department (from the PO), has warnings |
| Approvers | a user, a role, or "PO requester" (from the ERP PO) |
| Steps | 1 or 2 sequential levels (e.g. ≤ 500k PKR: department head; above: + controller) |

Default seed:

| Amount (PKR) | Approvers |
|---|---|
| ≤ 50,000 and clean | straight-through (no approval) |
| ≤ 500,000 | department head (PO requester's manager) or any approver |
| > 500,000 | approver, then controller |

## The review screen (clerk)

- Left: the document viewer (zoom, pages). Right: the fields, grouped as header, vendor, lines, totals.
- Clicking a field highlights its evidence box on the page; low-trust fields are amber, with the reason.
- The check results list sits on top, blocking items first, each with "Show me" and "Fix" actions.
- Actions:
  - **Save & re-check**
  - **Mark not a duplicate** (reason required)
  - **Reject**, with a reason. The vendor email template is v0.2.
  - **Send for approval**: when only warnings remain, or a blocker was overridden. Overrides need the controller role.

## Approver experience

**Email** (MVP):
- Subject: `Approve: Al-Noor Traders · INV-2291 · PKR 148,562`
- Body:
  - the 4 key numbers
  - the reason it needs approval ("Above 50,000 PKR" or "Price 6% above PO")
  - a thumbnail of page 1
  - **Approve** / **Reject** / **Open in InvoiceFlow** buttons
- Links are signed (HMAC, contains approval request id + action + expiry), single use, and expire after 72 h. Reject opens a small page asking for a reason.
- Approving through the link records the approver's identity from the request plus the IP and user agent. For amounts above the controller limit, link approval is disabled and login is required.

**Slack** (optional in MVP, flag `SLACK_ENABLED`): the same card in a DM, with interactive buttons. Signature verification uses the Slack signing secret.

**Dashboard:** "My approvals" list with bulk approve for invoices with no warnings.

## Reminders and escalation

- Daily at 09:00 org time: a digest to each approver with their pending items.
- After 3 working days pending: reminder + CC the controller. After 5: escalate to the next approver in the matrix (configurable).

## Notifications (MVP)

| Event | To |
|---|---|
| Invoice needs review | Clerks (dashboard badge + daily digest) |
| Approval requested | Approvers (email / Slack) |
| Invoice rejected | Clerk who submitted |
| `BANK_CHANGED` detected | Admins + controller, immediately |
| Posting failed | Clerks + admins |
| AI budget at 80% / 100% | Admins |
