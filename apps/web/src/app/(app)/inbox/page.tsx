import type { Metadata } from "next";

import { api } from "@/lib/api";
import type { Me, Role } from "@/lib/types";

export const metadata: Metadata = { title: "Inbox" };

const ROLE_HELP: Record<Role, string> = {
  clerk: "Upload invoices, review what the AI read, and fix anything flagged.",
  approver: "Approve or reject invoices routed to you.",
  controller: "Set the rules and tolerances, and see the metrics and audit trail.",
  admin: "Manage people, the ERP connection and the mailbox.",
};

export default async function InboxPage() {
  const me = await api<Me>("/me");
  const membership = me.memberships[0];
  const roles = membership?.roles ?? [];
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Inbox</h1>
        <p className="mt-1 text-sm text-muted">Invoices from email and uploads appear here as they are read and checked.</p>
      </div>
      <section className="rounded-xl border border-dashed border-line bg-surface p-8 text-center">
        <p className="font-medium">No invoices yet</p>
        <p className="mt-1 text-sm text-muted">Uploading and the email inbox arrive on day 4 of the build plan.</p>
      </section>
      <section className="rounded-xl border border-line bg-surface p-5">
        <h2 className="text-sm font-semibold">What you can do here</h2>
        <ul className="mt-3 space-y-2 text-sm">
          {roles.map((role) => (
            <li key={role} className="flex gap-3">
              <span className="w-24 shrink-0 rounded-md bg-canvas px-2 py-0.5 text-center text-xs font-medium capitalize">{role}</span>
              <span className="text-muted">{ROLE_HELP[role]}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
