import { GamePage } from '../pages/game/GamePage';

export function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Battleship</h1>
        <p>Game screen (MVP)</p>
      </header>
      <main>
        <GamePage />
      </main>
    </div>
  );
}
