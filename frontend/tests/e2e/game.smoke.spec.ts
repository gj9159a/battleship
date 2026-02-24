import { expect, test } from '@playwright/test';

test('game screen smoke', async ({ page }) => {
  await page.route('**/api/v1/health', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ok',
        service: 'battleship-backend',
        ts: '2026-02-24T00:00:00+00:00',
      }),
    });
  });

  await page.route('**/api/v1/rulesets', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'classic_v1',
          name: 'Classic Battleship v1',
          board_size: 10,
          fleet: [5, 4, 3, 3, 2],
          placement_no_touch: false,
          extra_turn_on_hit: true,
        },
      ]),
    });
  });

  await page.route('**/api/v1/game/sessions', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'smoke-session',
        ruleset_id: 'classic_v1',
        lifecycle_state: 'running',
        current_player: 0,
        winner: null,
        shots: [],
      }),
    });
  });

  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Морской бой' })).toBeVisible();
  await expect(page.getByText('Готово к старту.')).toBeVisible();

  await page.getByRole('button', { name: 'Начать игру' }).click();
  await expect(page.getByTestId('session-id')).toContainText('smoke-session');
});
