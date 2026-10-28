import type { Metadata } from "next";

import { InvoiceTable, UploadForm } from "@/components/invoices";
import { api } from "@/lib/api";
import type { InvoiceSummary } from "@/lib/invoices";

export const metadata: Metadata = { title: "Inbox" };

export default async function InboxPage() {
  const { results } = await api<{ results: InvoiceSummary[] }>("/invoices?limit=100");
  const count = (s: string) => results.filter((i) => i.status === s).length;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Inbox</h1>
          <p className="mt-1 text-sm text-muted">
            AI reads each invoice, rules check it, people approve exceptions, approved bills go to Odoo.
          </p>
        </div>
        <div className="flex gap-4 text-sm text-muted">
          <span><b className="text-ink">{count("posted")}</b> posted</span>
          <span><b className="text-ink">{count("awaiting_approval")}</b> awaiting approval</span>
          <span><b className="text-ink">{count("needs_review")}</b> need review</span>
        </div>
      </div>
      <UploadForm />
      <InvoiceTable invoices={results} />
    </div>
  );
}
