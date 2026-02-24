import { useState } from 'react';

import { BackendStatusBar } from './components/BackendStatusBar';
import { GamePage } from '../pages/game/GamePage';
import { LeaguePage } from '../pages/league/LeaguePage';
import { RulesetsPage } from '../pages/rulesets/RulesetsPage';
import { TrainingPage } from '../pages/training/TrainingPage';

type Screen = 'game' | 'training' | 'league' | 'rulesets';

export function App() {
  const [screen, setScreen] = useState<Screen>('game');

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Battleship</h1>
        <p>Game / Training / League / Rulesets</p>
      </header>

      <nav className="main-nav" aria-label="Main navigation">
        <button
          type="button"
          className={screen === 'game' ? 'nav-btn nav-btn-active' : 'nav-btn'}
          onClick={() => setScreen('game')}
        >
          Game
        </button>
        <button
          type="button"
          className={screen === 'training' ? 'nav-btn nav-btn-active' : 'nav-btn'}
          onClick={() => setScreen('training')}
        >
          Training
        </button>
        <button
          type="button"
          className={screen === 'league' ? 'nav-btn nav-btn-active' : 'nav-btn'}
          onClick={() => setScreen('league')}
        >
          League
        </button>
        <button
          type="button"
          className={screen === 'rulesets' ? 'nav-btn nav-btn-active' : 'nav-btn'}
          onClick={() => setScreen('rulesets')}
        >
          Rulesets
        </button>
      </nav>
      <BackendStatusBar />

      <main>
        {screen === 'game' && <GamePage />}
        {screen === 'training' && <TrainingPage />}
        {screen === 'league' && <LeaguePage />}
        {screen === 'rulesets' && <RulesetsPage />}
      </main>
    </div>
  );
}
