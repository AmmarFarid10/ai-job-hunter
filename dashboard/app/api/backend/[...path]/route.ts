import { backendFetch } from "@/lib/session";
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import {
  authenticated,
  backend,
  origin,
  ownerToken,
  workspaceCookie,
} from "@/lib/session";
import { backendPath, sameOrigin, readBody } from "@/lib/security.mjs";
export const runtime = "nodejs";
async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  if (!(await authenticated()))
    return NextResponse.json({ detail: "Sign in required" }, { status: 401 });
  if (
    !["GET", "HEAD"].includes(request.method) &&
    !sameOrigin(request, origin())
  )
    return NextResponse.json({ detail: "Invalid origin" }, { status: 403 });
  const path = backendPath((await context.params).path);
  if (!path)
    return NextResponse.json({ detail: "Invalid API path" }, { status: 400 });
  let payload: ArrayBuffer | undefined;
  try {
    if (!["GET", "HEAD"].includes(request.method))
      payload = await readBody(request, 11 * 1024 * 1024);
  } catch {
    return NextResponse.json({ detail: "Request too large" }, { status: 413 });
  }
  try {
    const response = await backendFetch(path + request.nextUrl.search, {
      method: request.method,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(120_000),
      headers: {
        "X-Owner-Session": (await ownerToken())!,
        ...((await cookies()).get(workspaceCookie)?.value
          ? {
              "X-Workspace-User": (await cookies()).get(workspaceCookie)!.value,
            }
          : {}),
        "Content-Type":
          request.headers.get("content-type") || "application/json",
      },
      body: payload,
    });
    const headers = new Headers({
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    });
    for (const name of ["content-type", "content-disposition"]) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    if (
      path.endsWith("/download/pdf") &&
      request.nextUrl.searchParams.get("preview") === "1"
    )
      headers.set("content-disposition", 'inline; filename="resume.pdf"');
    return new Response(response.body, { status: response.status, headers });
  } catch {
    return NextResponse.json(
      { detail: "Backend unavailable" },
      { status: 503 },
    );
  }
}
export { proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE };
