// Runs before every page and screenshot request: keeps the session fresh and sends
// signed-out visitors to /login. Refreshing happens here because Server Components can't
// set cookies; the new access token is also forwarded to this request as a header.

import { NextResponse, type NextRequest } from "next/server";

import { ACCESS_COOKIE, ACCESS_HEADER, REFRESH_COOKIE, clearSession, refreshTokens, writeSession } from "./lib/session";

const PUBLIC_PATHS = ["/login", "/register"];

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const isPublic = PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  const forwarded = new Headers(request.headers);
  forwarded.delete(ACCESS_HEADER); // only this file may set it

  if (request.cookies.has(ACCESS_COOKIE)) {
    return isPublic
      ? NextResponse.redirect(new URL("/inbox", request.url))
      : NextResponse.next({ request: { headers: forwarded } });
  }

  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  const tokens = refresh ? await refreshTokens(refresh) : null;
  if (tokens) {
    forwarded.set(ACCESS_HEADER, tokens.access);
    const response = isPublic
      ? NextResponse.redirect(new URL("/inbox", request.url))
      : NextResponse.next({ request: { headers: forwarded } });
    writeSession(response.cookies, tokens);
    return response;
  }

  const response = isPublic
    ? NextResponse.next({ request: { headers: forwarded } })
    : pathname.startsWith("/bff/")
      ? NextResponse.json({ error: { code: "not_authenticated", message: "Sign in again." } }, { status: 401 })
      : NextResponse.redirect(new URL(`/login?next=${encodeURIComponent(pathname + search)}`, request.url));
  if (refresh) clearSession(response.cookies); // expired or revoked
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|svg|ico|webp|jpg)$).*)"],
};
