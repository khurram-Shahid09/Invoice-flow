import type { Metadata } from "next";
import Link from "next/link";

import { api } from "@/lib/api";
import type { InvoiceDetail } from "@/lib/invoices";
import type { Me } from "@/lib/types";

import { Review } from "./review";

export const metadata: Metadata = { title: "Invoice" };

export default async function InvoicePage({ params }: PageProps<"/invoices/[id]">) {
  const { id } = await params;
  const [invoice, me] = await Promise.all([api<InvoiceDetail>(`/invoices/${id}`), api<Me>("/me")]);
  return (
    <div className="space-y-4">
      <Link href="/inbox" className="text-sm text-muted hover:text-ink">← Inbox</Link>
      <Review invoice={invoice} roles={me.memberships[0]?.roles ?? []} />
    </div>
  );
}
