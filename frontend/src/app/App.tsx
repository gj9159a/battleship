import { useState } from 'react';

import { BackendStatusBar } from './components/BackendStatusBar';
import { BotsPage } from '../pages/bots/BotsPage';
import { GamePage } from '../pages/game/GamePage';
import { LeaguePage } from '../pages/league/LeaguePage';
import { RulesetsPage } from '../pages/rulesets/RulesetsPage';
import { TrainingPage } from '../pages/training/TrainingPage';

type Screen = 'game' | 'training' | 'league' | 'rulesets' | 'bots';

export function App() {
  const [screen, setScreen] = useState<Screen>('game');

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Морской бой</h1>
        <p>Игра / Тренировка / Лига / Правила / Боты</p>
      </header>

      <nav className="main-nav" aria-label="Основная навигация">
        <button
          type="button"
          className={screen === 'game' ? 'nav-btn nav-btn-active' : 'nav-btn'}
          onClick={() => setScreen('game')}
        >
          Игра
        </button>
        <button
          type="button"
          className={screen === 'training' ? 'nav-btn nav-btn-active' : 'nav-btn'}
          onClick={() => setScreen('training')}
        >
          Тренировка
        </button>
        <button
          type="button"
          className={screen === 'league' ? 'nav-btn nav-btn-active' : 'nav-btn'}
          onClick={() => setScreen('league')}
        >
          Лига
        </button>
        <button
          type="button"
          className={screen === 'rulesets' ? 'nav-btn nav-btn-active' : 'nav-btn'}
          onClick={() => setScreen('rulesets')}
        >
          Правила
        </button>
        <button
          type="button"
          className={screen === 'bots' ? 'nav-btn nav-btn-active' : 'nav-btn'}
          onClick={() => setScreen('bots')}
        >
          Боты
        </button>
      </nav>
      <BackendStatusBar />

      <main>
        {screen === 'game' && <GamePage />}
        {screen === 'training' && <TrainingPage />}
        {screen === 'league' && <LeaguePage />}
        {screen === 'rulesets' && <RulesetsPage />}
        {screen === 'bots' && <BotsPage />}
      </main>
    </div>
  );
}
