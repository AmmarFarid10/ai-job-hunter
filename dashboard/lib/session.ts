import { cookies } from "next/headers";
export const workspaceCookie = "job_hunter_workspace";
export const cookieName = "job_hunter_owner_session";
export const backend = () => process.env.BACKEND_URL || "http://localhost:8000";
export const origin = () =>
  process.env.DASHBOARD_ORIGIN || "http://localhost:3000";
export async function ownerToken() {
  return (await cookies()).get(cookieName)?.value;
}
export async function authenticated() {
  const token = await ownerToken();
  if (!token) return false;
  try {
    const response = await backendFetch("/api/v1/auth/me", {
      headers: { "X-Owner-Session": token },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function backendFetch(path: string, init: RequestInit = {}) {
  const incoming = await (await import("next/headers")).headers();
  const supplied = Object.fromEntries(new Headers(init.headers).entries());
  return fetch(backend() + path, {
    ...init,
    headers: {
      ...supplied,
      ...(process.env.GATEWAY_TOKEN
        ? { "X-Gateway-Token": process.env.GATEWAY_TOKEN }
        : {}),
      "X-Client-IP": (incoming.get("x-forwarded-for") || "unknown")
        .split(",")
        .at(-1)!
        .trim(),
    },
  });
}
