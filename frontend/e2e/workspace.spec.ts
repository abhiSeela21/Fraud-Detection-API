import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('desktop: guided review, feedback, filters, persistence and API docs', async ({
  page,
  context,
}) => {
  await page.setViewportSize({ width: 1440, height: 1080 });
  await page.goto('/');
  await expect(page.getByText('API connected', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Start guided demo', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Pause feed', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Pause feed', exact: true }).click();
  await expect(page.getByText('Paused', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Resume feed', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Inspect an alert', exact: true })).toBeVisible({
    timeout: 30000,
  });
  await page.getByRole('button', { name: 'Inspect an alert', exact: true }).click();
  await expect(page.getByText('Model probability', { exact: true })).toBeVisible();
  await expect(page.getByText(/not the classifier’s reasoning/)).toBeVisible();
  await page.getByRole('button', { name: 'Fraud', exact: true }).click();
  await expect(page.getByText('Saved: fraud', { exact: true })).toBeVisible();
  await expect(page.getByText('You’ve completed the review loop.', { exact: true })).toBeVisible();
  const cookies = await context.cookies();
  const session = cookies.find((cookie) => cookie.name === 'fraud_session');
  expect(session?.httpOnly).toBe(true);
  expect(await page.evaluate(() => document.cookie)).not.toContain('fraud_session');
  await page.getByRole('button', { name: 'Review', exact: true }).click();
  await expect(page.locator('tbody tr')).toHaveCount(3);
  const accessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
    .analyze();
  expect(
    accessibility.violations.map((value) => ({
      id: value.id,
      example: value.nodes[0]?.failureSummary,
      targets: value.nodes.map((node) => node.target),
    })),
  ).toEqual([]);
  // axe visits focusable content; return the visual evidence to its opening view.
  await page.getByRole('button', { name: 'Review', exact: true }).focus();
  await page.evaluate(() => {
    document.querySelector('.detail-panel')?.scrollTo(0, 0);
    window.scrollTo(0, 0);
  });
  await page.screenshot({ path: 'test-results/workspace-desktop.png', fullPage: true });
  await page.reload();
  await expect(page.getByText(/temporary session was restored/)).toBeVisible();
  await expect(page.locator('tbody tr')).toHaveCount(20);
  const docs = await context.newPage();
  await docs.goto('/api/docs');
  await expect(docs.getByText('Fraud Detection API', { exact: false }).first()).toBeVisible();
  await expect.poll(async () => (await docs.request.get('/api/openapi.json')).status()).toBe(200);
  await docs.close();
});

test('mobile: manual scoring and keyboard-accessible review dialog', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByText('API connected', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Explore on my own' }).click();
  await page.getByRole('button', { name: 'Manual transaction', exact: true }).click();
  await page.getByLabel('Amount (USD)').fill('900.00');
  await page.getByRole('button', { name: 'Score transaction', exact: true }).click();
  await expect(
    page.getByRole('dialog', { name: 'Submit a synthetic transaction' }),
  ).not.toBeVisible();
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await page
    .getByRole('button', { name: /^Inspect transaction / })
    .first()
    .click();
  const detail = page.getByRole('dialog', { name: 'Transaction investigation' });
  await expect(detail).toBeVisible();
  await expect(detail.getByText('$900.00', { exact: true })).toBeVisible();
  await expect(detail.getByText('Model probability', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  const accessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
    .analyze();
  expect(
    accessibility.violations.map((value) => ({
      id: value.id,
      example: value.nodes[0]?.failureSummary,
      targets: value.nodes.map((node) => node.target),
    })),
  ).toEqual([]);
  await detail.getByRole('button', { name: 'Close transaction details' }).focus();
  await detail.evaluate((dialog) => dialog.scrollTo(0, 0));
  await page.screenshot({ path: 'test-results/workspace-mobile.png' });
  await page.keyboard.press('Escape');
  await expect(detail).not.toBeVisible();
  await expect(page.getByRole('button', { name: /^Inspect transaction / }).first()).toBeFocused();
});

test('custom simulations pause on a hidden tab and new runs keep their history', async ({
  page,
}) => {
  await page.goto('/');
  await expect(page.getByText('API connected', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Explore on my own' }).click();
  await page.getByLabel('Spending profile').selectOption('traveler');
  await page.getByRole('combobox', { name: 'Scenario', exact: true }).selectOption('travel');
  await page.getByRole('combobox', { name: 'Events', exact: true }).selectOption('20');
  await page.getByRole('combobox', { name: 'Playback', exact: true }).selectOption('500');
  await page.getByRole('button', { name: 'Start simulation', exact: true }).click();
  await expect.poll(() => page.locator('tbody tr').count()).toBeGreaterThan(0);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(page.getByText('Paused', { exact: true })).toBeVisible();
  const count = await page.locator('tbody tr').count();
  await page.waitForTimeout(1200);
  expect(await page.locator('tbody tr').count()).toBe(count);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  });
  await page.getByRole('button', { name: 'Resume feed', exact: true }).click();
  await expect(page.getByText('Complete', { exact: true })).toBeVisible({ timeout: 30000 });
  await expect(page.locator('tbody tr')).toHaveCount(20);
  await page.getByRole('button', { name: 'Start new run', exact: true }).click();
  await expect.poll(() => page.locator('tbody tr').count()).toBeGreaterThan(20);
  await page.getByRole('button', { name: 'Stop simulation', exact: true }).click();
  await expect(page.getByText('Stopped', { exact: true })).toBeVisible();
});

test('wake-up and unavailable states stay honest', async ({ page }) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: '{"status":"unavailable"}',
    }),
  );
  await page.goto('/');
  await expect(page.getByText('Waking up the scoring API', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Start guided demo', exact: true })).toBeDisabled();
  await expect(page.locator('tbody tr')).toHaveCount(0);
});
