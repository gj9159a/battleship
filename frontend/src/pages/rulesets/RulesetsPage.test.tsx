import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { RulesetsPage } from './RulesetsPage';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('RulesetsPage', () => {
  it('creates and activates ruleset', async () => {
    const rulesets = [
      {
        id: 'classic_v1',
        name: 'Classic Battleship v1',
        board_size: 10,
        fleet: [5, 4, 3, 3, 2],
        placement_no_touch: false,
        extra_turn_on_hit: true,
        is_active: true,
        is_archived: false,
      },
    ];

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? 'GET';

      if (url.endsWith('/api/v1/rulesets?include_archived=true') && method === 'GET') {
        return new Response(JSON.stringify(rulesets), { status: 200 });
      }

      if (url.endsWith('/api/v1/rulesets') && method === 'POST') {
        const body = JSON.parse(String(init?.body));
        const created = {
          ...body,
          is_active: false,
          is_archived: false,
        };
        rulesets.push(created);
        return new Response(JSON.stringify(created), { status: 200 });
      }

      if (url.endsWith('/api/v1/rulesets/dense_v2/activate') && method === 'POST') {
        for (const item of rulesets) {
          item.is_active = item.id === 'dense_v2';
        }
        return new Response(JSON.stringify(rulesets.find((item) => item.id === 'dense_v2')), { status: 200 });
      }

      throw new Error(`Unhandled request: ${url} ${method}`);
    });

    render(<RulesetsPage />);

    await waitFor(() => {
      expect(screen.getByText('Готово к управлению профилями правил.')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Новая форма профиля' }));

    fireEvent.change(screen.getByLabelText('ID профиля правил'), { target: { value: 'dense_v2' } });
    fireEvent.change(screen.getByLabelText('Название профиля правил'), { target: { value: 'Dense v2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));

    await waitFor(() => {
      expect(screen.getByTestId('rulesets-table')).toHaveTextContent('dense_v2');
    });

    fireEvent.click(screen.getByRole('button', { name: 'Активировать' }));

    await waitFor(() => {
      expect(screen.getByTestId('rulesets-status-text')).toHaveTextContent('активирован');
      expect(screen.getByTestId('rulesets-table')).toHaveTextContent('dense_v2');
      expect(screen.getByTestId('rulesets-table')).toHaveTextContent('активен');
    });
  });
});
