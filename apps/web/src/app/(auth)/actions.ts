"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { authCall, writeSession } from "@/lib/session";

export interface AuthState {
  error: string | null;
  email: string;
}

function safeNext(raw: FormDataEntryValue | null): string {
  const next = typeof raw === "string" ? raw : "";
  return next.startsWith("/") && !next.startsWith("//") ? next : "/inbox"; // no open redirects
}

async function clientIp(): Promise<string | null> {
  return (await headers()).get("x-forwarded-for")?.split(",")[0]?.trim() || null;
}

export async function login(_: AuthState, form: FormData): Promise<AuthState> {
  const email = String(form.get("email") ?? "").trim();
  const { tokens, error } = await authCall("login", { email, password: String(form.get("password") ?? "") }, await clientIp());
  if (!tokens) return { error, email };
  writeSession(await cookies(), tokens);
  redirect(safeNext(form.get("next")));
}

export async function register(_: AuthState, form: FormData): Promise<AuthState> {
  const email = String(form.get("email") ?? "").trim();
  const { tokens, error } = await authCall(
    "register",
    {
      email,
      password: String(form.get("password") ?? ""),
      name: String(form.get("name") ?? ""),
      org_name: String(form.get("org_name") ?? ""),
    },
    await clientIp(),
  );
  if (!tokens) return { error, email };
  writeSession(await cookies(), tokens);
  redirect("/inbox");
}
