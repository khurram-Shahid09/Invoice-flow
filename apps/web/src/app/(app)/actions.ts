"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { API_URL, REFRESH_COOKIE, clearSession } from "@/lib/session";

export async function logout(): Promise<void> {
  const store = await cookies();
  const refreshToken = store.get(REFRESH_COOKIE)?.value;
  if (refreshToken) {
    await fetch(`${API_URL}/api/v1/auth/logout`, {
      method: "POST",
      headers: { Cookie: `${REFRESH_COOKIE}=${encodeURIComponent(refreshToken)}` },
    }).catch(() => undefined);
  }
  clearSession(store);
  redirect("/login");
}
