"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useActionState, useEffect } from "react";

import { uploadInvoices, type ActionResult } from "@/app/(app)/invoice-actions";
import { BUSY, money, STATUS, type InvoiceStatus, type InvoiceSummary } from "@/lib/invoices";

export function StatusBadge({ status }: { status: InvoiceStatus }) {
  const s = STATUS[status];
  return <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${s.tone}`}>{s.label}</span>;
}

/** Refreshes the page every few seconds while something is still being processed. */
export function AutoRefresh({ active }: { active: boolean }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => router.refresh(), 2500);
    return () => clearInterval(timer);
  }, [active, router]);
  return null;
}

export function UploadForm() {
  const [state, action, pending] = useActionState<ActionResult, FormData>(uploadInvoices, { ok: true });
  return (
    <form action={action} className="flex flex-wrap items-center gap-3 rounded-xl border border-dashed border-line bg-surface p-4">
      <input
        name="files"
        type="file"
        multiple
        accept="application/pdf,image/png,image/jpeg"
        className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-canvas file:px-3 file:py-1.5 file:text-sm"
      />
      <button disabled={pending} className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-60">
        {pending ? "Uploading…" : "Upload invoices"}
      </button>
      {state.message && <span className={`text-sm ${state.ok ? "text-ok" : "text-danger"}`}>{state.message}</span>}
    </form>
  );
}

export function InvoiceTable({ invoices }: { invoices: InvoiceSummary[] }) {
  if (invoices.length === 0)
    return <p className="rounded-xl border border-line bg-surface p-8 text-center text-sm text-muted">Nothing here yet.</p>;
  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-surface">
      <AutoRefresh active={invoices.some((i) => BUSY.includes(i.status))} />
      <table className="w-full text-sm">
        <thead className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
          <tr>
            <th className="px-4 py-2.5">Vendor</th>
            <th className="px-4 py-2.5">Invoice</th>
            <th className="px-4 py-2.5 text-right">Total</th>
            <th className="px-4 py-2.5">Status</th>
            <th className="px-4 py-2.5">Why</th>
          </tr>
        </thead>
        <tbody>
          {invoices.map((inv) => (
            <tr key={inv.id} className="border-b border-line last:border-0 hover:bg-canvas/60">
              <td className="px-4 py-2.5">
                <Link href={`/invoices/${inv.id}`} className="font-medium hover:underline">
                  {inv.vendor_name || inv.filename}
                </Link>
              </td>
              <td className="px-4 py-2.5 text-muted">{inv.invoice_number || "—"}</td>
              <td className="px-4 py-2.5 text-right tabular-nums">{money(inv.total, inv.currency)}</td>
              <td className="px-4 py-2.5"><StatusBadge status={inv.status} /></td>
              <td className="max-w-xs truncate px-4 py-2.5 text-muted" title={inv.status_reason}>{inv.status_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
