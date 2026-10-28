"use server";

import { refresh } from "next/cache";

import { accessToken, api, ApiError } from "@/lib/api";
import { API_URL } from "@/lib/session";

// Server Functions are reachable by POST from anywhere: every one re-checks the session via api().

export interface ActionResult {
  ok: boolean;
  message?: string;
}

async function run(call: () => Promise<unknown>): Promise<ActionResult> {
  try {
    await call();
    refresh();
    return { ok: true };
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, message: error.message };
    throw error;
  }
}

export async function uploadInvoices(_: ActionResult, form: FormData): Promise<ActionResult> {
  const token = await accessToken();
  const files = form.getAll("files").filter((f): f is File => f instanceof File && f.size > 0);
  if (!token) return { ok: false, message: "Sign in again." };
  if (files.length === 0) return { ok: false, message: "Choose at least one PDF or image." };
  const body = new FormData();
  for (const file of files) body.append("files", file, file.name);
  const response = await fetch(`${API_URL}/api/v1/documents`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body,
  });
  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
    return { ok: false, message: data?.error?.message ?? `Upload failed (${response.status}).` };
  }
  refresh();
  return { ok: true, message: `${files.length} file${files.length > 1 ? "s" : ""} received.` };
}

export async function decide(id: string, decision: "approve" | "reject", reason = ""): Promise<ActionResult> {
  return run(() => api(`/invoices/${id}/decision`, { method: "POST", body: JSON.stringify({ decision, reason }) }));
}

export async function saveFields(id: string, values: Record<string, string>): Promise<ActionResult> {
  return run(() => api(`/invoices/${id}/fields`, { method: "PATCH", body: JSON.stringify({ values }) }));
}

export async function retry(id: string): Promise<ActionResult> {
  return run(() => api(`/invoices/${id}/retry`, { method: "POST" }));
}
