export function sameOrigin(request, origin) {
  return request.headers.get("origin") === origin;
}
export function backendPath(parts) {
  if (!parts.length || parts.some((p) => !/^[a-zA-Z0-9_-]+$/.test(p)))
    return null;
  if (
    ![
      "candidates",
      "admin",
      "jobs",
      "matching",
      "discovery",
      "resumes",
      "approvals",
      "notifications",
      "applications",
      "dashboard",
    ].includes(parts[0])
  )
    return null;
  return "/api/v1/" + parts.join("/");
}

export async function readBody(request, maximum) {
  const declared = Number(request.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > maximum)
    throw new RangeError("Request too large");
  if (!request.body) return new ArrayBuffer(0);
  const reader = request.body.getReader(),
    chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > maximum) {
      await reader.cancel();
      throw new RangeError("Request too large");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let position = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, position);
    position += chunk.byteLength;
  }
  return bytes.buffer;
}
