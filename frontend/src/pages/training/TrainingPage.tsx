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

const RULESETS_RETRY_DELAY_MS = 1000;
const ACTIVE_JOB_STORAGE_KEY = 'training.active_job_id';
const METRICS_STORAGE_KEY_PREFIX = 'training.metrics.';
const DEFAULT_PARAMS: TrainingParamsDTO = {
  microbatch_size: 100,
  eval_window_batches: 2,
  checkpoint_interval_batches: 50,
  population_size: 32,
  train_split: 0.7,
  worker_count: 12,
  quality_gate_games: 256,
  quality_gate_min_winrate: 0.57,
  quality_gate_min_lower_bound: 0.53,
  target_score: 0.8,
  improvement_delta: 0.008,
  plateau_delta: 0.0015,
  plateau_patience_windows: 8,
  early_stop_plateau_windows: 30,
  min_windows_before_early_stop: 120,
  tick_delay_ms: 0,
  autoevolve_enabled: true,
  meta_plateau_patience_cycles: 3,
  strictness_max_level: 3,
};
const SEED_BOT_STORAGE_KEY = 'training.seed_bot_version_id';

type MetricPoint = {
  batch: number;
  window: number;
  score: number;
  best: number;
  plateau: number;
  cycle: number;
  strictness: number;
};

function buildPolyline(
  points: MetricPoint[],
  valueGetter: (point: MetricPoint) => number,
  width: number,
  height: number,
): string {
  if (points.length === 0) {
    return '';
  }
  const sorted = [...points].sort((left, right) => left.batch - right.batch);
  if (sorted.length === 1) {
    const value = Math.max(0, Math.min(1, valueGetter(sorted[0])));
    const y = height - value * height;
    return `0,${y.toFixed(2)} ${width},${y.toFixed(2)}`;
  }

  const denominator = Math.max(1, sorted.length - 1);
  const coords: string[] = [];
  for (let index = 0; index < sorted.length; index += 1) {
    const point = sorted[index];
    const x = (index / denominator) * width;
    const value = Math.max(0, Math.min(1, valueGetter(point)));
    const y = height - value * height;
    coords.push(`${x.toFixed(2)},${y.toFixed(2)}`);
  }
  return coords.join(' ');
}

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
    let cancelled = false;
    const storedJobId = window.localStorage.getItem(ACTIVE_JOB_STORAGE_KEY);
    if (!storedJobId) {
      return () => {
        cancelled = true;
      };
    }

    const restore = async () => {
      try {
        const restored = await getTrainingJob(storedJobId);
        if (cancelled) {
          return;
        }
        setJob(restored);
        await refreshCheckpoints(restored.id);
        if (cancelled) {
          return;
        }
        const raw = window.localStorage.getItem(`${METRICS_STORAGE_KEY_PREFIX}${restored.id}`);
        if (raw) {
          try {
            const parsed = JSON.parse(raw) as MetricPoint[];
            if (Array.isArray(parsed)) {
              setMetrics(parsed.slice(0, 120));
            }
          } catch {
            window.localStorage.removeItem(`${METRICS_STORAGE_KEY_PREFIX}${restored.id}`);
          }
        }
        setStatusText(`Восстановлена тренировка (${restored.id}).`);
      } catch {
        window.localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
      }
    };

    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const storedSeedBot = window.localStorage.getItem(SEED_BOT_STORAGE_KEY);
    if (storedSeedBot) {
      setSeedBotVersionId(storedSeedBot);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let retryTimerId: number | null = null;

    const loadRulesets = async () => {
      try {
        const items = await getRulesets();
        if (cancelled) {
          return;
        }
        setRulesets(items);
        setErrorText(null);
        setSelectedRulesetId((prev) => {
          if (items.length === 0) {
            return prev;
          }
          return items.some((item) => item.id === prev) ? prev : items[0].id;
        });
        setStatusText(items.length > 0 ? 'Готово к запуску тренировки.' : 'Нет доступных профилей правил.');
      } catch (error) {
        if (cancelled) {
          return;
        }
        setErrorText((error as Error).message);
        setStatusText('Не удалось загрузить профили правил. Повторяем...');
        retryTimerId = window.setTimeout(() => {
          retryTimerId = null;
          void loadRulesets();
        }, RULESETS_RETRY_DELAY_MS);
      }
    };

    void loadRulesets();

    return () => {
      cancelled = true;
      if (retryTimerId !== null) {
        window.clearTimeout(retryTimerId);
      }
    };
  }, []);

  useEffect(() => {
    if (!job) {
      return;
    }
    window.localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, job.id);
    if (['Stopped', 'Completed', 'Error'].includes(job.lifecycle_state)) {
      window.localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
    }
  }, [job]);

  async function refreshJob(jobId: string): Promise<TrainingJobDTO> {
    const fresh = await getTrainingJob(jobId);
    setJob(fresh);
    return fresh;
  }

  async function refreshCheckpoints(jobId: string): Promise<void> {
    const items = await getTrainingCheckpoints(jobId);
    setCheckpoints(items);
  }

  function upsertMetric(point: MetricPoint, jobId: string) {
    setMetrics((prev) => {
      const merged = [point, ...prev.filter((item) => item.batch !== point.batch)]
        .sort((left, right) => right.batch - left.batch)
        .slice(0, 120);
      window.localStorage.setItem(`${METRICS_STORAGE_KEY_PREFIX}${jobId}`, JSON.stringify(merged));
      return merged;
    });
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
        const gamesPlayed = Number(event.payload.games_played ?? 0);
        const batchesDone = Number(event.payload.batches_done ?? 0);
        const windowsDone = Number(event.payload.windows_done ?? 0);
        const score = Number(event.payload.score ?? 0);
        const bestScore = Number(event.payload.best_score ?? 0);
        const plateauWindows = Number(event.payload.plateau_windows ?? 0);
        const cycleIndex = Number(event.payload.cycle_index ?? 0);
        const strictnessLevel = Number(event.payload.strictness_level ?? 0);
        const metaPlateauCounter = Number(event.payload.meta_plateau_counter ?? 0);
        const championGateLcb = Number(event.payload.champion_gate_lcb ?? 0);
        const evalProtocolHash = String(event.payload.eval_protocol_hash ?? '');

        setJob((prev) => {
          if (!prev || prev.id !== job.id) {
            return prev;
          }
          return {
            ...prev,
            progress: {
              ...prev.progress,
              games_played: gamesPlayed,
              batches_done: batchesDone,
              windows_done: windowsDone,
              last_score: score,
              best_score: bestScore,
              plateau_windows: plateauWindows,
              cycle_index: cycleIndex,
              strictness_level: strictnessLevel,
              meta_plateau_counter: metaPlateauCounter,
              champion_gate_lcb: championGateLcb,
              eval_protocol_hash: evalProtocolHash,
            },
          };
        });

        const point: MetricPoint = {
          batch: batchesDone,
          window: windowsDone,
          score,
          best: bestScore,
          plateau: plateauWindows,
          cycle: cycleIndex,
          strictness: strictnessLevel,
        };
        upsertMetric(point, job.id);
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

  useEffect(() => {
    if (!job || job.progress.batches_done <= 0) {
      return;
    }
    upsertMetric(
      {
        batch: job.progress.batches_done,
        window: job.progress.windows_done,
        score: job.progress.last_score,
        best: job.progress.best_score,
        plateau: job.progress.plateau_windows,
        cycle: job.progress.cycle_index,
        strictness: job.progress.strictness_level,
      },
      job.id,
    );
  }, [
    job?.id,
    job?.progress.batches_done,
    job?.progress.windows_done,
    job?.progress.last_score,
    job?.progress.best_score,
    job?.progress.plateau_windows,
    job?.progress.cycle_index,
    job?.progress.strictness_level,
  ]);

  const canPause = job?.lifecycle_state === 'Running';
  const canResume = job?.lifecycle_state === 'Paused';
  const canStop = job ? ['Running', 'Pausing', 'Paused'].includes(job.lifecycle_state) : false;

  const latestMetrics = useMemo(() => metrics.slice(0, 10), [metrics]);
  const chartPoints = useMemo(() => metrics.slice(0, 80), [metrics]);
  const scorePolyline = useMemo(() => buildPolyline(chartPoints, (point) => point.score, 420, 120), [chartPoints]);
  const bestPolyline = useMemo(() => buildPolyline(chartPoints, (point) => point.best, 420, 120), [chartPoints]);

  async function onStartTraining() {
    if (isBusy) {
      return;
    }

    setIsBusy(true);
    setErrorText(null);
    setMetrics([]);
    if (job?.id) {
      window.localStorage.removeItem(`${METRICS_STORAGE_KEY_PREFIX}${job.id}`);
    }
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
      window.localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, started.id);
      window.localStorage.removeItem(`${METRICS_STORAGE_KEY_PREFIX}${started.id}`);
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
              Автоэволюция
              <input
                aria-label="Автоэволюция"
                type="checkbox"
                checked={params.autoevolve_enabled}
                onChange={(event) =>
                  setParams((prev) => ({
                    ...prev,
                    autoevolve_enabled: event.target.checked,
                  }))
                }
              />
            </label>

            <label>
              Терпение мета-плато (циклы)
              <input
                aria-label="Терпение мета-плато"
                value={params.meta_plateau_patience_cycles}
                onChange={(event) =>
                  setParams((prev) => ({
                    ...prev,
                    meta_plateau_patience_cycles: toNumber(event.target.value, prev.meta_plateau_patience_cycles),
                  }))
                }
              />
            </label>

            <label>
              Макс. уровень строгости
              <input
                aria-label="Макс. уровень строгости"
                value={params.strictness_max_level}
                onChange={(event) =>
                  setParams((prev) => ({
                    ...prev,
                    strictness_max_level: toNumber(event.target.value, prev.strictness_max_level),
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
              Терпение плато (окон)
              <input
                aria-label="Терпение плато"
                value={params.plateau_patience_windows}
                onChange={(event) =>
                  setParams((prev) => ({
                    ...prev,
                    plateau_patience_windows: toNumber(event.target.value, prev.plateau_patience_windows),
                  }))
                }
              />
            </label>

            <label>
              Ранний стоп: плато (окон)
              <input
                aria-label="Ранний стоп плато"
                value={params.early_stop_plateau_windows}
                onChange={(event) =>
                  setParams((prev) => ({
                    ...prev,
                    early_stop_plateau_windows: toNumber(event.target.value, prev.early_stop_plateau_windows),
                  }))
                }
              />
            </label>

            <label>
              Мин. окон до early stop
              <input
                aria-label="Мин. окон до early stop"
                value={params.min_windows_before_early_stop}
                onChange={(event) =>
                  setParams((prev) => ({
                    ...prev,
                    min_windows_before_early_stop: toNumber(event.target.value, prev.min_windows_before_early_stop),
                  }))
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
          <div className="training-charts" data-testid="training-charts">
            <div className="training-chart">
              <div className="training-chart-title">Score</div>
              <svg viewBox="0 0 420 120" aria-label="График score">
                <polyline className="chart-line-score" points={scorePolyline} />
              </svg>
            </div>
            <div className="training-chart">
              <div className="training-chart-title">Best Score</div>
              <svg viewBox="0 0 420 120" aria-label="График best score">
                <polyline className="chart-line-best" points={bestPolyline} />
              </svg>
            </div>
          </div>
          <table className="data-table" data-testid="training-metrics-table">
            <thead>
                <tr>
                  <th>Батч</th>
                  <th>Окно</th>
                  <th>Цикл</th>
                  <th>Строгость</th>
                  <th>Счёт</th>
                  <th>Лучший</th>
                  <th>Плато</th>
                </tr>
            </thead>
            <tbody>
              {latestMetrics.map((point) => (
                <tr key={`m-${point.batch}-${point.window}`}>
                  <td>{point.batch}</td>
                  <td>{point.window}</td>
                  <td>{point.cycle}</td>
                  <td>{point.strictness}</td>
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
          {job && (
            <div className="inline-summary">
              Цикл: {job.progress.cycle_index} | Уровень строгости: {job.progress.strictness_level} | Метаплато:{' '}
              {job.progress.meta_plateau_counter} | LCB чемпиона: {job.progress.champion_gate_lcb.toFixed(4)}
            </div>
          )}
          {job && <div className="inline-summary">Протокол eval: {job.progress.eval_protocol_hash || '-'}</div>}
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
