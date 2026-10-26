import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import {
  backendFetch,
  cookieName,
  workspaceCookie,
  origin,
} from "@/lib/session";
import { sameOrigin, readBody } from "@/lib/security.mjs";
export async function POST(request: NextRequest) {
  if (!sameOrigin(request, origin()))
    return NextResponse.json({ detail: "Invalid origin" }, { status: 403 });
  try {
    const body = JSON.parse(
      new TextDecoder().decode(await readBody(request, 4096)),
    );
    if (
      ![
        "request-verification",
        "request-password-reset",
        "verify-email",
        "reset-password",
      ].includes(body?.action)
    )
      return NextResponse.json({ detail: "Invalid action" }, { status: 400 });
    const { action, ...data } = body;
    const response = await backendFetch("/api/v1/auth/" + action, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
      signal: AbortSignal.timeout(45000),
    });
    const result = await response.json();
    if (response.ok && action === "reset-password") {
      const jar = await cookies();
      jar.delete(cookieName);
      jar.delete(workspaceCookie);
    }
    return NextResponse.json(
      {
        detail:
          typeof result.detail === "string"
            ? result.detail
            : "Check your details and try again",
      },
      { status: response.status },
    );
  } catch {
    return NextResponse.json(
      { detail: "Request could not be processed" },
      { status: 400 },
    );
  }
}
