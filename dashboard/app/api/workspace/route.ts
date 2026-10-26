import { backendFetch } from "@/lib/session";
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { backend, origin, ownerToken, workspaceCookie } from "@/lib/session";
import { sameOrigin, readBody } from "@/lib/security.mjs";
export async function POST(request: NextRequest) {
  if (!sameOrigin(request, origin()))
    return NextResponse.json({ detail: "Invalid origin" }, { status: 403 });
  try {
    const token = await ownerToken();
    if (!token)
      return NextResponse.json({ detail: "Sign in required" }, { status: 401 });
    const { account_id } = JSON.parse(
      new TextDecoder().decode(await readBody(request, 1024)),
    );
    const response = await backendFetch("/api/v1/admin/users", {
      headers: { "X-Owner-Session": token },
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok)
      return NextResponse.json(
        { detail: "Administrator access required" },
        { status: response.status },
      );
    if (account_id) {
      if (
        typeof account_id !== "string" ||
        !/^[0-9a-f-]{36}$/i.test(account_id)
      )
        return NextResponse.json(
          { detail: "Invalid workspace" },
          { status: 400 },
        );
      const target = await backendFetch("/api/v1/candidates?limit=1", {
        headers: { "X-Owner-Session": token, "X-Workspace-User": account_id },
        cache: "no-store",
        signal: AbortSignal.timeout(10000),
      });
      if (!target.ok)
        return NextResponse.json(
          { detail: "Workspace not available" },
          { status: target.status },
        );
    }
    const jar = await cookies();
    if (account_id)
      jar.set(workspaceCookie, account_id, {
        httpOnly: true,
        sameSite: "strict",
        secure: origin().startsWith("https:"),
        path: "/",
        maxAge: 8 * 3600,
      });
    else jar.delete(workspaceCookie);
    return NextResponse.json({ ok: true });
  } catch {
    return NextResponse.json(
      { detail: "Workspace could not be selected" },
      { status: 400 },
    );
  }
}
