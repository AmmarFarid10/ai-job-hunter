import { backendFetch } from "@/lib/session";
import { cookies } from "next/headers";
import { timingSafeEqual } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { backend, cookieName, origin, workspaceCookie } from "@/lib/session";
export const runtime = "nodejs";
export async function GET(request: NextRequest) {
  const state = request.nextUrl.searchParams.get("state"),
    code = request.nextUrl.searchParams.get("code"),
    jar = await cookies();
  const expected = jar.get("job_hunter_google_state")?.value;
  jar.set("job_hunter_google_state", "", {
    path: "/api/oauth/google",
    maxAge: 0,
  });
  const fail = () =>
    NextResponse.redirect(origin() + "/?auth_error=google_failed");
  if (
    !state ||
    !expected ||
    !code ||
    state.length > 200 ||
    code.length > 4096 ||
    Buffer.byteLength(state) !== Buffer.byteLength(expected) ||
    !timingSafeEqual(Buffer.from(state), Buffer.from(expected))
  )
    return fail();
  try {
    const response = await backendFetch("/api/v1/auth/google/complete", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state, code }),
      signal: AbortSignal.timeout(40_000),
    });
    const value = await response.json();
    if (!response.ok) return fail();
    jar.delete(workspaceCookie);
    jar.set(cookieName, value.token, {
      httpOnly: true,
      sameSite: "strict",
      secure: origin().startsWith("https:"),
      path: "/",
      maxAge: 8 * 3600,
    });
    return NextResponse.redirect(origin());
  } catch {
    return fail();
  }
}
