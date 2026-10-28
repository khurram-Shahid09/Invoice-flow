import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "../auth-form";

export const metadata: Metadata = { title: "Sign in" };

async function LoginForm({ searchParams }: { searchParams: PageProps<"/login">["searchParams"] }) {
  const { next } = await searchParams;
  return <AuthForm mode="login" next={typeof next === "string" ? next : undefined} />;
}

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <>
      <h1 className="mb-5 text-lg font-semibold">Sign in</h1>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <LoginForm searchParams={searchParams} />
      </Suspense>
    </>
  );
}
