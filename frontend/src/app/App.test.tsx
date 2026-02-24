import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { App } from './App';

vi.mock('./components/BackendStatusBar', () => ({
  BackendStatusBar: () => <div>BackendStatus</div>,
}));

vi.mock('../pages/game/GamePage', () => ({
  GamePage: () => <div>GamePage</div>,
}));

vi.mock('../pages/league/LeaguePage', () => ({
  LeaguePage: () => <div>LeaguePage</div>,
}));

vi.mock('../pages/rulesets/RulesetsPage', () => ({
  RulesetsPage: () => <div>RulesetsPage</div>,
}));

vi.mock('../pages/bots/BotsPage', () => ({
  BotsPage: () => <div>BotsPage</div>,
}));

vi.mock('../pages/training/TrainingPage', () => ({
  TrainingPage: () => {
    const [value, setValue] = useState('');
    return (
      <label>
        training-local
        <input
          aria-label="training-local"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      </label>
    );
  },
}));

describe('App', () => {
  it('keeps training page state after tab switch', () => {
    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: 'Тренировка' }));
    const input = screen.getByLabelText('training-local');
    fireEvent.change(input, { target: { value: 'persist-me' } });

    fireEvent.click(screen.getByRole('button', { name: 'Лига' }));
    fireEvent.click(screen.getByRole('button', { name: 'Тренировка' }));

    expect(screen.getByLabelText('training-local')).toHaveValue('persist-me');
  });
});
