import { backendFetch } from "@/lib/session";
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { backend, origin, ownerToken } from "@/lib/session";
import { readBody, sameOrigin } from "@/lib/security.mjs";
export const runtime = "nodejs";
export async function POST(request: NextRequest) {
  if (!sameOrigin(request, origin()))
    return NextResponse.json({ detail: "Invalid origin" }, { status: 403 });
  let body;
  try {
    body = JSON.parse(new TextDecoder().decode(await readBody(request, 2048)));
  } catch {
    return NextResponse.json({ detail: "Invalid request" }, { status: 400 });
  }
  try {
    const token = await ownerToken();
    const response = await backendFetch("/api/v1/auth/google/start", {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { "X-Owner-Session": token } : {}),
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15_000),
    });
    const value = await response.json();
    if (!response.ok)
      return NextResponse.json(
        {
          detail:
            typeof value.detail === "string"
              ? value.detail
              : "Google sign-in could not start",
        },
        { status: response.status },
      );
    (await cookies()).set("job_hunter_google_state", value.state, {
      httpOnly: true,
      sameSite: "lax",
      secure: origin().startsWith("https:"),
      path: "/api/oauth/google",
      maxAge: 600,
    });
    return NextResponse.json({ url: value.authorization_url });
  } catch {
    return NextResponse.json(
      { detail: "Google sign-in could not start" },
      { status: 503 },
    );
  }
}
