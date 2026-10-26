import {
  chromium,
  expect,
} from "../dashboard/node_modules/@playwright/test/index.mjs";
const origin = "http://localhost:3001";
const browser = await chromium.launch({
  channel: process.env.BROWSER_CHANNEL || "chrome",
  headless: true,
});
try {
  const context = await browser.newContext(),
    page = await context.newPage();
  const failures = [];
  page.on("pageerror", (e) => failures.push(e.message));
  await page.route("**/api/session", async (route) => {
    if (route.request().method() === "GET")
      return route.fulfill({
        json: {
          authenticated: false,
          signup_available: true,
          google_available: false,
          password_recovery_available: true,
        },
      });
    return route.continue();
  });
  await page.goto(origin);
  await page
    .getByRole("button", { name: "Forgot password?", exact: true })
    .click();
  await page
    .getByLabel("Email", { exact: true })
    .fill("fictional-recovery@example.com");
  await page
    .getByRole("button", { name: "Send email link", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("If the account exists");
  // A link fragment is removed from the address bar before the action is submitted.
  const token = "fictional-one-time-link-with-at-least-thirty-two-characters";
  await page.goto(origin + "/#reset=" + token);
  await expect(
    page.getByRole("heading", { name: "Choose a new password" }),
  ).toBeVisible();
  expect(page.url()).not.toContain(token);
  await page
    .getByLabel("New password", { exact: true })
    .fill("fictional-updated-password");
  await page
    .getByLabel("Confirm new password", { exact: true })
    .fill("different-fictional-password");
  await page
    .getByRole("button", { name: "Save new password", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Passwords do not match" }),
  ).toContainText("Passwords do not match");
  await page
    .getByLabel("Confirm new password", { exact: true })
    .fill("fictional-updated-password");
  await page.route("**/api/account", (route) =>
    route.fulfill({
      json: { detail: "Password reset. Sign in with your new password" },
    }),
  );
  await page
    .getByRole("button", { name: "Save new password", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Password reset");
  await page.goto(origin + "/#verify=" + token);
  await expect(
    page.getByRole("heading", { name: "Confirm email verification" }),
  ).toBeVisible();
  expect(page.url()).not.toContain(token);
  await page.unroute("**/api/account");
  await page.route("**/api/account", (route) =>
    route.fulfill({ json: { detail: "Email verified. Sign in to continue" } }),
  );
  await page.getByRole("button", { name: "Verify email", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Email verified");
  await page.unroute("**/api/session");
  await page.route("**/api/session", (route) =>
    route.fulfill({
      json: {
        authenticated: true,
        email_verification_required: true,
        user: {
          email: "fictional-pending@example.com",
          email_verified: false,
          role: "USER",
        },
      },
    }),
  );
  await page.goto(origin + "/?verification-gate-check=1");
  await expect(
    page.getByRole("heading", { name: "Verify your email", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(0);
  expect(failures).toEqual([]);
  console.log(
    "Browser authentication UI passed: recovery request, one-time fragment removal, password mismatch and reset confirmation. Token semantics are verified separately against PostgreSQL.",
  );
} finally {
  await browser.close();
}
