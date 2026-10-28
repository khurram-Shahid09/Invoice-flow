// Page images for the review screen, fetched with the session's token (never exposed to the browser).

import { accessToken } from "@/lib/api";
import { API_URL } from "@/lib/session";

export async function GET(_: Request, { params }: RouteContext<"/bff/invoices/[id]/pages/[n]">) {
  const { id, n } = await params;
  const token = await accessToken();
  if (!token) return new Response(null, { status: 401 });
  const upstream = await fetch(`${API_URL}/api/v1/invoices/${encodeURIComponent(id)}/pages/${Number(n)}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!upstream.ok) return new Response(null, { status: upstream.status });
  return new Response(upstream.body, {
    headers: { "Content-Type": "image/png", "Cache-Control": "private, max-age=3600" },
  });
}
