// Server-side API client (Server Components and Server Functions only).

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { ACCESS_COOKIE, ACCESS_HEADER, API_URL } from "./session";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

export async function accessToken(): Promise<string | null> {
  const fromProxy = (await headers()).get(ACCESS_HEADER);
  return fromProxy ?? (await cookies()).get(ACCESS_COOKIE)?.value ?? null;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await accessToken();
  if (!token) redirect("/login");
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/v1${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...init.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", "Can't reach the InvoiceFlow API. Is it running?");
  }
  if (response.status === 401) redirect("/login");
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (body as { error?: { code?: string; message?: string; details?: Record<string, unknown> } })?.error;
    throw new ApiError(response.status, error?.code ?? "http_error", error?.message ?? `Request failed (${response.status}).`, error?.details);
  }
  return body as T;
}
