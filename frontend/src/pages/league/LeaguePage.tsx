import { useEffect, useMemo, useState } from 'react';

import {
  commandLeagueSeason,
  connectEvents,
  createLeagueSeason,
  getLeagueMatchupMatrix,
  getLeagueSeason,
  getLeagueTable,
  getBotVersions,
  getRulesets,
  recordLeagueMatch,
  registerLeagueBot,
} from '../../shared/api/client';
import type {
  EventEnvelope,
  LeagueMatrixCellDTO,
  LeaguePoolType,
  LeagueRatingDTO,
  LeagueSeasonDTO,
  RulesetDTO,
} from '../../shared/api/types';

function toNumber(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function LeaguePage() {
  const [rulesets, setRulesets] = useState<RulesetDTO[]>([]);
  const [selectedRulesetId, setSelectedRulesetId] = useState('classic_v1');

  const [table, setTable] = useState<LeagueRatingDTO[]>([]);
  const [matrix, setMatrix] = useState<LeagueMatrixCellDTO[]>([]);
  const [botWeightsById, setBotWeightsById] = useState<Record<string, Record<string, number>>>({});
  const [season, setSeason] = useState<LeagueSeasonDTO | null>(null);

  const [botVersionId, setBotVersionId] = useState('');
  const [poolType, setPoolType] = useState<LeaguePoolType>('active');
  const [seedInput, setSeedInput] = useState('3');
  const [maxMatchesInput, setMaxMatchesInput] = useState('500');
  const [microbatchInput, setMicrobatchInput] = useState('10');

  const [statusText, setStatusText] = useState('Загрузка профилей правил...');
  const [errorText, setErrorText] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [eventLines, setEventLines] = useState<string[]>([]);

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
        setStatusText('Готово к работе с лигой.');
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
  }, [selectedRulesetId]);

  async function refreshLeagueData(rulesetId: string): Promise<void> {
    const [rows, cells, bots] = await Promise.all([
      getLeagueTable(rulesetId),
      getLeagueMatchupMatrix(rulesetId),
      getBotVersions({ ruleset_id: rulesetId }),
    ]);
    setTable(rows);
    setMatrix(cells);
    const mapped: Record<string, Record<string, number>> = {};
    for (const bot of bots) {
      mapped[bot.bot_version_id] = bot.weights;
    }
    setBotWeightsById(mapped);
  }

  function botWeightsTooltip(botVersionId: string): string {
    const weights = botWeightsById[botVersionId];
    if (!weights) {
      return 'Веса недоступны';
    }
    return Object.entries(weights)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, value]) => `${key}=${value.toFixed(3)}`)
      .join('\n');
  }

  useEffect(() => {
    if (!selectedRulesetId) {
      return;
    }
    void refreshLeagueData(selectedRulesetId).catch(() => {
      // Ignore initial refresh errors; keep previous UI.
    });
  }, [selectedRulesetId]);

  useEffect(() => {
    if (!season) {
      return;
    }

    const activeStates = new Set(['Running', 'Pausing', 'Stopping']);
    if (!activeStates.has(season.lifecycle_state)) {
      return;
    }

    const timer = window.setInterval(() => {
      void getLeagueSeason(season.id)
        .then((fresh) => setSeason(fresh))
        .catch(() => {
          // No-op.
        });
      void refreshLeagueData(season.ruleset_id).catch(() => {
        // No-op.
      });
    }, 450);

    return () => {
      window.clearInterval(timer);
    };
  }, [season]);

  useEffect(() => {
    const stop = connectEvents((event: EventEnvelope) => {
      if (event.ruleset_id !== selectedRulesetId) {
        return;
      }

      if (event.event_type.startsWith('league.')) {
        setEventLines((prev) => [`${event.event_type} #${event.seq}`, ...prev].slice(0, 25));
      }

      if (event.event_type === 'league.match_finished' || event.event_type === 'league.rating_updated') {
        void refreshLeagueData(selectedRulesetId).catch(() => {
          // No-op.
        });
      }

      if (season && event.event_type === 'league.lifecycle_changed' && event.entity_id === season.id) {
        void getLeagueSeason(season.id)
          .then((fresh) => setSeason(fresh))
          .catch(() => {
            // No-op.
          });
      }
    });

    return () => {
      stop?.();
    };
  }, [selectedRulesetId, season]);

  const canPause = season?.lifecycle_state === 'Running';
  const canResume = season?.lifecycle_state === 'Paused';
  const canStop = season ? ['Running', 'Pausing', 'Paused'].includes(season.lifecycle_state) : false;

  const top16 = useMemo(() => table.filter((row) => row.pool_type === 'league').slice(0, 16), [table]);
  const topMatchupsByGames = useMemo(
    () =>
      [...matrix]
        .sort(
          (left, right) =>
            right.total - left.total ||
            right.wins_a + right.wins_b - (left.wins_a + left.wins_b) ||
            left.bot_a_id.localeCompare(right.bot_a_id) ||
            left.bot_b_id.localeCompare(right.bot_b_id),
        )
        .slice(0, 50),
    [matrix],
  );

  async function onRegisterBot() {
    if (!botVersionId || isBusy) {
      return;
    }

    setIsBusy(true);
    setErrorText(null);

    try {
      await registerLeagueBot(selectedRulesetId, botVersionId.trim(), poolType);
      await refreshLeagueData(selectedRulesetId);
      setStatusText(`Бот ${botVersionId} добавлен в пул ${poolType}.`);
      setBotVersionId('');
    } catch (error) {
      setErrorText((error as Error).message);
      setStatusText('Ошибка регистрации бота.');
    } finally {
      setIsBusy(false);
    }
  }

  async function onCreateSeason() {
    if (isBusy) {
      return;
    }

    setIsBusy(true);
    setErrorText(null);

    try {
      const created = await createLeagueSeason({
        ruleset_id: selectedRulesetId,
        seed: toNumber(seedInput, 0),
        max_matches: toNumber(maxMatchesInput, 500),
        microbatch_size: toNumber(microbatchInput, 10),
      });
      setSeason(created);
      setStatusText(`Сезон ${created.id} создан.`);
    } catch (error) {
      setErrorText((error as Error).message);
      setStatusText('Ошибка создания сезона.');
    } finally {
      setIsBusy(false);
    }
  }

  async function onCommandSeason(command: 'start' | 'pause' | 'resume' | 'stop') {
    if (!season || isBusy) {
      return;
    }

    setIsBusy(true);
    setErrorText(null);

    try {
      const updated = await commandLeagueSeason(season.id, command);
      setSeason(updated);
      setStatusText(`Команда ${command} отправлена для сезона ${season.id}.`);
    } catch (error) {
      setErrorText((error as Error).message);
      setStatusText(`Ошибка команды ${command}.`);
    } finally {
      setIsBusy(false);
    }
  }

  async function onQuickMatch() {
    if (table.length < 2 || isBusy) {
      return;
    }

    setIsBusy(true);
    setErrorText(null);

    try {
      await recordLeagueMatch({
        ruleset_id: selectedRulesetId,
        bot_a_id: table[0].bot_version_id,
        bot_b_id: table[1].bot_version_id,
        winner_id: table[0].bot_version_id,
      });
      await refreshLeagueData(selectedRulesetId);
      setStatusText('Быстрый матч сыгран.');
    } catch (error) {
      setErrorText((error as Error).message);
      setStatusText('Ошибка быстрого матча.');
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <section className="screen-layout">
      <aside className="panel controls">
        <h2>Лига</h2>

        <label>
          Профиль правил
          <select value={selectedRulesetId} onChange={(event) => setSelectedRulesetId(event.target.value)}>
            {rulesets.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.id})
              </option>
            ))}
          </select>
        </label>

        <label>
          ID версии бота
          <input
            aria-label="ID версии бота"
            value={botVersionId}
            onChange={(event) => setBotVersionId(event.target.value)}
            placeholder="candidate-001"
          />
        </label>

        <label>
          Пул
          <select value={poolType} onChange={(event) => setPoolType(event.target.value as LeaguePoolType)}>
            <option value="active">active (кандидаты)</option>
            <option value="baseline">baseline (базовые)</option>
            <option value="league">league (лига)</option>
          </select>
        </label>

        <button type="button" onClick={onRegisterBot} disabled={isBusy || !botVersionId.trim()}>
          Зарегистрировать бота
        </button>

        <hr className="divider" />

        <label>
          Seed сезона
          <input value={seedInput} onChange={(event) => setSeedInput(event.target.value)} />
        </label>

        <label>
          Макс. матчей
          <input value={maxMatchesInput} onChange={(event) => setMaxMatchesInput(event.target.value)} />
        </label>

        <label>
          Микробатч
          <input value={microbatchInput} onChange={(event) => setMicrobatchInput(event.target.value)} />
        </label>

        <button type="button" onClick={onCreateSeason} disabled={isBusy}>
          Создать сезон
        </button>

        <div className="button-row">
          <button type="button" onClick={() => onCommandSeason('start')} disabled={isBusy || !season || season.lifecycle_state !== 'Idle'}>
            Старт
          </button>
          <button type="button" onClick={() => onCommandSeason('pause')} disabled={!canPause || isBusy}>
            Пауза
          </button>
          <button type="button" onClick={() => onCommandSeason('resume')} disabled={!canResume || isBusy}>
            Продолжить
          </button>
          <button type="button" onClick={() => onCommandSeason('stop')} disabled={!canStop || isBusy}>
            Стоп
          </button>
        </div>

        <button type="button" onClick={onQuickMatch} disabled={isBusy || table.length < 2}>
          Быстрый матч top-2
        </button>

        <div className="status" data-testid="league-status-text">
          {statusText}
        </div>

        {season && (
          <div data-testid="league-season-id">
            Сезон: {season.id}
            <br />
            Жизненный цикл: {season.lifecycle_state}
            <br />
            Матчей сыграно: {season.matches_done}/{season.max_matches}
            <br />
            Причина остановки: {season.stop_reason ?? '-'}
          </div>
        )}

        {errorText && <div role="alert">{errorText}</div>}
      </aside>

      <div className="screen-content">
        <section className="panel">
          <h3>Топ-16 (по mu-3*sigma)</h3>
          <table className="data-table" data-testid="league-table">
            <thead>
              <tr>
                <th>Бот</th>
                <th>Пул</th>
                <th>mu</th>
                <th>sigma</th>
                <th>mu-3σ</th>
                <th>Матчи</th>
                <th>Винрейт</th>
              </tr>
            </thead>
            <tbody>
              {top16.map((row) => (
                <tr key={row.bot_version_id}>
                  <td title={botWeightsTooltip(row.bot_version_id)}>{row.bot_version_id}</td>
                  <td>{row.pool_type}</td>
                  <td>{row.mu.toFixed(3)}</td>
                  <td>{row.sigma.toFixed(3)}</td>
                  <td>{row.conservative_score.toFixed(3)}</td>
                  <td>{row.matches_played}</td>
                  <td>{(row.winrate * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="panel">
          <h3>Матрица матчапов (топ-50 по числу игр)</h3>
          <table className="data-table" data-testid="league-matrix-table">
            <thead>
              <tr>
                <th>Бот A</th>
                <th>Бот B</th>
                <th>Побед A</th>
                <th>Побед B</th>
                <th>Всего</th>
              </tr>
            </thead>
            <tbody>
              {topMatchupsByGames.map((cell) => (
                <tr key={`${cell.bot_a_id}-${cell.bot_b_id}`}>
                  <td>{cell.bot_a_id}</td>
                  <td>{cell.bot_b_id}</td>
                  <td>{cell.wins_a}</td>
                  <td>{cell.wins_b}</td>
                  <td>{cell.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="panel">
          <h3>События</h3>
          <ul className="event-list" data-testid="league-events-list">
            {eventLines.map((line, index) => (
              <li key={`${line}-${index}`}>{line}</li>
            ))}
          </ul>
        </section>
      </div>
    </section>
  );
}
