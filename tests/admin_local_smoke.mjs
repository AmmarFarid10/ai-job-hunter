// Authorized local administrator smoke check; never print credentials or profile contents.
import {
  chromium,
  expect,
} from "../dashboard/node_modules/@playwright/test/index.mjs";
import { readFile } from "node:fs/promises";
import { parseEnv } from "node:util";
const origin = "http://localhost:3000";
const credentials = parseEnv(await readFile(".env", "utf8"));
if (!credentials.ADMIN_EMAIL || !credentials.ADMIN_PASSWORD)
  throw new Error("Administrator configuration missing");
const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || "chrome", headless: true });
const context = await browser.newContext(),
  page = await context.newPage();
try {
  const response = await context.request.post(origin + "/api/session", {
    headers: { origin },
    data: {
      mode: "login",
      email: credentials.ADMIN_EMAIL,
      password: credentials.ADMIN_PASSWORD,
    },
  });
  expect(response.status()).toBe(200);
  const session = await (
    await context.request.get(origin + "/api/session")
  ).json();
  expect(session.user.role).toBe("ADMIN");
  await page.goto(origin);
  await page
    .locator("nav")
    .getByRole("button", { name: /Administration/ })
    .click();
  const row = page.getByRole("row").filter({
    has: page.getByRole("cell", {
      name: "Imported private workspace",
      exact: true,
    }),
  });
  await row
    .getByRole("button", { name: "View workspace", exact: true })
    .click();
  await expect(
    page.getByRole("status").filter({ hasText: "Administrator view" }),
  ).toBeVisible();
  const candidates = await (
    await context.request.get(origin + "/api/backend/candidates")
  ).json();
  expect(candidates.length).toBeGreaterThan(0);
  const dashboards = await Promise.all(
    candidates.map(async (candidate) =>
      (
        await context.request.get(
          origin + "/api/backend/dashboard/" + candidate.id,
        )
      ).json(),
    ),
  );
  const jobs = Math.max(...dashboards.map((data) => data.jobs.length));
  const resumes = dashboards.reduce(
    (total, data) => total + data.resumes.length,
    0,
  );
  expect(jobs).toBeGreaterThan(0);
  expect(resumes).toBeGreaterThan(0);
  await page
    .locator("nav")
    .getByRole("button", { name: /Job search/ })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Saved job leads · last 7 days",
      exact: true,
    }),
  ).toBeVisible();
  const recentResponse = await context.request.get(
    origin + "/api/backend/discovery/items?posted_within_days=7",
  );
  expect(recentResponse.status()).toBe(200);
  const recent = await recentResponse.json();
  expect(Array.isArray(recent)).toBe(true);
  for (const item of recent) {
    const posted = Date.parse(item.payload.posted_at);
    expect(posted).toBeGreaterThanOrEqual(Date.now() - 7 * 86400000 - 1000);
    expect(posted).toBeLessThanOrEqual(Date.now());
  }
  // Isolated browser fixtures verify labels/links without persisting fake leads.
  await page.route("**/api/backend/discovery/items?*", (route) =>
    route.fulfill({
      json: [
        {
          id: "listing-fixture",
          status: "REVIEW_REQUIRED",
          payload: {
            title: "Fixture job listing",
            source_url: "https://linkedin.com/jobs/view/1234567890",
            description: "## Role\n\n- Build **Python** APIs",
            posted_at: new Date().toISOString(),
          },
        },
        {
          id: "post-fixture",
          status: "REVIEW_REQUIRED",
          payload: {
            title: "Fixture hiring post",
            source_url: "https://linkedin.com/posts/fixture-hiring",
            description: "Hiring post for review",
            posted_at: new Date().toISOString(),
          },
        },
      ],
    }),
  );
  await page
    .locator("nav")
    .getByRole("button", { name: /Overview/ })
    .click();
  await page
    .locator("nav")
    .getByRole("button", { name: /Job search/ })
    .click();
  await expect(
    page.getByRole("link", { name: /Review LinkedIn job listing/ }),
  ).toHaveAttribute("href", "https://linkedin.com/jobs/view/1234567890");
  await expect(
    page.getByRole("link", { name: /Review LinkedIn hiring post/ }),
  ).toHaveAttribute("href", "https://linkedin.com/posts/fixture-hiring");
  await expect(
    page.locator(".linkedin-lead strong").filter({ hasText: "Python" }),
  ).toBeVisible();
  await page
    .locator("nav")
    .getByRole("button", { name: /Opportunities/ })
    .click();
  await expect(
    page.getByRole("link", { name: /Review company \/ careers page/ }).first(),
  ).toBeVisible();
  const logs = await (
    await context.request.get(origin + "/api/backend/admin/audit")
  ).json();
  expect(logs.length).toBeGreaterThan(1);
  expect(
    (
      await context.request.delete(origin + "/api/session", {
        headers: { origin },
      })
    ).status(),
  ).toBe(200);
  console.log(
    JSON.stringify({
      administrator_login: true,
      imported_workspace_access: true,
      existing_candidates: candidates.length,
      visible_jobs: jobs,
      existing_resumes: resumes,
      audit_recorded: true,
      recent_linkedin_view: true,
      source_labels_and_review_links: true,
      session_revoked: true,
    }),
  );
} finally {
  await context.request.delete(origin + "/api/session", {
    headers: { origin },
  });
  await browser.close();
}
