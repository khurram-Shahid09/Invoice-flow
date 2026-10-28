// Session cookies for the dashboard (backend-for-frontend, docs/03-architecture.md).
//
// The API runs on another site, so its refresh cookie would be third-party in the browser.
// Instead the Next.js server talks to the API and keeps both tokens in first-party,
// httpOnly cookies on the dashboard's own origin. Browser code never sees a token.

export const API_URL = (process.env.INVOICEFLOW_API_URL ?? "http://localhost:8100").replace(/\/$/, "");
export const ACCESS_COOKIE = "if_access";
export const REFRESH_COOKIE = "if_refresh";
/** Set by proxy.ts after a refresh, so this request's server code already has the new token. */
export const ACCESS_HEADER = "x-if-access";

const secure = process.env.NODE_ENV === "production";
const REFRESH_MAX_AGE = 30 * 24 * 60 * 60;

export interface Tokens {
  access: string;
  accessExpiresIn: number; // seconds
  refresh: string;
}

type CookieWriter = { set(name: string, value: string, options: Record<string, unknown>): unknown };

export function writeSession(cookies: CookieWriter, tokens: Tokens): void {
  const base = { httpOnly: true, sameSite: "lax", secure, path: "/" };
  // Expire the access cookie a minute early so a refresh happens before the JWT lapses.
  cookies.set(ACCESS_COOKIE, tokens.access, { ...base, maxAge: Math.max(tokens.accessExpiresIn - 60, 30) });
  cookies.set(REFRESH_COOKIE, tokens.refresh, { ...base, maxAge: REFRESH_MAX_AGE });
}

export function clearSession(cookies: { delete(name: string): unknown }): void {
  cookies.delete(ACCESS_COOKIE);
  cookies.delete(REFRESH_COOKIE);
}

/** The API's rotated refresh token, from its Set-Cookie header. */
export function refreshFromSetCookie(response: Response): string | null {
  for (const line of response.headers.getSetCookie()) {
    const match = /^if_refresh=([^;]*)/.exec(line);
    if (match?.[1]) return decodeURIComponent(match[1]);
  }
  return null;
}

async function tokensFrom(response: Response): Promise<Tokens | null> {
  if (!response.ok) return null;
  const body = (await response.json()) as { access: string; access_expires_in: number };
  const refresh = refreshFromSetCookie(response);
  return refresh ? { access: body.access, accessExpiresIn: body.access_expires_in, refresh } : null;
}

// The API revokes every session of a user when a rotated refresh token is presented twice
// (reuse detection). Parallel requests that all find an expired access cookie would do
// exactly that, so concurrent refreshes with the same token share one call.
const inflight = new Map<string, Promise<Tokens | null>>();

export function refreshTokens(refresh: string): Promise<Tokens | null> {
  let pending = inflight.get(refresh);
  if (!pending) {
    pending = fetch(`${API_URL}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { Cookie: `${REFRESH_COOKIE}=${encodeURIComponent(refresh)}` },
      cache: "no-store",
    })
      .then(tokensFrom)
      .catch(() => null);
    inflight.set(refresh, pending);
    setTimeout(() => inflight.delete(refresh), 30_000); // late duplicates reuse the result
  }
  return pending;
}

export async function authCall(
  path: "login" | "register",
  body: Record<string, string>,
  clientIp: string | null,
): Promise<{ tokens: Tokens | null; error: string | null }> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/v1/auth/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(clientIp ? { "X-Forwarded-For": clientIp } : {}) },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return { tokens: null, error: "Can't reach the InvoiceFlow API. Is it running?" };
  }
  if (response.ok) {
    const tokens = await tokensFrom(response);
    return tokens ? { tokens, error: null } : { tokens: null, error: "Unexpected response from the API." };
  }
  const data = (await response.json().catch(() => null)) as {
    error?: { message?: string; details?: Record<string, string[]> };
  } | null;
  const details = Object.values(data?.error?.details ?? {}).flat();
  return { tokens: null, error: details[0] ?? data?.error?.message ?? `Request failed (${response.status}).` };
}
