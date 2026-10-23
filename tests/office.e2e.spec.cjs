/* Real Chromium/Playwright smoke against a strictly loopback-only
 * fixture that reuses the production Flask template and JS. No GCP,
 * GitHub token, Webull sandbox, AI API or trading credentials are used.
 */
const { test, expect } = require("@playwright/test");

test.use({ baseURL: "http://127.0.0.1:18765" });

test("seven official roles, verified stages and conversations render", async ({page}) => {
  await page.goto("/office");
  await expect(page.getByRole("heading", {name: /the agent office/i})).toBeVisible();
  await expect(page.locator("#office-world")).toBeVisible();
  await expect(page.locator("#agent-roster .agent-btn")).toHaveCount(7);
  await expect(page.locator("#agent-name")).toHaveText("Maya");
  await expect(page.locator("#agent-state")).toHaveText("WORKING");
  await expect(page.locator("#conversation-feed")).toContainText(
    "Offline test-only research message", {timeout: 15000});
  await page.locator('#agent-roster .agent-btn[data-name="Sage"]').click();
  await expect(page.locator("#agent-name")).toHaveText("Sage");
  await expect(page.locator("#agent-state")).toHaveText("FAILED");
  await page.locator('#agent-roster .agent-btn[data-name="Theo"]').click();
  await expect(page.locator("#agent-state")).toHaveText("DONE");
  await expect(page.locator("#research-consensus")).toContainText("NO_CONSENSUS");
});

test("animations can be paused without changing agent run evidence", async ({page}) => {
  await page.goto("/office");
  await expect(page.locator("#motion-toggle")).toHaveAttribute("aria-pressed", "true");
  await page.locator("#motion-toggle").click();
  await expect(page.locator("#motion-toggle")).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator("#agent-roster .agent-btn")).toHaveCount(7);
  await expect(page.locator("#agent-state")).toHaveText("WORKING");
  await page.locator("#zoom-in").click();
  await expect(page.locator("#zoom-level")).not.toHaveText("100%");
});

test("no exposed order forms or credentials in browser status payload", async ({page}) => {
  await page.goto("/office");
  const response = await page.request.get("/office/status");
  expect(response.status()).toBe(200);
  const data = await response.json();
  expect(data.roles).toHaveLength(7);
  expect(data.conversation.available).toBeTruthy();
  expect(data.run.run_id).toBe(12345);
  const serialized = JSON.stringify(data).toLowerCase();
  for (const secret of ["api_secret", "access_token", "account_id", "order_payload"]) {
    expect(serialized).not.toContain(secret);
  }
  expect(await page.locator('form[action*="order"]').count()).toBe(0);
});
