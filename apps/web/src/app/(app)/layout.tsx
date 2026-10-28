import Link from "next/link";
import { Suspense } from "react";

import { api } from "@/lib/api";
import type { Me } from "@/lib/types";

import { logout } from "./actions";

const NAV = [
  { href: "/inbox", label: "Inbox" },
  { href: "/approvals", label: "Approvals" },
  { href: "/vendors", label: "Vendors" },
  { href: "/settings", label: "Settings" },
] as const;

async function Account() {
  const me = await api<Me>("/me");
  const membership = me.memberships[0];
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="hidden text-muted sm:inline">
        {membership?.org.name ?? "No workspace"} · {me.name || me.email}
      </span>
      <form action={logout}>
        <button className="rounded-md border border-line px-2.5 py-1 text-muted hover:text-ink">Sign out</button>
      </form>
    </div>
  );
}

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4">
          <nav className="flex items-center gap-6">
            <Link href="/inbox" className="font-semibold tracking-tight">
              InvoiceFlow
            </Link>
            {NAV.map((item) => (
              <Link key={item.href} href={item.href} className="hidden text-sm text-muted hover:text-ink sm:inline">
                {item.label}
              </Link>
            ))}
          </nav>
          <Suspense fallback={<span className="text-sm text-muted">…</span>}>
            <Account />
          </Suspense>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
        {/* Pages read the session; the boundary keeps the shell static (Cache Components). */}
        <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>{children}</Suspense>
      </main>
    </>
  );
}
