import { useEffect, useState } from 'react';

import {
  createBotFromCheckpoint,
  getBotCheckpoints,
  getBotVersions,
  getRulesets,
  patchBotLabels,
  registerLeagueBot,
} from '../../shared/api/client';
import type { BotVersionDTO, LeaguePoolType, RulesetDTO, TrainingCheckpointIndexDTO } from '../../shared/api/types';

const SEED_BOT_STORAGE_KEY = 'training.seed_bot_version_id';

export function BotsPage() {
  const [rulesets, setRulesets] = useState<RulesetDTO[]>([]);
  const [selectedRulesetId, setSelectedRulesetId] = useState('classic_v1');
  const [includeLegacy, setIncludeLegacy] = useState(true);
  const [policyFilter, setPolicyFilter] = useState('');
  const [schemaFilter, setSchemaFilter] = useState('');
  const [importPoolType, setImportPoolType] = useState<LeaguePoolType>('active');

  const [bots, setBots] = useState<BotVersionDTO[]>([]);
  const [checkpoints, setCheckpoints] = useState<TrainingCheckpointIndexDTO[]>([]);
  const [seedBotId, setSeedBotId] = useState('');

  const [statusText, setStatusText] = useState('Загрузка bots/checkpoints...');
  const [errorText, setErrorText] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    const storedSeed = window.localStorage.getItem(SEED_BOT_STORAGE_KEY);
    if (storedSeed) {
      setSeedBotId(storedSeed);
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
      })
      .catch((error: Error) => {
        if (mounted) {
          setErrorText(error.message);
          setStatusText('Не удалось загрузить rulesets.');
        }
      });

    return () => {
      mounted = false;
    };
  }, [selectedRulesetId]);

  async function refreshData() {
    const [botRows, checkpointRows] = await Promise.all([
      getBotVersions({
        ruleset_id: selectedRulesetId,
        policy_type: policyFilter.trim() || undefined,
        feature_schema_version: schemaFilter.trim() || undefined,
        include_legacy: includeLegacy,
      }),
      getBotCheckpoints(selectedRulesetId),
    ]);

    setBots(botRows);
    setCheckpoints(checkpointRows);
  }

  useEffect(() => {
    if (!selectedRulesetId) {
      return;
    }

    refreshData()
      .then(() => {
        setStatusText('Готово к работе с bots/checkpoints.');
      })
      .catch((error: Error) => {
        setErrorText(error.message);
        setStatusText('Ошибка загрузки bots/checkpoints.');
      });
  }, [selectedRulesetId, includeLegacy, policyFilter, schemaFilter]);

  async function withBusy(action: () => Promise<void>) {
    setIsBusy(true);
    setErrorText(null);
    try {
      await action();
    } catch (error) {
      setErrorText((error as Error).message);
    } finally {
      setIsBusy(false);
    }
  }

  async function onPromoteCheckpoint(row: TrainingCheckpointIndexDTO) {
    await withBusy(async () => {
      await createBotFromCheckpoint({
        job_id: row.job_id,
        checkpoint_id: row.checkpoint_id,
      });
      await refreshData();
      setStatusText(`Checkpoint ${row.checkpoint_id} promoted to bot version.`);
    });
  }

  async function onImportToLeague(botVersionId: string) {
    await withBusy(async () => {
      await registerLeagueBot(selectedRulesetId, botVersionId, importPoolType);
      setStatusText(`Bot ${botVersionId} imported to league pool: ${importPoolType}.`);
    });
  }

  async function onToggleLegacy(bot: BotVersionDTO) {
    await withBusy(async () => {
      const isLegacy = bot.tags.includes('legacy');
      await patchBotLabels(bot.bot_version_id, { is_legacy: !isLegacy });
      await refreshData();
      setStatusText(`Bot ${bot.bot_version_id}: legacy = ${!isLegacy}.`);
    });
  }

  function onUseAsSeed(botVersionId: string) {
    window.localStorage.setItem(SEED_BOT_STORAGE_KEY, botVersionId);
    setSeedBotId(botVersionId);
    setStatusText(`Training seed bot selected: ${botVersionId}.`);
  }

  return (
    <section className="screen-layout">
      <aside className="panel controls">
        <h2>Bots / Checkpoints</h2>

        <label>
          Ruleset
          <select value={selectedRulesetId} onChange={(event) => setSelectedRulesetId(event.target.value)}>
            {rulesets.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.id})
              </option>
            ))}
          </select>
        </label>

        <label>
          Policy filter
          <input value={policyFilter} onChange={(event) => setPolicyFilter(event.target.value)} placeholder="probability_strong" />
        </label>

        <label>
          Feature schema filter
          <input value={schemaFilter} onChange={(event) => setSchemaFilter(event.target.value)} placeholder="classic_features_v1" />
        </label>

        <label>
          Include legacy
          <input type="checkbox" checked={includeLegacy} onChange={(event) => setIncludeLegacy(event.target.checked)} />
        </label>

        <label>
          League pool for import
          <select value={importPoolType} onChange={(event) => setImportPoolType(event.target.value as LeaguePoolType)}>
            <option value="active">active</option>
            <option value="baseline">baseline</option>
            <option value="league">league</option>
          </select>
        </label>

        <button type="button" className="ghost-btn" onClick={() => void refreshData()} disabled={isBusy}>
          Refresh
        </button>

        <div className="status" data-testid="bots-status-text">
          {statusText}
        </div>

        <div data-testid="bots-seed-selection">Training seed: {seedBotId || '-'}</div>

        {errorText && <div role="alert">{errorText}</div>}
      </aside>

      <div className="screen-content">
        <section className="panel">
          <h3>Bot versions</h3>
          <table className="data-table" data-testid="bots-table">
            <thead>
              <tr>
                <th>Bot version</th>
                <th>Policy</th>
                <th>Schema</th>
                <th>Lookahead</th>
                <th>Source checkpoint</th>
                <th>Tags</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {bots.map((bot) => (
                <tr key={bot.bot_version_id}>
                  <td>{bot.bot_version_id}</td>
                  <td>{bot.policy_type}</td>
                  <td>{bot.feature_schema_version}</td>
                  <td>{bot.lookahead_policy_version}</td>
                  <td>{bot.source_checkpoint_id ?? '-'}</td>
                  <td>{bot.tags.join(', ') || '-'}</td>
                  <td>
                    <button type="button" className="mini-btn" onClick={() => onUseAsSeed(bot.bot_version_id)}>
                      Use as seed
                    </button>{' '}
                    <button
                      type="button"
                      className="mini-btn"
                      onClick={() => void onImportToLeague(bot.bot_version_id)}
                      disabled={isBusy}
                    >
                      Import to league
                    </button>{' '}
                    <button type="button" className="mini-btn ghost-btn" onClick={() => void onToggleLegacy(bot)} disabled={isBusy}>
                      Toggle legacy
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="panel">
          <h3>Training checkpoints</h3>
          <table className="data-table" data-testid="bots-checkpoints-table">
            <thead>
              <tr>
                <th>Job</th>
                <th>Checkpoint</th>
                <th>Batches</th>
                <th>Best score</th>
                <th>Stage</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {checkpoints.map((row) => (
                <tr key={`${row.job_id}-${row.checkpoint_id}`}>
                  <td>{row.job_id.slice(0, 8)}</td>
                  <td>{row.checkpoint_id}</td>
                  <td>{row.batches_done}</td>
                  <td>{row.best_score.toFixed(4)}</td>
                  <td>{row.stage_state ?? '-'}</td>
                  <td>
                    <button type="button" className="mini-btn" onClick={() => void onPromoteCheckpoint(row)} disabled={isBusy}>
                      Promote to bot
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </section>
  );
}
