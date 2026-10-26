import test from "node:test";
import assert from "node:assert/strict";
import { sameOrigin, backendPath, readBody } from "../lib/security.mjs";
test("mutations require exact configured origin", () => {
  assert.ok(
    sameOrigin(
      new Request("http://localhost", {
        headers: { origin: "http://localhost:3000" },
      }),
      "http://localhost:3000",
    ),
  );
  assert.equal(
    sameOrigin(
      new Request("http://localhost", {
        headers: { origin: "https://evil.example" },
      }),
      "http://localhost:3000",
    ),
    false,
  );
  assert.equal(
    sameOrigin(new Request("http://localhost"), "http://localhost:3000"),
    false,
  );
});
test("API proxy cannot traverse paths or act as an open proxy", () => {
  assert.equal(
    backendPath(["resumes", "versions", "uuid", "download", "pdf"]),
    "/api/v1/resumes/versions/uuid/download/pdf",
  );
  for (const parts of [
    ["..", "secret"],
    ["jobs", ".."],
    ["jobs", "%2e%2e"],
    ["jobs", "https://evil.example"],
    ["health"],
    [],
  ])
    assert.equal(backendPath(parts), null);
});

test("request bodies are bounded while streaming, including multipart", async () => {
  const bytes = await readBody(
    new Request("http://localhost", { method: "POST", body: "PDF bytes" }),
    20,
  );
  assert.equal(new TextDecoder().decode(bytes), "PDF bytes");
  await assert.rejects(
    readBody(
      new Request("http://localhost", {
        method: "POST",
        body: "x".repeat(100),
      }),
      20,
    ),
    RangeError,
  );
  await assert.rejects(
    readBody(
      new Request("http://localhost", {
        method: "POST",
        headers: { "content-length": "1000" },
        body: "small",
      }),
      20,
    ),
    RangeError,
  );
});
