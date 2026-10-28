"use client";

import Link from "next/link";
import { useActionState } from "react";

import { login, register, type AuthState } from "./actions";

const field =
  "w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/20";

export function AuthForm({ mode, next }: { mode: "login" | "register"; next?: string }) {
  const [state, action, pending] = useActionState<AuthState, FormData>(mode === "login" ? login : register, {
    error: null,
    email: "",
  });
  return (
    <form action={action} className="space-y-4">
      {mode === "register" && (
        <>
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">Your name</span>
            <input name="name" autoComplete="name" className={field} />
          </label>
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">Workspace name</span>
            <input name="org_name" required placeholder="e.g. Indus Retail" className={field} />
          </label>
        </>
      )}
      <label className="block space-y-1.5">
        <span className="text-sm font-medium">Email</span>
        <input name="email" type="email" required autoComplete="email" defaultValue={state.email} className={field} />
      </label>
      <label className="block space-y-1.5">
        <span className="text-sm font-medium">Password</span>
        <input
          name="password"
          type="password"
          required
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          className={field}
        />
      </label>
      {next && <input type="hidden" name="next" value={next} />}
      {state.error && (
        <p role="alert" className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">
          {state.error}
        </p>
      )}
      <button
        disabled={pending}
        className="w-full rounded-md bg-accent px-3 py-2 text-sm font-semibold text-white hover:bg-accent/90 disabled:opacity-60"
      >
        {pending ? "Please wait…" : mode === "login" ? "Sign in" : "Create workspace"}
      </button>
      <p className="text-center text-sm text-muted">
        {mode === "login" ? (
          <>
            New here? <Link href="/register" className="text-accent hover:underline">Create a workspace</Link>
          </>
        ) : (
          <>
            Have an account? <Link href="/login" className="text-accent hover:underline">Sign in</Link>
          </>
        )}
      </p>
    </form>
  );
}
