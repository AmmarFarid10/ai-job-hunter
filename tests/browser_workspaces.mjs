import {
  chromium,
  expect,
} from "../dashboard/node_modules/@playwright/test/index.mjs";
import { randomUUID } from "node:crypto";
const origin = "http://localhost:3001",
  key = "browser-test-key-at-least-thirty-two-characters";
const browser = await chromium.launch({
  channel: process.env.BROWSER_CHANNEL || "chrome",
  headless: true,
});
const errors = [];
async function signup(name) {
  const context = await browser.newContext(),
    page = await context.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(origin);
  await page.getByRole("button", { name: "Sign up", exact: true }).click();
  await expect(page.getByLabel("Workspace setup key")).toHaveCount(0);
  await page.getByLabel("Your name", { exact: true }).fill(name);
  await page
    .getByLabel("Email", { exact: true })
    .fill(`${randomUUID()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("fictional-browser-password");
  await page.getByRole("button", { name: /^Create workspace account/ }).click();
  await expect(
    page.getByRole("heading", { name: "Your search, in focus." }),
  ).toBeVisible();
  const session = await (
    await context.request.get(origin + "/api/session")
  ).json();
  expect(session.user.role).toBe("USER");
  return { context, page, user: session.user };
}
try {
  const first = await signup("Browser Admin"),
    second = await signup("Private Browser User");
  const created = await second.context.request.post(
    origin + "/api/backend/candidates",
    { headers: { origin }, data: { name: "User Two Private Profile" } },
  );
  expect(created.status()).toBe(201);
  const candidate = (await created.json()).id;
  expect(
    (
      await first.context.request.get(origin + "/api/backend/candidates")
    ).status(),
  ).toBe(200);
  expect(
    await (
      await first.context.request.get(origin + "/api/backend/candidates")
    ).json(),
  ).toEqual([]);
  expect(
    (
      await first.context.request.get(
        origin + "/api/backend/candidates/" + candidate,
      )
    ).status(),
  ).toBe(404);
  expect(
    (
      await second.context.request.post(origin + "/api/workspace", {
        headers: { origin },
        data: { account_id: first.user.id },
      })
    ).status(),
  ).toBe(403);
  await first.page
    .locator("nav")
    .getByRole("button", { name: /Administration/ })
    .click();
  await first.page.getByLabel("Administrator setup key").fill(key);
  await first.page
    .getByRole("button", { name: "Make my account administrator" })
    .click();
  await expect(
    first.page.getByRole("heading", { name: "Your search, in focus." }),
  ).toBeVisible();
  await first.page
    .locator("nav")
    .getByRole("button", { name: /Administration/ })
    .click();
  const row = first.page.getByRole("row").filter({
    has: first.page.getByRole("cell", {
      name: second.user.email,
      exact: true,
    }),
  });
  await row
    .getByRole("button", { name: "View workspace", exact: true })
    .click();
  await expect(
    first.page.getByRole("status").filter({ hasText: "Administrator view" }),
  ).toBeVisible();
  expect(
    (await first.context.cookies()).find(
      (c) => c.name === "job_hunter_workspace",
    )?.httpOnly,
  ).toBe(true);
  await expect(
    first.page.getByRole("combobox", { name: "Candidate", exact: true }),
  ).toHaveValue(candidate);
  expect(
    (
      await first.context.request.get(
        origin + "/api/backend/candidates/" + candidate,
      )
    ).status(),
  ).toBe(200);
  const audit = await (
    await first.context.request.get(origin + "/api/backend/admin/audit")
  ).json();
  expect(audit.some((e) => e.target_account_id === second.user.id)).toBe(true);
  await first.page
    .getByRole("button", { name: "Return to my workspace", exact: true })
    .click();
  await expect(
    first.page.getByRole("status").filter({ hasText: "Administrator view" }),
  ).toHaveCount(0);
  await expect(
    first.page.getByRole("heading", { name: "Your search, in focus." }),
  ).toBeVisible();
  expect(
    await (
      await first.context.request.get(origin + "/api/backend/candidates")
    ).json(),
  ).toEqual([]);
  await first.page
    .getByRole("button", { name: "Sign out", exact: true })
    .click();
  expect(
    (await first.context.cookies()).some(
      (c) => c.name === "job_hunter_workspace",
    ),
  ).toBe(false);
  expect(errors).toEqual([]);
  console.log(
    "Browser workspace checks passed: public signup, private profiles, denied cross-user access, protected admin setup, workspace selector, HttpOnly scope cookie, audit history and return to own workspace.",
  );
} finally {
  await browser.close();
}
