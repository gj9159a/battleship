import { useEffect, useMemo, useState } from 'react';

import {
  analyzePlacementBias,
  commandTrainingJob,
  connectEvents,
  createTrainingJob,
  getLatestPlacementBiasReport,
  getRulesets,
  getTrainingJob,
} from '../../shared/api/client';
import type {
  EventEnvelope,
  FrozenSuiteSummaryDTO,
  PlacementBiasReportDTO,
  RulesetDTO,
  TrainingJobDTO,
  TrainingParamsDTO,
} from '../../shared/api/types';

const RULESETS_RETRY_DELAY_MS = 1000;
const ACTIVE_JOB_STORAGE_KEY = 'training.active_job_id';
const METRICS_STORAGE_KEY_PREFIX = 'training.metrics.';
const DEFAULT_PARAMS: TrainingParamsDTO = {
  games_per_candidate: 128,
  epoch_iters: 5,
  microbatch_size: 128,
  eval_window_batches: 5,
  checkpoint_interval_batches: 50,
  population_size: 32,
  train_split: 0.7,
  worker_count: 12,
  quality_gate_games: 256,
  quality_gate_min_winrate: 0.57,
  quality_gate_min_lower_bound: 0.53,
  target_score: 0.8,
  improvement_delta: 0.01,
  plateau_delta: 0.01,
  plateau_patience_windows: 1,
  early_stop_plateau_windows: 30,
  min_windows_before_early_stop: 120,
  tick_delay_ms: 0,
  autoevolve_enabled: true,
  meta_plateau_patience_cycles: 3,
  strictness_max_level: 0,
};
const SEED_BOT_STORAGE_KEY = 'training.seed_bot_version_id';

const CHART_WIDTH = 420;
const CHART_HEIGHT = 120;

type MetricPoint = {
  batch: number;
  window: number;
  score: number;
  best: number;
  plateau: number;
  cycle: number;
  populationSize: number;
  windowEvaluated: boolean;
  avgShotsToSinkAll: number;
  p95ShotsToSinkAll: number;
  avgShotsToFirstHit: number;
  avgShotsAfterFirstHitToSinkAll: number;
  selectionDecisionReason: string;
  selectionTiebreakUsed: boolean;
  selectionNoninferiorityPassed: boolean;
  selectionRobustDelta: number;
  selectionAttackDelta: number;
  sigmaMean: number;
  sigmaMin: number;
  sigmaMax: number;
  restartCount: number;
  lastRestartReason: string;
  lastRestartWindow: number;
  eliteFallbackUsed: boolean;
};

type FrozenSummaryRow = {
  suiteKind: string;
  runId: string;
  createdAt: string;
  winrate: number;
  lcb: number;
  avgShotsToSinkAll: number;
  p95ShotsToSinkAll: number;
};

function toNumber(value: string, fallback: number): number {
  const normalized = value.replace(',', '.');
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function readNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function readString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function readBoolean(value: unknown, fallback = false): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function formatNumber(value: number, digits = 4): string {
  return Number.isFinite(value) ? value.toFixed(digits) : '-';
}

function buildPolylineScaled(
  points: MetricPoint[],
  valueGetter: (point: MetricPoint) => number,
  width: number,
  height: number,
): string {
  if (points.length === 0) {
    return '';
  }
  const sorted = [...points].sort((left, right) => left.batch - right.batch);
  const values = sorted.map((item) => valueGetter(item)).filter((item) => Number.isFinite(item));
  if (values.length === 0) {
    return '';
  }

  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const range = Math.max(1e-9, maxValue - minValue);
  const denominator = Math.max(1, sorted.length - 1);
  const coords: string[] = [];

  for (let index = 0; index < sorted.length; index += 1) {
    const point = sorted[index];
    const x = (index / denominator) * width;
    const raw = valueGetter(point);
    const normalized = (raw - minValue) / range;
    const y = height - normalized * height;
    coords.push(`${x.toFixed(2)},${y.toFixed(2)}`);
  }
  return coords.join(' ');
}

function pickCellColor(value: number, maxValue: number): string {
  const safeMax = maxValue > 0 ? maxValue : 1;
  const ratio = Math.max(0, Math.min(1, value / safeMax));
  const lightness = 97 - ratio * 46;
  return `hsl(164 46% ${lightness.toFixed(1)}%)`;
}

function HeatmapTable({ title, matrix }: { title: string; matrix: number[][] }) {
  if (!Array.isArray(matrix) || matrix.length === 0) {
    return (
      <div className="heatmap-block">
        <div className="training-chart-title">{title}</div>
        <div className="inline-summary">Нет данных.</div>
      </div>
    );
  }

  const flatValues = matrix.flat().filter((item) => Number.isFinite(item));
  const maxValue = flatValues.length > 0 ? Math.max(...flatValues) : 1;

  return (
    <div className="heatmap-block">
      <div className="training-chart-title">{title}</div>
      <div className="table-scroll">
        <table className="heatmap-table">
          <tbody>
            {matrix.map((row, rowIndex) => (
              <tr key={`hr-${rowIndex}`}>
                {row.map((value, colIndex) => (
                  <td
                    key={`hc-${rowIndex}-${colIndex}`}
                    style={{ backgroundColor: pickCellColor(readNumber(value), maxValue) }}
                    title={`r${rowIndex} c${colIndex}: ${formatNumber(readNumber(value), 4)}`}
                  >
                    {formatNumber(readNumber(value), 2)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function TrainingPage() {
  const [rulesets, setRulesets] = useState<RulesetDTO[]>([]);
  const [selectedRulesetId, setSelectedRulesetId] = useState('classic_v1');
  const [seedBotVersionId, setSeedBotVersionId] = useState('');
  const [params, setParams] = useState<TrainingParamsDTO>(DEFAULT_PARAMS);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [job, setJob] = useState<TrainingJobDTO | null>(null);
  const [metrics, setMetrics] = useState<MetricPoint[]>([]);
  const [eventLines, setEventLines] = useState<string[]>([]);
  const [stageReason, setStageReason] = useState<string>('');

  const [biasRulesetId, setBiasRulesetId] = useState('classic_v1');
  const [biasSampleCount, setBiasSampleCount] = useState('5000');
  const [biasSeedAnchor, setBiasSeedAnchor] = useState('');
  const [biasReport, setBiasReport] = useState<PlacementBiasReportDTO | null>(null);
  const [biasLoading, setBiasLoading] = useState(false);
  const [biasStatus, setBiasStatus] = useState('');
  const [biasError, setBiasError] = useState<string | null>(null);

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
    if (!seedBotVersionId.trim()) {
      window.localStorage.removeItem(SEED_BOT_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(SEED_BOT_STORAGE_KEY, seedBotVersionId.trim());
  }, [seedBotVersionId]);

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
        setBiasRulesetId((prev) => {
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

  function upsertMetric(point: MetricPoint, jobId: string) {
    setMetrics((prev) => {
      const currentByBatch = new Map(prev.map((item) => [item.batch, item]));
      const existing = currentByBatch.get(point.batch);
      if (existing && existing.windowEvaluated && !point.windowEvaluated) {
        point = existing;
      }
      currentByBatch.set(point.batch, point);
      const merged = Array.from(currentByBatch.values())
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
        const reason = readString(event.payload.reason, 'unknown');
        setStageReason(reason);
      }

      if (event.event_type === 'training.frozen_suites_updated') {
        const suiteSummaries = (event.payload.suite_summaries ?? {}) as Record<string, FrozenSuiteSummaryDTO>;
        setJob((prev) => {
          if (!prev || prev.id !== job.id) {
            return prev;
          }
          return {
            ...prev,
            progress: {
              ...prev.progress,
              frozen_suite_summaries: suiteSummaries,
            },
          };
        });
      }

      if (event.event_type === 'training.metrics') {
        const gamesPlayed = readNumber(event.payload.games_played);
        const batchesDone = readNumber(event.payload.batches_done);
        const windowsDone = readNumber(event.payload.windows_done);
        const score = readNumber(event.payload.score);
        const bestScore = readNumber(event.payload.best_score);
        const plateauWindows = readNumber(event.payload.plateau_windows);
        const cycleIndex = readNumber(event.payload.cycle_index);
        const currentPopulationSize = readNumber(
          event.payload.current_population_size,
          readNumber(job.progress.current_population_size, job.params.population_size),
        );
        const metaPlateauCounter = readNumber(event.payload.meta_plateau_counter);
        const championGateLcb = readNumber(event.payload.champion_gate_lcb);
        const evalProtocolHash = readString(event.payload.eval_protocol_hash);
        const avgShotsToSinkAll = readNumber(event.payload.avg_shots_to_sink_all);
        const p95ShotsToSinkAll = readNumber(event.payload.p95_shots_to_sink_all);
        const avgShotsToFirstHit = readNumber(event.payload.avg_shots_to_first_hit);
        const avgShotsAfterFirstHitToSinkAll = readNumber(event.payload.avg_shots_after_first_hit_to_sink_all);
        const selectionDecisionReason = readString(event.payload.selection_decision_reason, 'unknown');
        const selectionTiebreakUsed = readBoolean(event.payload.selection_tiebreak_used);
        const selectionNoninferiorityPassed = readBoolean(event.payload.selection_noninferiority_passed);
        const selectionRobustDelta = readNumber(event.payload.selection_robust_delta);
        const selectionAttackDelta = readNumber(event.payload.selection_attack_delta);
        const sigmaMean = readNumber(event.payload.sigma_mean);
        const sigmaMin = readNumber(event.payload.sigma_min);
        const sigmaMax = readNumber(event.payload.sigma_max);
        const restartCount = readNumber(event.payload.restart_count);
        const lastRestartReason = readString(event.payload.last_restart_reason, 'none');
        const lastRestartWindow = readNumber(event.payload.last_restart_window, -1);
        const eliteFallbackUsed = readBoolean(event.payload.elite_fallback_used);
        const frozenSuiteSummaries = (event.payload.frozen_suite_summaries ?? {}) as Record<string, FrozenSuiteSummaryDTO>;

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
              current_population_size: currentPopulationSize,
              meta_plateau_counter: metaPlateauCounter,
              champion_gate_lcb: championGateLcb,
              eval_protocol_hash: evalProtocolHash,
              last_avg_shots_to_sink_all: avgShotsToSinkAll,
              last_p95_shots_to_sink_all: p95ShotsToSinkAll,
              last_avg_shots_to_first_hit: avgShotsToFirstHit,
              last_avg_shots_after_first_hit_to_sink_all: avgShotsAfterFirstHitToSinkAll,
              selection_decision_reason: selectionDecisionReason,
              selection_tiebreak_used: selectionTiebreakUsed,
              selection_noninferiority_passed: selectionNoninferiorityPassed,
              selection_robust_delta: selectionRobustDelta,
              selection_attack_delta: selectionAttackDelta,
              sigma_mean: sigmaMean,
              sigma_min: sigmaMin,
              sigma_max: sigmaMax,
              restart_count: restartCount,
              last_restart_reason: lastRestartReason,
              last_restart_window: lastRestartWindow,
              elite_fallback_used: eliteFallbackUsed,
              frozen_suite_summaries: frozenSuiteSummaries,
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
          populationSize: currentPopulationSize,
          windowEvaluated: readBoolean(event.payload.window_evaluated),
          avgShotsToSinkAll,
          p95ShotsToSinkAll,
          avgShotsToFirstHit,
          avgShotsAfterFirstHitToSinkAll,
          selectionDecisionReason,
          selectionTiebreakUsed,
          selectionNoninferiorityPassed,
          selectionRobustDelta,
          selectionAttackDelta,
          sigmaMean,
          sigmaMin,
          sigmaMax,
          restartCount,
          lastRestartReason,
          lastRestartWindow,
          eliteFallbackUsed,
        };
        upsertMetric(point, job.id);
      }

      if (event.event_type === 'job.lifecycle_changed') {
        void refreshJob(job.id).catch(() => {
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
    const epochIters = Math.max(1, readNumber(job.params.epoch_iters, readNumber(job.params.eval_window_batches, 1)));

    upsertMetric(
      {
        batch: job.progress.batches_done,
        window: job.progress.windows_done,
        score: job.progress.last_score,
        best: job.progress.best_score,
        plateau: job.progress.plateau_windows,
        cycle: job.progress.cycle_index,
        populationSize: readNumber(job.progress.current_population_size, job.params.population_size),
        windowEvaluated: Boolean(
          job.progress.windows_done > 0 &&
            job.progress.batches_done === job.progress.windows_done * epochIters,
        ),
        avgShotsToSinkAll: readNumber(job.progress.last_avg_shots_to_sink_all),
        p95ShotsToSinkAll: readNumber(job.progress.last_p95_shots_to_sink_all),
        avgShotsToFirstHit: readNumber(job.progress.last_avg_shots_to_first_hit),
        avgShotsAfterFirstHitToSinkAll: readNumber(job.progress.last_avg_shots_after_first_hit_to_sink_all),
        selectionDecisionReason: readString(job.progress.selection_decision_reason, 'unknown'),
        selectionTiebreakUsed: readBoolean(job.progress.selection_tiebreak_used),
        selectionNoninferiorityPassed: readBoolean(job.progress.selection_noninferiority_passed),
        selectionRobustDelta: readNumber(job.progress.selection_robust_delta),
        selectionAttackDelta: readNumber(job.progress.selection_attack_delta),
        sigmaMean: readNumber(job.progress.sigma_mean),
        sigmaMin: readNumber(job.progress.sigma_min),
        sigmaMax: readNumber(job.progress.sigma_max),
        restartCount: readNumber(job.progress.restart_count),
        lastRestartReason: readString(job.progress.last_restart_reason, 'none'),
        lastRestartWindow: readNumber(job.progress.last_restart_window, -1),
        eliteFallbackUsed: readBoolean(job.progress.elite_fallback_used),
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
    job?.progress.current_population_size,
    job?.params.epoch_iters,
    job?.progress.last_avg_shots_to_sink_all,
    job?.progress.last_p95_shots_to_sink_all,
    job?.progress.last_avg_shots_to_first_hit,
    job?.progress.last_avg_shots_after_first_hit_to_sink_all,
    job?.progress.selection_decision_reason,
    job?.progress.selection_tiebreak_used,
    job?.progress.selection_noninferiority_passed,
    job?.progress.selection_robust_delta,
    job?.progress.selection_attack_delta,
    job?.progress.sigma_mean,
    job?.progress.sigma_min,
    job?.progress.sigma_max,
    job?.progress.restart_count,
    job?.progress.last_restart_reason,
    job?.progress.last_restart_window,
    job?.progress.elite_fallback_used,
  ]);

  const canPause = job?.lifecycle_state === 'Running';
  const canResume = job?.lifecycle_state === 'Paused';
  const canStop = job ? ['Running', 'Pausing', 'Paused'].includes(job.lifecycle_state) : false;

  const windowMetrics = useMemo(() => {
    const evalWindowBatches = Math.max(1, readNumber(job?.params.epoch_iters, 1));
    const byWindow = new Map<number, MetricPoint>();
    for (const point of metrics) {
      if (!point.windowEvaluated || point.window <= 0) {
        continue;
      }
      const existing = byWindow.get(point.window);
      if (!existing) {
        byWindow.set(point.window, point);
        continue;
      }
      const pointIsExact = point.batch === point.window * evalWindowBatches;
      const existingIsExact = existing.batch === existing.window * evalWindowBatches;
      if (pointIsExact && !existingIsExact) {
        byWindow.set(point.window, point);
        continue;
      }
      if (pointIsExact === existingIsExact && point.batch > existing.batch) {
        byWindow.set(point.window, point);
      }
    }
    return Array.from(byWindow.values()).sort((left, right) => right.batch - left.batch);
  }, [job?.params.epoch_iters, metrics]);
  const latestMetrics = useMemo(() => windowMetrics.slice(0, 10), [windowMetrics]);
  const chartPoints = useMemo(() => windowMetrics.slice(0, 80).reverse(), [windowMetrics]);
  const latestPoint = latestMetrics[0] ?? null;

  const scorePolyline = useMemo(
    () => buildPolylineScaled(chartPoints, (point) => point.score, CHART_WIDTH, CHART_HEIGHT),
    [chartPoints],
  );
  const bestPolyline = useMemo(
    () => buildPolylineScaled(chartPoints, (point) => point.best, CHART_WIDTH, CHART_HEIGHT),
    [chartPoints],
  );
  const avgShotsPolyline = useMemo(
    () => buildPolylineScaled(chartPoints, (point) => point.avgShotsToSinkAll, CHART_WIDTH, CHART_HEIGHT),
    [chartPoints],
  );
  const p95ShotsPolyline = useMemo(
    () => buildPolylineScaled(chartPoints, (point) => point.p95ShotsToSinkAll, CHART_WIDTH, CHART_HEIGHT),
    [chartPoints],
  );
  const sigmaPolyline = useMemo(
    () => buildPolylineScaled(chartPoints, (point) => point.sigmaMean, CHART_WIDTH, CHART_HEIGHT),
    [chartPoints],
  );

  const frozenSummaryRows = useMemo((): FrozenSummaryRow[] => {
    const raw = job?.progress.frozen_suite_summaries;
    if (!raw) {
      return [];
    }

    return Object.entries(raw)
      .map(([suiteKind, summary]) => ({
        suiteKind,
        runId: readString(summary.run_id),
        createdAt: readString(summary.created_at),
        winrate: readNumber(summary.winrate),
        lcb: readNumber(summary.lcb),
        avgShotsToSinkAll: readNumber(summary.avg_shots_to_sink_all),
        p95ShotsToSinkAll: readNumber(summary.p95_shots_to_sink_all),
      }))
      .sort((left, right) => left.suiteKind.localeCompare(right.suiteKind));
  }, [job?.progress.frozen_suite_summaries]);

  const occupancyByLenEntries = useMemo(() => {
    if (!biasReport) {
      return [];
    }
    return Object.entries(biasReport.occupancy_by_ship_len).sort(([left], [right]) => Number(right) - Number(left));
  }, [biasReport]);

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
    setStageReason('');

    try {
      const created = await createTrainingJob({
        ruleset_id: selectedRulesetId,
        seed_bot_version_id: seedBotVersionId.trim() || null,
        params,
      });
      const started = await commandTrainingJob(created.id, 'start');
      setJob(started);
      window.localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, started.id);
      window.localStorage.removeItem(`${METRICS_STORAGE_KEY_PREFIX}${started.id}`);
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

  async function onAnalyzeBias() {
    setBiasLoading(true);
    setBiasError(null);
    setBiasStatus('Запуск bias-анализа...');
    try {
      const report = await analyzePlacementBias({
        ruleset_id: biasRulesetId,
        sample_count: Math.max(1, Math.floor(toNumber(biasSampleCount, 5000))),
        seed_anchor: biasSeedAnchor.trim() ? Math.floor(toNumber(biasSeedAnchor, 0)) : null,
      });
      setBiasReport(report);
      setBiasStatus(`Bias-отчёт построен: ${report.report_id}`);
    } catch (error) {
      setBiasError((error as Error).message);
      setBiasStatus('Ошибка bias-анализа.');
    } finally {
      setBiasLoading(false);
    }
  }

  async function onLoadLatestBias() {
    setBiasLoading(true);
    setBiasError(null);
    setBiasStatus('Загрузка последнего bias-отчёта...');
    try {
      const report = await getLatestPlacementBiasReport(biasRulesetId);
      setBiasReport(report);
      setBiasStatus(`Загружен последний отчёт: ${report.report_id}`);
    } catch (error) {
      setBiasError((error as Error).message);
      setBiasStatus('Последний отчёт не найден.');
      setBiasReport(null);
    } finally {
      setBiasLoading(false);
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
          Игр на кандидата
          <input
            aria-label="Игр на кандидата"
            value={params.games_per_candidate}
            onChange={(event) =>
              setParams((prev) => {
                const value = toNumber(event.target.value, prev.games_per_candidate);
                return {
                  ...prev,
                  games_per_candidate: value,
                  microbatch_size: value,
                };
              })
            }
          />
        </label>

        <label>
          Итераций в эпохе
          <input
            aria-label="Итераций в эпохе"
            value={params.epoch_iters}
            onChange={(event) =>
              setParams((prev) => {
                const value = toNumber(event.target.value, prev.epoch_iters);
                return {
                  ...prev,
                  epoch_iters: value,
                  eval_window_batches: value,
                };
              })
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
              Порог улучшения (доля 0..1)
              <input
                aria-label="Порог улучшения"
                type="number"
                step="0.0001"
                min="0"
                max="1"
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
              Порог плато (доля 0..1)
              <input
                aria-label="Порог плато"
                type="number"
                step="0.0001"
                min="0"
                max="1"
                value={params.plateau_delta}
                onChange={(event) =>
                  setParams((prev) => ({ ...prev, plateau_delta: toNumber(event.target.value, prev.plateau_delta) }))
                }
              />
            </label>

            <label>
              Терпение плато (эпох)
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
          <div className="inline-summary">В графиках и таблицах используются только финальные точки эпох.</div>
          <div className="training-charts" data-testid="training-charts">
            <div className="training-chart">
              <div className="training-chart-title">Score</div>
              <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} aria-label="График score">
                <polyline className="chart-line-score" points={scorePolyline} />
              </svg>
            </div>
            <div className="training-chart">
              <div className="training-chart-title">Best Score</div>
              <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} aria-label="График best score">
                <polyline className="chart-line-best" points={bestPolyline} />
              </svg>
            </div>
            <div className="training-chart">
              <div className="training-chart-title">avg_shots_to_sink_all</div>
              <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} aria-label="График avg_shots_to_sink_all">
                <polyline className="chart-line-attack" points={avgShotsPolyline} />
              </svg>
            </div>
            <div className="training-chart">
              <div className="training-chart-title">p95_shots_to_sink_all</div>
              <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} aria-label="График p95_shots_to_sink_all">
                <polyline className="chart-line-attack-p95" points={p95ShotsPolyline} />
              </svg>
            </div>
            <div className="training-chart">
              <div className="training-chart-title">sigma_mean</div>
              <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} aria-label="График sigma_mean">
                <polyline className="chart-line-sigma" points={sigmaPolyline} />
              </svg>
            </div>
          </div>

          {latestPoint && (
            <div className="inline-summary">
              Последнее решение: {latestPoint.selectionDecisionReason} | tiebreak:{' '}
              {latestPoint.selectionTiebreakUsed ? 'yes' : 'no'} | noninferiority:{' '}
              {latestPoint.selectionNoninferiorityPassed ? 'pass' : 'fail'} | Δrobust:{' '}
              {formatNumber(latestPoint.selectionRobustDelta, 4)} | Δattack: {formatNumber(latestPoint.selectionAttackDelta, 4)}
            </div>
          )}

          <div className="table-scroll">
            <table className="data-table" data-testid="training-metrics-table">
              <thead>
                <tr>
                  <th>Итерация</th>
                  <th>Эпоха</th>
                  <th>Цикл</th>
                  <th>Популяция</th>
                  <th>Счёт</th>
                  <th>Лучший</th>
                  <th>Плато</th>
                  <th>avg_sink</th>
                  <th>p95_sink</th>
                  <th>avg_first_hit</th>
                  <th>avg_after_hit</th>
                  <th>Decision</th>
                  <th>Tie</th>
                  <th>NI</th>
                  <th>Δrobust</th>
                  <th>Δattack</th>
                  <th>σmean</th>
                  <th>σmin</th>
                  <th>σmax</th>
                  <th>Restarts</th>
                  <th>Last restart</th>
                  <th>Fallback</th>
                </tr>
              </thead>
              <tbody>
                {latestMetrics.map((point) => (
                  <tr key={`m-${point.batch}-${point.window}`}>
                    <td>{point.batch}</td>
                    <td>{point.window}</td>
                    <td>{point.cycle}</td>
                    <td>{point.populationSize}</td>
                    <td>{formatNumber(point.score, 4)}</td>
                    <td>{formatNumber(point.best, 4)}</td>
                    <td>{point.plateau}</td>
                    <td>{formatNumber(point.avgShotsToSinkAll, 2)}</td>
                    <td>{formatNumber(point.p95ShotsToSinkAll, 2)}</td>
                    <td>{formatNumber(point.avgShotsToFirstHit, 2)}</td>
                    <td>{formatNumber(point.avgShotsAfterFirstHitToSinkAll, 2)}</td>
                    <td>{point.selectionDecisionReason}</td>
                    <td>{point.selectionTiebreakUsed ? 'yes' : 'no'}</td>
                    <td>{point.selectionNoninferiorityPassed ? 'pass' : 'fail'}</td>
                    <td>{formatNumber(point.selectionRobustDelta, 4)}</td>
                    <td>{formatNumber(point.selectionAttackDelta, 4)}</td>
                    <td>{formatNumber(point.sigmaMean, 4)}</td>
                    <td>{formatNumber(point.sigmaMin, 4)}</td>
                    <td>{formatNumber(point.sigmaMax, 4)}</td>
                    <td>{point.restartCount}</td>
                    <td>
                      {point.lastRestartReason}
                      {point.lastRestartWindow >= 0 ? `@${point.lastRestartWindow}` : ''}
                    </td>
                    <td>{point.eliteFallbackUsed ? 'yes' : 'no'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {job && (
            <div className="inline-summary">
              Игры: {job.progress.games_played} | Итерации: {job.progress.batches_done} | Лучший: {job.progress.best_score.toFixed(4)}
            </div>
          )}
          {job && (
            <div className="inline-summary">
              Цикл: {job.progress.cycle_index} | Популяция: {readNumber(job.progress.current_population_size, job.params.population_size)} |
              Плато-срабатываний: {job.progress.meta_plateau_counter} | LCB чемпиона: {job.progress.champion_gate_lcb.toFixed(4)}
            </div>
          )}
          {job && (
            <div className="inline-summary">
              Search: σmean={formatNumber(readNumber(job.progress.sigma_mean), 4)}; σmin={formatNumber(readNumber(job.progress.sigma_min), 4)};
              σmax={formatNumber(readNumber(job.progress.sigma_max), 4)}; restarts={readNumber(job.progress.restart_count)}; reason=
              {readString(job.progress.last_restart_reason, 'none')}; window={readNumber(job.progress.last_restart_window, -1)}
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
          <h3>Frozen Benchmarks (последние)</h3>
          {frozenSummaryRows.length === 0 ? (
            <div className="inline-summary">Пока нет frozen suite результатов для текущего job.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table" data-testid="training-frozen-summaries-table">
                <thead>
                  <tr>
                    <th>Suite</th>
                    <th>Run ID</th>
                    <th>Время</th>
                    <th>Winrate</th>
                    <th>LCB</th>
                    <th>avg_sink</th>
                    <th>p95_sink</th>
                  </tr>
                </thead>
                <tbody>
                  {frozenSummaryRows.map((row) => (
                    <tr key={`${row.suiteKind}-${row.runId}`}>
                      <td>{row.suiteKind}</td>
                      <td>{row.runId || '-'}</td>
                      <td>{row.createdAt || '-'}</td>
                      <td>{formatNumber(row.winrate, 4)}</td>
                      <td>{formatNumber(row.lcb, 4)}</td>
                      <td>{formatNumber(row.avgShotsToSinkAll, 2)}</td>
                      <td>{formatNumber(row.p95ShotsToSinkAll, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="panel" data-testid="placement-bias-panel">
          <h3>Bias-диагностика расстановки</h3>
          <div className="training-bias-controls">
            <label>
              Ruleset
              <select value={biasRulesetId} onChange={(event) => setBiasRulesetId(event.target.value)}>
                {rulesets.map((item) => (
                  <option key={`bias-${item.id}`} value={item.id}>
                    {item.name} ({item.id})
                  </option>
                ))}
              </select>
            </label>
            <label>
              sample_count
              <input value={biasSampleCount} onChange={(event) => setBiasSampleCount(event.target.value)} />
            </label>
            <label>
              seed_anchor (optional)
              <input value={biasSeedAnchor} onChange={(event) => setBiasSeedAnchor(event.target.value)} />
            </label>
            <div className="button-row">
              <button type="button" onClick={onAnalyzeBias} disabled={biasLoading || rulesets.length === 0}>
                Analyze
              </button>
              <button type="button" className="ghost-btn" onClick={onLoadLatestBias} disabled={biasLoading || rulesets.length === 0}>
                Load latest
              </button>
            </div>
          </div>

          {biasStatus && <div className="inline-summary">{biasStatus}</div>}
          {biasError && <div role="alert">{biasError}</div>}

          {!biasReport && <div className="inline-summary">Отчёт не загружен. Запустите анализ или загрузите последний отчёт.</div>}

          {biasReport && (
            <>
              <div className="inline-summary">
                ruleset={biasReport.ruleset_id}; sample_count={biasReport.sample_count}; seed_anchor={biasReport.seed_anchor};
                scheme={biasReport.seed_derivation_scheme}; generator={biasReport.generator_version}; created_at={biasReport.created_at}
              </div>
              <div className="inline-summary">
                reproducibility: {JSON.stringify(biasReport.seed_reproducibility_check)}
              </div>

              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Метрика</th>
                      <th>Значение</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(biasReport.edge_center_bias).map(([key, value]) => (
                      <tr key={`ec-${key}`}>
                        <td>edge_center_bias.{key}</td>
                        <td>{formatNumber(readNumber(value), 6)}</td>
                      </tr>
                    ))}
                    {Object.entries(biasReport.corner_bias).map(([key, value]) => (
                      <tr key={`corner-${key}`}>
                        <td>corner_bias.{key}</td>
                        <td>{formatNumber(readNumber(value), 6)}</td>
                      </tr>
                    ))}
                    <tr>
                      <td>retry_stats</td>
                      <td>{JSON.stringify(biasReport.retry_stats)}</td>
                    </tr>
                    {readBoolean((biasReport.retry_stats as Record<string, unknown>).unavailable) && (
                      <tr>
                        <td>retry_stats.unavailable</td>
                        <td>true</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>ship_len</th>
                      <th>horizontal</th>
                      <th>vertical</th>
                      <th>count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(biasReport.orientation_stats_by_len)
                      .sort(([left], [right]) => Number(right) - Number(left))
                      .map(([shipLen, stats]) => (
                        <tr key={`orientation-${shipLen}`}>
                          <td>{shipLen}</td>
                          <td>{formatNumber(readNumber(stats.horizontal), 6)}</td>
                          <td>{formatNumber(readNumber(stats.vertical), 6)}</td>
                          <td>{readNumber(stats.count)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>

              <div className="heatmap-grid">
                <HeatmapTable title="occupancy_heatmap" matrix={biasReport.occupancy_heatmap} />
                {occupancyByLenEntries.map(([shipLen, matrix]) => (
                  <HeatmapTable key={`ship-len-${shipLen}`} title={`occupancy_by_ship_len[${shipLen}]`} matrix={matrix} />
                ))}
              </div>
            </>
          )}
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
