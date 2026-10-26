import { backendFetch } from "@/lib/session";
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import {
  backend,
  cookieName,
  origin,
  ownerToken,
  workspaceCookie,
} from "@/lib/session";
import { sameOrigin, readBody } from "@/lib/security.mjs";
export const runtime = "nodejs";
export async function GET() {
  try {
    const token = await ownerToken();
    if (token) {
      const response = await backendFetch("/api/v1/auth/me", {
        headers: { "X-Owner-Session": token },
        cache: "no-store",
        signal: AbortSignal.timeout(10_000),
      });
      if (response.ok) {
        const available = await backendFetch("/api/v1/auth/status", {
          cache: "no-store",
        });
        return NextResponse.json({
          authenticated: true,
          workspace_id: (await cookies()).get(workspaceCookie)?.value || null,
          ...(await response.json()),
          ...(await available.json()),
        });
      }
    }
    const response = await backendFetch("/api/v1/auth/status", {
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) throw new Error();
    return NextResponse.json({
      authenticated: false,
      ...(await response.json()),
    });
  } catch {
    return NextResponse.json(
      { detail: "Backend unavailable" },
      { status: 503 },
    );
  }
}
export async function POST(request: NextRequest) {
  if (!sameOrigin(request, origin()))
    return NextResponse.json({ detail: "Invalid origin" }, { status: 403 });
  let body: string;
  try {
    body = new TextDecoder().decode(await readBody(request, 4096));
  } catch {
    return NextResponse.json({ detail: "Request too large" }, { status: 413 });
  }
  let data;
  try {
    data = JSON.parse(body);
  } catch {
    return NextResponse.json({ detail: "Invalid request" }, { status: 400 });
  }
  if (
    data === null ||
    typeof data !== "object" ||
    !["login", "signup"].includes(data.mode)
  )
    return NextResponse.json(
      { detail: "Invalid sign-in request" },
      { status: 400 },
    );
  const { mode, ...credentials } = data;
  try {
    const response = await backendFetch("/api/v1/auth/" + mode, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(credentials),
      signal: AbortSignal.timeout(15_000),
    });
    const result = await response.json();
    if (!response.ok)
      return NextResponse.json(
        {
          detail:
            typeof result.detail === "string"
              ? result.detail
              : "Check the form. Passwords must contain 12–128 characters.",
        },
        { status: response.status },
      );
    (await cookies()).delete(workspaceCookie);
    (await cookies()).set(cookieName, result.token, {
      httpOnly: true,
      sameSite: "strict",
      secure: origin().startsWith("https:"),
      path: "/",
      maxAge: 8 * 3600,
    });
    return NextResponse.json({ authenticated: true, user: result.user });
  } catch {
    return NextResponse.json(
      { detail: "Backend unavailable" },
      { status: 503 },
    );
  }
}
export async function DELETE(request: NextRequest) {
  if (!sameOrigin(request, origin()))
    return NextResponse.json({ detail: "Invalid origin" }, { status: 403 });
  const token = await ownerToken();
  try {
    if (token) {
      const response = await backendFetch("/api/v1/auth/logout", {
        method: "POST",
        headers: { "X-Owner-Session": token },
        signal: AbortSignal.timeout(10_000),
      });
      if (!response.ok && response.status !== 401) throw new Error();
    }
    (await cookies()).delete(cookieName);
    (await cookies()).delete(workspaceCookie);
    return NextResponse.json({ authenticated: false });
  } catch {
    return NextResponse.json(
      { detail: "Could not revoke session. Try signing out again." },
      { status: 503 },
    );
  }
}
