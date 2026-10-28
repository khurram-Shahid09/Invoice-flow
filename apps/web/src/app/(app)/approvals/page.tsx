import type { Metadata } from "next";

import { InvoiceTable } from "@/components/invoices";
import { api } from "@/lib/api";
import type { InvoiceSummary } from "@/lib/invoices";

export const metadata: Metadata = { title: "Approvals" };

export default async function ApprovalsPage() {
  const { results } = await api<{ results: InvoiceSummary[] }>("/invoices?status=awaiting_approval&limit=100");
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Approvals</h1>
        <p className="mt-1 text-sm text-muted">Invoices that passed every check but need a person: over the limit, or with a warning.</p>
      </div>
      <InvoiceTable invoices={results} />
    </div>
  );
}
