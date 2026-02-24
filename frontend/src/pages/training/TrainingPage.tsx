import { useEffect, useMemo, useState } from 'react';

import {
  commandTrainingJob,
  connectEvents,
  createTrainingJob,
  getRulesets,
  getTrainingCheckpoints,
  getTrainingJob,
  loadTrainingCheckpoint,
} from '../../shared/api/client';
import type {
  EventEnvelope,
  RulesetDTO,
  TrainingCheckpointDTO,
  TrainingJobDTO,
  TrainingParamsDTO,
} from '../../shared/api/types';

const DEFAULT_PARAMS: TrainingParamsDTO = {
  microbatch_size: 20,
  eval_window_batches: 1,
  checkpoint_interval_batches: 5,
  population_size: 16,
  train_split: 0.65,
  worker_count: 12,
  quality_gate_games: 120,
  quality_gate_min_winrate: 0.55,
  quality_gate_min_lower_bound: 0.5,
  target_score: 0.78,
  improvement_delta: 0.01,
  plateau_delta: 0.003,
  plateau_patience_windows: 4,
  early_stop_plateau_windows: 8,
  tick_delay_ms: 10,
};
const SEED_BOT_STORAGE_KEY = 'training.seed_bot_version_id';

type MetricPoint = {
  window: number;
  score: number;
  best: number;
  plateau: number;
};

function toNumber(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function TrainingPage() {
  const [rulesets, setRulesets] = useState<RulesetDTO[]>([]);
  const [selectedRulesetId, setSelectedRulesetId] = useState('classic_v1');
  const [seedInput, setSeedInput] = useState('42');
  const [seedBotVersionId, setSeedBotVersionId] = useState('');
  const [params, setParams] = useState<TrainingParamsDTO>(DEFAULT_PARAMS);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [job, setJob] = useState<TrainingJobDTO | null>(null);
  const [checkpoints, setCheckpoints] = useState<TrainingCheckpointDTO[]>([]);
  const [metrics, setMetrics] = useState<MetricPoint[]>([]);
  const [eventLines, setEventLines] = useState<string[]>([]);
  const [stageReason, setStageReason] = useState<string>('');

  const [statusText, setStatusText] = useState('Загрузка профилей правил...');
  const [errorText, setErrorText] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    const storedSeedBot = window.localStorage.getItem(SEED_BOT_STORAGE_KEY);
    if (storedSeedBot) {
      setSeedBotVersionId(storedSeedBot);
    }
  }, []);

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
        setStatusText('Готово к запуску тренировки.');
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

  async function refreshJob(jobId: string): Promise<TrainingJobDTO> {
    const fresh = await getTrainingJob(jobId);
    setJob(fresh);
    return fresh;
  }

  async function refreshCheckpoints(jobId: string): Promise<void> {
    const items = await getTrainingCheckpoints(jobId);
    setCheckpoints(items);
  }

  useEffect(() => {
    if (!job) {
      return;
    }

    const activeStates = new Set(['Running', 'Pausing', 'Stopping']);
    if (!activeStates.has(job.lifecycle_state)) {
      return;
    }

    const timer = window.setInterval(() => {
      void refreshJob(job.id).catch(() => {
        // Keep previous state on transient polling errors.
      });
      void refreshCheckpoints(job.id).catch(() => {
        // Keep previous checkpoint list on transient polling errors.
      });
    }, 400);

    return () => {
      window.clearInterval(timer);
    };
  }, [job]);

  useEffect(() => {
    if (!job) {
      return;
    }

    const stop = connectEvents((event: EventEnvelope) => {
      if (event.entity_id !== job.id) {
        return;
      }

      setEventLines((prev) => {
        const line = `${event.event_type} #${event.seq}`;
        return [line, ...prev].slice(0, 25);
      });

      if (event.event_type === 'training.stage_changed') {
        const reason = String(event.payload.reason ?? 'unknown');
        setStageReason(reason);
      }

      if (event.event_type === 'training.metrics') {
        const point: MetricPoint = {
          window: Number(event.payload.windows_done ?? 0),
          score: Number(event.payload.score ?? 0),
          best: Number(event.payload.best_score ?? 0),
          plateau: Number(event.payload.plateau_windows ?? 0),
        };
        setMetrics((prev) => [point, ...prev].slice(0, 30));
      }

      if (event.event_type === 'job.lifecycle_changed' || event.event_type === 'training.checkpoint_created') {
        void refreshJob(job.id).catch(() => {
          // No-op.
        });
        void refreshCheckpoints(job.id).catch(() => {
          // No-op.
        });
      }
    });

    return () => {
      stop?.();
    };
  }, [job]);

  const canPause = job?.lifecycle_state === 'Running';
  const canResume = job?.lifecycle_state === 'Paused';
  const canStop = job ? ['Running', 'Pausing', 'Paused'].includes(job.lifecycle_state) : false;

  const latestMetrics = useMemo(() => metrics.slice(0, 10), [metrics]);

  async function onStartTraining() {
    if (isBusy) {
      return;
    }

    setIsBusy(true);
    setErrorText(null);
    setMetrics([]);
    setEventLines([]);
    setCheckpoints([]);
    setStageReason('');

    try {
      const created = await createTrainingJob({
        ruleset_id: selectedRulesetId,
        seed_bot_version_id: seedBotVersionId.trim() || null,
        seed: toNumber(seedInput, 42),
        params,
      });
      const started = await commandTrainingJob(created.id, 'start');
      setJob(started);
      await refreshCheckpoints(started.id);
      setStatusText(`Тренировка запущена (${started.id}).`);
    } catch (error) {
      setErrorText((error as Error).message);
      setStatusText('Ошибка запуска тренировки.');
    } finally {
      setIsBusy(false);
    }
  }

  async function onCommand(command: 'pause' | 'resume' | 'stop') {
    if (!job || isBusy) {
      return;
    }
    setIsBusy(true);
    setErrorText(null);

    try {
      const updated = await commandTrainingJob(job.id, command);
      setJob(updated);
      setStatusText(`Команда ${command} отправлена.`);
    } catch (error) {
      setErrorText((error as Error).message);
      setStatusText(`Ошибка команды ${command}.`);
    } finally {
      setIsBusy(false);
    }
  }

  async function onLoadCheckpoint(checkpointId: string) {
    if (!job || isBusy) {
      return;
    }
    setIsBusy(true);
    setErrorText(null);

    try {
      const loaded = await loadTrainingCheckpoint(job.id, checkpointId);
      setJob(loaded);
      setStatusText(`Чекпоинт ${checkpointId} загружен.`);
    } catch (error) {
      setErrorText((error as Error).message);
      setStatusText('Ошибка загрузки чекпоинта.');
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <section className="screen-layout">
      <aside className="panel controls">
        <h2>Тренировка</h2>

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
          Seed-бот (опционально)
          <input
            aria-label="Seed-бот"
            value={seedBotVersionId}
            onChange={(event) => setSeedBotVersionId(event.target.value)}
            disabled={isBusy}
          />
        </label>

        <label>
          Сид
          <input
            aria-label="Сид"
            value={seedInput}
            onChange={(event) => setSeedInput(event.target.value)}
            disabled={isBusy}
          />
        </label>

        <label>
          Микробатч
          <input
            aria-label="Микробатч"
            value={params.microbatch_size}
            onChange={(event) =>
              setParams((prev) => ({ ...prev, microbatch_size: toNumber(event.target.value, prev.microbatch_size) }))
            }
          />
        </label>

        <label>
          Окно оценки
          <input
            aria-label="Окно оценки"
            value={params.eval_window_batches}
            onChange={(event) =>
              setParams((prev) => ({ ...prev, eval_window_batches: toNumber(event.target.value, prev.eval_window_batches) }))
            }
          />
        </label>

        <label>
          Интервал чекпоинтов
          <input
            aria-label="Интервал чекпоинтов"
            value={params.checkpoint_interval_batches}
            onChange={(event) =>
              setParams((prev) => ({
                ...prev,
                checkpoint_interval_batches: toNumber(event.target.value, prev.checkpoint_interval_batches),
              }))
            }
          />
        </label>

        <button type="button" className="ghost-btn" onClick={() => setShowAdvanced((prev) => !prev)}>
          {showAdvanced ? 'Скрыть расширенные настройки' : 'Показать расширенные настройки'}
        </button>

        {showAdvanced && (
          <div className="advanced-grid">
            <label>
              Популяция
              <input
                aria-label="Популяция"
                value={params.population_size}
                onChange={(event) =>
                  setParams((prev) => ({ ...prev, population_size: toNumber(event.target.value, prev.population_size) }))
                }
              />
            </label>

            <label>
              Доля train
              <input
                aria-label="Доля train"
                value={params.train_split}
                onChange={(event) =>
                  setParams((prev) => ({ ...prev, train_split: toNumber(event.target.value, prev.train_split) }))
                }
              />
            </label>

            <label>
              Число worker
              <input
                aria-label="Число worker"
                value={params.worker_count}
                onChange={(event) =>
                  setParams((prev) => ({ ...prev, worker_count: toNumber(event.target.value, prev.worker_count) }))
                }
              />
            </label>

            <label>
              Игр quality gate
              <input
                aria-label="Игр quality gate"
                value={params.quality_gate_games}
                onChange={(event) =>
                  setParams((prev) => ({
                    ...prev,
                    quality_gate_games: toNumber(event.target.value, prev.quality_gate_games),
                  }))
                }
              />
            </label>

            <label>
              Мин. winrate quality gate
              <input
                aria-label="Мин. winrate quality gate"
                value={params.quality_gate_min_winrate}
                onChange={(event) =>
                  setParams((prev) => ({
                    ...prev,
                    quality_gate_min_winrate: toNumber(event.target.value, prev.quality_gate_min_winrate),
                  }))
                }
              />
            </label>

            <label>
              Мин. нижняя граница quality gate
              <input
                aria-label="Мин. нижняя граница quality gate"
                value={params.quality_gate_min_lower_bound}
                onChange={(event) =>
                  setParams((prev) => ({
                    ...prev,
                    quality_gate_min_lower_bound: toNumber(event.target.value, prev.quality_gate_min_lower_bound),
                  }))
                }
              />
            </label>

            <label>
              Целевой score
              <input
                aria-label="Целевой score"
                value={params.target_score}
                onChange={(event) =>
                  setParams((prev) => ({ ...prev, target_score: toNumber(event.target.value, prev.target_score) }))
                }
              />
            </label>

            <label>
              Порог улучшения
              <input
                aria-label="Порог улучшения"
                value={params.improvement_delta}
                onChange={(event) =>
                  setParams((prev) => ({
                    ...prev,
                    improvement_delta: toNumber(event.target.value, prev.improvement_delta),
                  }))
                }
              />
            </label>

            <label>
              Порог плато
              <input
                aria-label="Порог плато"
                value={params.plateau_delta}
                onChange={(event) =>
                  setParams((prev) => ({ ...prev, plateau_delta: toNumber(event.target.value, prev.plateau_delta) }))
                }
              />
            </label>

            <label>
              Задержка тика, мс
              <input
                aria-label="Задержка тика"
                value={params.tick_delay_ms}
                onChange={(event) =>
                  setParams((prev) => ({ ...prev, tick_delay_ms: toNumber(event.target.value, prev.tick_delay_ms) }))
                }
              />
            </label>
          </div>
        )}

        <div className="button-row">
          <button type="button" onClick={onStartTraining} disabled={isBusy || rulesets.length === 0}>
            Запустить тренировку
          </button>
          <button type="button" onClick={() => onCommand('pause')} disabled={!canPause || isBusy}>
            Пауза
          </button>
          <button type="button" onClick={() => onCommand('resume')} disabled={!canResume || isBusy}>
            Продолжить
          </button>
          <button type="button" onClick={() => onCommand('stop')} disabled={!canStop || isBusy}>
            Стоп
          </button>
        </div>

        <div className="status" data-testid="training-status-text">
          {statusText}
        </div>
        <div>Лукахед: адаптивный</div>
        <div>Политика: adaptive_v1</div>

        {job && (
          <div data-testid="training-job-id">
            Джоб: {job.id}
            <br />
            Жизненный цикл: {job.lifecycle_state}
            <br />
            Стадия: {job.stage_state ?? '-'}
            <br />
            Seed-бот: {job.seed_bot_version_id ?? '-'}
            <br />
            Причина остановки: {job.stop_reason ?? '-'}
          </div>
        )}

        {errorText && <div role="alert">{errorText}</div>}
      </aside>

      <div className="screen-content">
        <section className="panel">
          <h3>Метрики в реальном времени</h3>
          <table className="data-table" data-testid="training-metrics-table">
            <thead>
                <tr>
                  <th>Окно</th>
                  <th>Счёт</th>
                  <th>Лучший</th>
                  <th>Плато</th>
                </tr>
            </thead>
            <tbody>
              {latestMetrics.map((point) => (
                <tr key={`m-${point.window}-${point.score}`}>
                  <td>{point.window}</td>
                  <td>{point.score.toFixed(4)}</td>
                  <td>{point.best.toFixed(4)}</td>
                  <td>{point.plateau}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {job && (
            <div className="inline-summary">
              Игры: {job.progress.games_played} | Батчи: {job.progress.batches_done} | Лучший:{' '}
              {job.progress.best_score.toFixed(4)}
            </div>
          )}
          {stageReason && <div className="inline-summary">Причина смены стадии: {stageReason}</div>}
          {job && (
            <div className="inline-summary" data-testid="training-weights-summary">
              Лучшие веса: {Object.entries(job.best_weights).map(([key, value]) => `${key}=${value.toFixed(3)}`).join(', ')}
            </div>
          )}
        </section>

        <section className="panel">
          <h3>Чекпоинты</h3>
          <table className="data-table" data-testid="training-checkpoints-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Батчи</th>
                <th>Игры</th>
                <th>Лучший</th>
                <th>Действие</th>
              </tr>
            </thead>
            <tbody>
              {checkpoints.map((checkpoint) => (
                <tr key={checkpoint.checkpoint_id}>
                  <td>{checkpoint.checkpoint_id}</td>
                  <td>{checkpoint.batches_done}</td>
                  <td>{checkpoint.games_played}</td>
                  <td>{checkpoint.best_score.toFixed(4)}</td>
                  <td>
                    <button
                      type="button"
                      className="mini-btn"
                      onClick={() => onLoadCheckpoint(checkpoint.checkpoint_id)}
                      disabled={isBusy || !job || ['Running', 'Pausing', 'Stopping'].includes(job.lifecycle_state)}
                    >
                      Загрузить
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="panel">
          <h3>События</h3>
          <ul className="event-list" data-testid="training-events-list">
            {eventLines.map((line, index) => (
              <li key={`${line}-${index}`}>{line}</li>
            ))}
          </ul>
        </section>
      </div>
    </section>
  );
}
