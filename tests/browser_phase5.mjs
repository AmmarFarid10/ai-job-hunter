import {
  chromium,
  expect,
} from "../dashboard/node_modules/@playwright/test/index.mjs";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir } from "node:fs/promises";
const backend = "http://127.0.0.1:8001",
  origin = "http://localhost:3001";
const key = "browser-test-key-at-least-thirty-two-characters";
const browserEmail = `owner-browser-${randomUUID()}@example.com`;
let sessionToken = null;
async function api(path, method = "GET", body) {
  const response = await fetch(backend + "/api/v1/" + path, {
    method,
    headers: {
      ...(sessionToken
        ? { "X-Owner-Session": sessionToken }
        : { "X-API-Key": key }),
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(`${path}: ${response.status} ${JSON.stringify(data)}`);
  return data;
}
sessionToken = (
  await api("auth/signup", "POST", {
    name: "Browser Owner",
    email: browserEmail,
    password: "owner-browser-password-123",
  })
).token;
const cid = (await api("candidates", "POST", { name: "Browser Demo" })).id;
await api(`candidates/${cid}/profile`, "PUT", {
  name: "Browser Demo",
  email: "fictional@example.com",
  location: "Lahore, Pakistan",
  confirmed: true,
  skills: ["Python", "FastAPI"],
  experiences: [
    {
      employer: "Fictional Company",
      title: "Senior Backend Engineer",
      start_month: "2015-01",
      is_current: true,
      bullets: ["Built Python APIs for a fictional demonstration."],
    },
  ],
});
const job = (
  await api("jobs", "POST", {
    title: "Senior Python Backend Engineer",
    company: "Fictional Browser Employer " + randomUUID().slice(0, 8),
    description:
      "Python and FastAPI required. 5 years of professional experience.",
    location: "Pakistan - Remote",
    source_name: "browser-test",
    source_url: "https://example.com/jobs/" + randomUUID(),
    application_url: "https://example.com/jobs/fictional-apply/" + randomUUID(),
  })
).job;
await api("matching/runs", "POST", { candidate_id: cid, job_ids: [job.id] });
const version = await api("resumes/generations", "POST", {
  candidate_id: cid,
  job_id: job.id,
});
const approval = await api("approvals", "POST", {
  resume_version_id: version.id,
  details: { method: "manual_handoff", destination: job.application_url },
});
const browser = await chromium.launch({
  channel: process.env.BROWSER_CHANNEL || "chrome",
  headless: true,
});
await mkdir("storage/phase5_browser", { recursive: true });
const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  }),
  page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
try {
  expect(
    (await context.request.get(origin + "/api/backend/candidates")).status(),
  ).toBe(401);
  expect(
    (
      await context.request.post(origin + "/api/session", {
        headers: { origin: "https://evil.example" },
        data: { key },
      })
    ).status(),
  ).toBe(403);
  await page.goto(origin + `/?candidate=${cid}`);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await page.getByLabel("Email", { exact: true }).fill(browserEmail);
  await page
    .getByLabel("Password", { exact: true })
    .fill("owner-browser-password-123");
  await page
    .getByRole("button", {
      name: "Log in to workspace",
    })
    .click();
  await expect(
    page.getByRole("heading", { name: "Your search, in focus." }),
  ).toBeVisible();
  await expect(
    page.getByText(job.company, { exact: false }).first(),
  ).toBeVisible();
  const cookies = await context.cookies();
  expect(
    cookies.find((c) => c.name === "job_hunter_owner_session").httpOnly,
  ).toBe(true);
  expect(JSON.stringify(cookies)).not.toContain(key);
  expect(
    (
      await context.request.post(
        origin + "/api/backend/notifications/reports",
        {
          headers: { origin: "https://evil.example" },
          data: { candidate_id: cid },
        },
      )
    ).status(),
  ).toBe(403);
  await page.screenshot({
    path: "storage/phase5_browser/overview.png",
    fullPage: true,
  });
  await page
    .locator("nav")
    .getByRole("button", { name: /Approvals/ })
    .click();
  await page.getByRole("button", { name: "Review details" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("button", { name: "Approve exact version" }),
  ).toBeDisabled();
  const responsePromise = page.waitForResponse((r) =>
    r.url().includes("/preview/1"),
  );
  await dialog
    .getByRole("button", { name: "Preview PDF", exact: true })
    .click();
  expect((await responsePromise).headers()["content-type"]).toContain(
    "image/png",
  );
  await expect(dialog.getByAltText("Resume PDF page 1")).toBeVisible();
  const pdf = await context.request.get(
    origin + "/api/backend/" + version.downloads.pdf.replace("/api/v1/", ""),
  );
  expect(pdf.status()).toBe(200);
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");
  await dialog.getByLabel("I reviewed this resume version").check();
  await dialog.getByRole("button", { name: "Approve exact version" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Approved for this exact resume",
  );
  expect((await api("approvals/" + approval.id)).effective_approved).toBe(true);
  await dialog.getByRole("button", { name: "Revoke approval" }).click();
  await expect(page.getByRole("status")).toContainText(
    "decision has been recorded",
  );
  expect((await api("approvals/" + approval.id)).effective_approved).toBe(
    false,
  );
  await dialog.getByRole("button", { name: "Create review request" }).click();
  await expect(
    dialog.getByRole("button", { name: "Request changes" }),
  ).toBeVisible();
  await dialog
    .getByLabel("Reason or requested changes")
    .fill("Please select more relevant Python bullets.");
  await dialog.getByRole("button", { name: "Request changes" }).click();
  await expect(
    dialog
      .getByText("Please select more relevant Python bullets.", { exact: true })
      .first(),
  ).toBeVisible();
  await expect(page.getByRole("status")).toContainText(
    "Your decision has been recorded.",
  );
  await expect(
    dialog.getByRole("button", { name: "Create review request" }),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "Close review" }).click();
  await expect(dialog).not.toBeVisible();
  await page
    .locator("nav")
    .getByRole("button", { name: /Activity/ })
    .click();
  await page.getByRole("button", { name: "Generate mock report" }).click();
  await expect(page.getByRole("status")).toContainText("Report");
  await page
    .locator("nav")
    .getByRole("button", { name: /Settings/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "Notification settings" }),
  ).toBeVisible();
  await page.getByLabel("Report email").fill("fictional-reports@example.com");
  await page
    .getByRole("button", { name: "Save notification settings" })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "Notification settings saved",
  );
  await page
    .locator("nav")
    .getByRole("button", { name: /Master resume/ })
    .click();
  const buffer = execFileSync(".venv/bin/python", [
    "-c",
    "import pymupdf,sys; d=pymupdf.open(); p=d.new_page(); p.insert_text((72,72),'Browser Demo Python FastAPI Azure user@example.com'); sys.stdout.buffer.write(d.tobytes())",
  ]);
  await page
    .getByLabel("Master resume PDF")
    .setInputFiles({ name: "master.pdf", mimeType: "application/pdf", buffer });
  await page
    .getByRole("button", { name: "Upload master resume", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Review uploaded resume" }),
  ).toBeVisible();
  expect(
    (await api(`candidates/${cid}`)).skills.map((row) => row.name),
  ).toEqual(["Python", "FastAPI"]);
  await expect(
    page.getByRole("button", { name: "Confirm reviewed profile" }),
  ).toBeDisabled();
  await page.getByLabel("I checked every fact against my resume").check();
  await page.getByRole("button", { name: "Confirm reviewed profile" }).click();
  await expect(
    page.getByText("This upload was already confirmed.", { exact: false }),
  ).toBeVisible();
  expect(
    (await api(`candidates/${cid}`)).skills.map((row) => row.name),
  ).toEqual(["Python", "FastAPI"]);
  await page.route("**/api/backend/discovery/providers", (route) =>
    route.fulfill({
      json: [{ name: "linkedin-tavily", kind: "tavily", configured: true }],
    }),
  );
  await page.route("**/api/backend/discovery/items?*", (route) =>
    route.fulfill({
      json: [
        {
          id: "test-lead",
          status: "REVIEW_REQUIRED",
          provider: "linkedin-tavily",
          payload: {
            title: "Python Engineer - Browser Lead",
            source_url: "https://www.linkedin.com/jobs/view/1234567890",
            description: "Unverified snippet from a search provider",
          },
        },
      ],
    }),
  );
  await page.route("**/api/backend/discovery/runs**", (route) =>
    route.fulfill({
      json:
        route.request().method() === "GET"
          ? []
          : {
              status: "COMPLETED",
              created_at: new Date().toISOString(),
              summary: {
                counts: { review_required: 1, seen: 0 },
                rejected: 0,
                errors: [],
                warnings: [],
              },
            },
    }),
  );
  await page
    .locator("nav")
    .getByRole("button", { name: /Job search/ })
    .click();
  await page.getByRole("button", { name: "Search jobs", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Last job search" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Python Engineer - Browser Lead" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Review LinkedIn job listing/ }),
  ).toHaveAttribute("href", "https://www.linkedin.com/jobs/view/1234567890");
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .locator("nav")
    .getByRole("button", { name: /Overview/ })
    .click();
  await page.screenshot({
    path: "storage/phase5_browser/mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Log in to workspace" }),
  ).toBeVisible();
  expect(
    (await context.request.get(origin + "/api/backend/candidates")).status(),
  ).toBe(401);
  expect(errors).toEqual([]);
  console.log(
    "Browser flow passed: login, authentication, CSRF, preview, download, approval, revocation, changes, mock report, settings, PDF upload/explicit confirmation, LinkedIn lead search, mobile layout, logout.",
  );
} finally {
  await browser.close();
}
