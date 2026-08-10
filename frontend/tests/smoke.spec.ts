import { test, expect } from "@playwright/test";

/**
 * Basic smoke test: the app shell boots and the auth/login page renders.
 * No backend or real Supabase is required — this guards against blank
 * renders / build breakage, not full behavior.
 */
test("login page renders the CloudPulse branding", async ({ page }) => {
  await page.goto("/login");
  await expect(
    page.getByRole("heading", { name: "CloudPulse AI" })
  ).toBeVisible();
  await expect(page.getByText("Sign in to continue")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create an account" })
  ).toBeVisible();
});

test("app shell serves HTTP 200 on /", async ({ page }) => {
  const res = await page.goto("/");
  expect(res?.status()).toBe(200);
  await expect(page.locator("body")).toBeVisible();
});
