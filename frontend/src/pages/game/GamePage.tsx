import { useEffect, useMemo, useState } from 'react';

import { createGameSession, getGameSession, getRulesets, shoot } from '../../shared/api/client';
import type { GameSessionDTO, RulesetDTO, ShotDTO } from '../../shared/api/types';
import { shipCells } from './placementTemplates';

function cellKey(row: number, col: number): string {
  return `${row}:${col}`;
}

export function GamePage() {
  const [rulesets, setRulesets] = useState<RulesetDTO[]>([]);
  const [selectedRulesetId, setSelectedRulesetId] = useState('classic_v1');
  const [session, setSession] = useState<GameSessionDTO | null>(null);
  const [statusText, setStatusText] = useState('Загрузка профилей правил...');
  const [isBusy, setIsBusy] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    getRulesets()
      .then((items) => {
        if (!mounted) {
          return;
        }
        setRulesets(items);
        if (items.length > 0 && !items.some((item) => item.id === selectedRulesetId)) {
          setSelectedRulesetId(items[0].id);
        }
        setStatusText('Готово к старту.');
      })
      .catch((error: Error) => {
        if (mounted) {
          setErrorText(error.message);
          setStatusText('Не удалось загрузить профили правил.');
        }
      });

    return () => {
      mounted = false;
    };
  }, []);

  const playerShips = useMemo(() => shipCells(session?.player_placements ?? []), [session?.player_placements]);

  const shotIndex = useMemo(() => {
    const map = new Map<string, ShotDTO>();
    for (const shot of session?.shots ?? []) {
      map.set(`${shot.target}:${shot.row}:${shot.col}`, shot);
    }
    return map;
  }, [session]);

  const playerShotSet = useMemo(() => {
    const set = new Set<string>();
    for (const shot of session?.shots ?? []) {
      if (shot.shooter === 0) {
        set.add(cellKey(shot.row, shot.col));
      }
    }
    return set;
  }, [session]);

  const isPlayerTurn = session?.current_player === 0 && session.lifecycle_state === 'running';

  async function reloadSession(sessionId: string) {
    const fresh = await getGameSession(sessionId);
    setSession(fresh);
    return fresh;
  }

  async function onStartGame() {
    if (isBusy) {
      return;
    }

    try {
      setIsBusy(true);
      setErrorText(null);
      const created = await createGameSession({
        ruleset_id: selectedRulesetId,
      });
      setSession(created);
      if (created.current_player === 1) {
        await runOpponentTurns(created);
      } else {
        setStatusText('Игра началась. Ход игрока.');
      }
    } catch (error) {
      setErrorText((error as Error).message);
      setStatusText('Ошибка старта игры.');
    } finally {
      setIsBusy(false);
    }
  }

  async function runOpponentTurns(current: GameSessionDTO) {
    let latest = current;
    setStatusText('Ход бота...');

    while (latest.current_player === 1 && latest.lifecycle_state === 'running') {
      const attempt = await shoot(latest.id, 0, 0);
      latest = await reloadSession(latest.id);
      if (attempt.game_over) {
        break;
      }
    }

    if (latest.lifecycle_state === 'completed') {
      setStatusText(latest.winner === 0 ? 'Победа игрока.' : 'Победа бота.');
      return;
    }
    setStatusText('Ход игрока.');
  }

  async function onPlayerShot(row: number, col: number) {
    if (!session || !isPlayerTurn || isBusy) {
      return;
    }

    if (playerShotSet.has(cellKey(row, col))) {
      return;
    }

    try {
      setIsBusy(true);
      const result = await shoot(session.id, row, col);
      const fresh = await reloadSession(session.id);

      if (result.game_over) {
        setStatusText(fresh.winner === 0 ? 'Победа игрока.' : 'Победа бота.');
        return;
      }

      if (fresh.current_player === 1) {
        await runOpponentTurns(fresh);
      } else {
        setStatusText('Ход игрока.');
      }
    } catch (error) {
      setErrorText((error as Error).message);
      setStatusText('Ошибка при выстреле.');
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <section className="game-layout">
      <aside className="panel controls">
        <label>
          Профиль правил
          <select
            aria-label="Профиль правил"
            value={selectedRulesetId}
            onChange={(event) => setSelectedRulesetId(event.target.value)}
            disabled={isBusy}
          >
            {rulesets.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.id})
              </option>
            ))}
          </select>
        </label>

        <button type="button" onClick={onStartGame} disabled={isBusy || rulesets.length === 0}>
          Начать игру
        </button>

        <div className="status" data-testid="status-text">
          {statusText}
        </div>

        {session && <div data-testid="session-id">Сессия: {session.id}</div>}

        {errorText && <div role="alert">{errorText}</div>}

        <div>
          <h3>События</h3>
          <ul className="event-list" data-testid="events-list">
            {(session?.shots ?? []).map((shot, index) => (
              <li key={`${shot.shooter}-${shot.target}-${shot.row}-${shot.col}-${index}`}>
                {`p${shot.shooter} -> (${shot.row},${shot.col}) = ${shot.outcome}`}
              </li>
            ))}
          </ul>
        </div>
      </aside>

      <div className="boards">
        <section className="panel">
          <h3>Поле игрока</h3>
          <div className="board" data-testid="player-board">
            {Array.from({ length: 10 * 10 }).map((_, idx) => {
              const row = Math.floor(idx / 10);
              const col = idx % 10;
              const shot = shotIndex.get(`0:${row}:${col}`);
              const classes = ['cell'];

              if (playerShips.has(cellKey(row, col))) {
                classes.push('ship');
              }
              if (shot) {
                classes.push(shot.outcome);
              }

              return <div key={`player-${row}-${col}`} className={classes.join(' ')} />;
            })}
          </div>
        </section>

        <section className="panel">
          <h3>Поле противника</h3>
          <div className="board" data-testid="enemy-board">
            {Array.from({ length: 10 * 10 }).map((_, idx) => {
              const row = Math.floor(idx / 10);
              const col = idx % 10;
              const shot = shotIndex.get(`1:${row}:${col}`);
              const classes = ['cell'];

              if (shot) {
                classes.push(shot.outcome);
              }
              if (!shot && isPlayerTurn && !isBusy) {
                classes.push('targetable');
              }

              return (
                <button
                  key={`enemy-${row}-${col}`}
                  type="button"
                  className={classes.join(' ')}
                  onClick={() => onPlayerShot(row, col)}
                  disabled={!isPlayerTurn || Boolean(shot) || isBusy}
                  aria-label={`клетка-противника-${row}-${col}`}
                />
              );
            })}
          </div>
        </section>
      </div>
    </section>
  );
}
