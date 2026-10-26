import test from "node:test";
import assert from "node:assert/strict";
import { readFile, writeFile, mkdir, unlink } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Compile the actual shared component, then exercise its resulting HTML.
await mkdir(".next", { recursive: true });
const modulePath = resolve(".next", `markdown-test-${randomUUID()}.mjs`);
const source = await readFile("components/JobDescription.tsx", "utf8");
await writeFile(
  modulePath,
  ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext },
  }).outputText,
);
let JobDescription;
try {
  JobDescription = (await import(pathToFileURL(modulePath).href)).default;
} finally {
  await unlink(modulePath);
}
const render = (text) =>
  renderToStaticMarkup(React.createElement(JobDescription, { text }));

test("job Markdown renders headings, emphasis, lists, code and tables", () => {
  const html = render(
    "# Responsibilities\n\nBuild **Python** APIs.\n\n- FastAPI\n- Testing\n\n```python\nprint(1)\n```\n\n| Skill | Level |\n| --- | --- |\n| Python | Senior |",
  );
  for (const element of [
    "<h3>Responsibilities</h3>",
    "<strong>Python</strong>",
    "<ul>",
    "<li>FastAPI</li>",
    "<pre>",
    "<table>",
  ])
    assert.ok(html.includes(element), element);
});
test("untrusted descriptions cannot inject HTML, scripts, unsafe URLs or tracking images", () => {
  const html = render(
    '<script>alert(1)</script>\n\n<img src="x" onerror="alert(2)">\n\n[bad](javascript:alert%281%29)\n\n[data](data:text/html,hello)\n\n![tracking](https://tracker.invalid/pixel)\n\n[Apply](https://example.com/jobs/1)',
  );
  assert.ok(!html.includes("<script"));
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes("javascript:"));
  assert.ok(!html.includes("data:text"));
  assert.ok(!html.includes("tracker.invalid"));
  assert.ok(html.includes('href="https://example.com/jobs/1"'));
  assert.ok(html.includes('rel="noopener noreferrer"'));
});
