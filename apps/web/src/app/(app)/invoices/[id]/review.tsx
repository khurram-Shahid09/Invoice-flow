"use client";

import { useState, useTransition } from "react";

import { AutoRefresh, StatusBadge } from "@/components/invoices";
import { BUSY, FIELD_LABELS, money, type Evidence, type InvoiceDetail } from "@/lib/invoices";
import type { Role } from "@/lib/types";

import { decide, retry, saveFields, type ActionResult } from "../../invoice-actions";

const AMOUNTS = new Set(["subtotal", "tax_total", "shipping", "total"]);
const SEVERITY = {
  blocking: "border-danger/40 bg-danger/5 text-danger",
  warning: "border-warn/40 bg-warn-soft text-warn",
  info: "border-line bg-canvas text-muted",
};
const GROUNDING: Record<string, string> = {
  exact: "Found on the page",
  fuzzy: "Found on the page (approximately)",
  model_only: "Read from an image: no text layer to verify against",
  none: "Not found on the page, so not used",
  unparseable: "Couldn't be read as a value",
  edited: "Corrected by a person",
  answer_key: "Offline demo mode",
  absent: "Not on the document",
};

function Pages({ invoice, focus }: { invoice: InvoiceDetail; focus: Evidence | null }) {
  return (
    <div className="space-y-3">
      {invoice.pages.map((page) => (
        <div key={page.number} className="relative overflow-hidden rounded-lg border border-line bg-white shadow-sm">
          {/* eslint-disable-next-line @next/next/no-img-element -- authenticated image through the BFF */}
          <img src={`/bff/invoices/${invoice.id}/pages/${page.number}`} alt={`Page ${page.number}`} className="block w-full" />
          {focus?.box && (focus.page ?? 1) === page.number && (
            <div
              className="pointer-events-none absolute rounded-sm border-2 border-accent bg-accent/15"
              style={{
                left: `${focus.box[0] * 100 - 0.5}%`,
                top: `${focus.box[1] * 100 - 0.4}%`,
                width: `${(focus.box[2] - focus.box[0]) * 100 + 1}%`,
                height: `${(focus.box[3] - focus.box[1]) * 100 + 0.8}%`,
              }}
            />
          )}
        </div>
      ))}
    </div>
  );
}

export function Review({ invoice, roles }: { invoice: InvoiceDetail; roles: Role[] }) {
  const [focus, setFocus] = useState<Evidence | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ActionResult | null>(null);
  const [pending, start] = useTransition();
  const canApprove = roles.some((r) => r === "approver" || r === "controller");
  const canEdit = roles.some((r) => r === "clerk" || r === "admin");
  const open = invoice.status === "awaiting_approval" || invoice.status === "needs_review";
  const act = (call: () => Promise<ActionResult>) => start(async () => setResult(await call()));
  const flagged = new Set(invoice.checks.filter((c) => c.severity !== "info").flatMap((c) => c.fields));

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <AutoRefresh active={BUSY.includes(invoice.status)} />
      <Pages invoice={invoice} focus={focus} />

      <div className="space-y-4">
        <div className="rounded-xl border border-line bg-surface p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-lg font-semibold">{invoice.vendor_name || invoice.filename}</div>
              <div className="text-sm text-muted">
                {invoice.invoice_number || "No number"} · {money(invoice.total, invoice.currency)}
                {invoice.po_number && <> · PO {invoice.po_number}</>}
              </div>
            </div>
            <StatusBadge status={invoice.status} />
          </div>
          {invoice.decision.reasons && invoice.decision.reasons.length > 0 && (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">
              {invoice.decision.reasons.map((r) => <li key={r}>{r}</li>)}
            </ul>
          )}
          {invoice.erp_url && (
            <p className="mt-3 text-sm">
              Bill {invoice.erp_bill_id} in the ERP:{" "}
              <a href={invoice.erp_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">open in Odoo</a>
            </p>
          )}
          {invoice.status_reason && !invoice.decision.reasons?.includes(invoice.status_reason) && (
            <p className="mt-2 text-sm text-muted">{invoice.status_reason}</p>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            {canApprove && invoice.status === "awaiting_approval" && (
              <button disabled={pending} onClick={() => act(() => decide(invoice.id, "approve"))} className="rounded-md bg-ok px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-60">
                Approve and post
              </button>
            )}
            {open && (canApprove || canEdit) && (
              <button
                disabled={pending}
                onClick={() => {
                  const reason = window.prompt("Why is it rejected?");
                  if (reason) act(() => decide(invoice.id, "reject", reason));
                }}
                className="rounded-md border border-line px-3 py-1.5 text-sm"
              >
                Reject
              </button>
            )}
            {canEdit && open && !editing && (
              <button onClick={() => setEditing(true)} className="rounded-md border border-line px-3 py-1.5 text-sm">Correct fields</button>
            )}
            {canEdit && (invoice.status === "extraction_failed" || invoice.status === "posting_failed") && (
              <button disabled={pending} onClick={() => act(() => retry(invoice.id))} className="rounded-md border border-line px-3 py-1.5 text-sm">Retry</button>
            )}
          </div>
          {result?.message && <p className={`mt-2 text-sm ${result.ok ? "text-ok" : "text-danger"}`}>{result.message}</p>}
        </div>

        {invoice.checks.length > 0 && (
          <div className="space-y-2">
            {invoice.checks.map((c, i) => (
              <div key={i} className={`rounded-lg border px-3 py-2 text-sm ${SEVERITY[c.severity]}`}>
                <span className="font-mono text-xs font-semibold">{c.code}</span> · {c.message}
              </div>
            ))}
          </div>
        )}

        <div className="rounded-xl border border-line bg-surface">
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5 text-sm font-semibold">
            <span>What the AI read</span>
            <span className="text-xs font-normal text-muted">Hover a value to see it on the page</span>
          </div>
          <dl className="divide-y divide-line text-sm">
            {Object.entries(FIELD_LABELS).map(([name, label]) => {
              const ev = invoice.fields[name];
              if (!ev) return null;
              const shown = AMOUNTS.has(name) ? money(ev.value) : (ev.value ?? "—");
              return (
                <div
                  key={name}
                  onMouseEnter={() => setFocus(ev)}
                  onMouseLeave={() => setFocus(null)}
                  className={`grid grid-cols-[9rem_1fr] gap-3 px-4 py-2 ${flagged.has(name) ? "bg-warn-soft/60" : ""}`}
                >
                  <dt className="text-muted">{label}</dt>
                  <dd title={GROUNDING[ev.grounding] ?? ev.grounding}>
                    {editing ? (
                      <input
                        defaultValue={ev.value ?? ""}
                        onChange={(e) => setDraft({ ...draft, [name]: e.target.value })}
                        className="w-full rounded border border-line bg-surface px-2 py-0.5"
                      />
                    ) : (
                      <span className={ev.grounding === "none" ? "text-danger" : ""}>
                        {shown}
                        {ev.grounding === "none" && ev.rejected && <span className="ml-2 text-xs">(AI said “{ev.rejected}”, not on the page)</span>}
                        {ev.box && <span className="ml-2 text-xs text-ok">●</span>}
                      </span>
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
          {editing && (
            <div className="flex gap-2 border-t border-line px-4 py-3">
              <button disabled={pending} onClick={() => act(async () => { const r = await saveFields(invoice.id, draft); if (r.ok) setEditing(false); return r; })} className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-white">
                Save and re-check
              </button>
              <button onClick={() => setEditing(false)} className="rounded-md border border-line px-3 py-1.5 text-sm">Cancel</button>
            </div>
          )}
        </div>

        {invoice.lines.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-line bg-surface">
            <table className="w-full text-sm">
              <thead className="border-b border-line text-left text-xs uppercase text-muted">
                <tr><th className="px-3 py-2">Item</th><th className="px-3 py-2 text-right">Qty</th><th className="px-3 py-2 text-right">Price</th><th className="px-3 py-2 text-right">Amount</th></tr>
              </thead>
              <tbody>
                {invoice.lines.map((line, i) => (
                  <tr key={i} className={`border-b border-line last:border-0 ${flagged.has(`lines.${i + 1}`) || flagged.has(`lines.${i + 1}.unit_price`) || flagged.has(`lines.${i + 1}.quantity`) ? "bg-warn-soft/60" : ""}`}>
                    <td className="px-3 py-2" onMouseEnter={() => setFocus(line.description)} onMouseLeave={() => setFocus(null)}>
                      {line.description?.value}
                      {line.product_code?.value && <span className="ml-2 text-xs text-muted">{line.product_code.value}</span>}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums" onMouseEnter={() => setFocus(line.quantity)} onMouseLeave={() => setFocus(null)}>{line.quantity?.value}</td>
                    <td className="px-3 py-2 text-right tabular-nums" onMouseEnter={() => setFocus(line.unit_price)} onMouseLeave={() => setFocus(null)}>{money(line.unit_price?.value ?? null)}</td>
                    <td className="px-3 py-2 text-right tabular-nums" onMouseEnter={() => setFocus(line.line_total)} onMouseLeave={() => setFocus(null)}>{money(line.line_total?.value ?? null)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-xs text-muted">
          Read by {invoice.extraction.provider ?? "—"} {invoice.extraction.model ?? ""}
          {invoice.extraction.ms ? ` in ${(invoice.extraction.ms / 1000).toFixed(1)} s` : ""}
          {invoice.extraction.input_tokens ? ` · ${invoice.extraction.input_tokens + (invoice.extraction.output_tokens ?? 0)} tokens` : ""}
          {" · "}rules {invoice.decision.rules_version ?? "—"}
          {invoice.decision.vendor_matched_by && ` · vendor matched by ${invoice.decision.vendor_matched_by.replace("_", " ")}`}
          {!invoice.has_text_layer && " · scanned or photographed: values can't be located on the page"}
        </p>
      </div>
    </div>
  );
}
