import { useEffect, useState } from 'react';

import {
  getBotVersions,
  getRulesets,
  patchBotLabels,
  registerLeagueBot,
} from '../../shared/api/client';
import type { BotVersionDTO, LeaguePoolType, RulesetDTO } from '../../shared/api/types';

const SEED_BOT_STORAGE_KEY = 'training.seed_bot_version_id';

export function BotsPage() {
  const [rulesets, setRulesets] = useState<RulesetDTO[]>([]);
  const [selectedRulesetId, setSelectedRulesetId] = useState('classic_v1');
  const [includeLegacy, setIncludeLegacy] = useState(true);
  const [policyFilter, setPolicyFilter] = useState('');
  const [schemaFilter, setSchemaFilter] = useState('');
  const [importPoolType, setImportPoolType] = useState<LeaguePoolType>('active');

  const [bots, setBots] = useState<BotVersionDTO[]>([]);
  const [seedBotId, setSeedBotId] = useState('');

  const [statusText, setStatusText] = useState('Загрузка ботов...');
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
          setStatusText('Не удалось загрузить профили правил.');
        }
      });

    return () => {
      mounted = false;
    };
  }, [selectedRulesetId]);

  async function refreshData() {
    const botRows = await getBotVersions({
      ruleset_id: selectedRulesetId,
      policy_type: policyFilter.trim() || undefined,
      feature_schema_version: schemaFilter.trim() || undefined,
      include_legacy: includeLegacy,
    });

    setBots(botRows);
  }

  useEffect(() => {
    if (!selectedRulesetId) {
      return;
    }

    refreshData()
      .then(() => {
        setStatusText('Готово к работе с ботами.');
      })
      .catch((error: Error) => {
        setErrorText(error.message);
        setStatusText('Ошибка загрузки ботов.');
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

  async function onImportToLeague(botVersionId: string) {
    await withBusy(async () => {
      await registerLeagueBot(selectedRulesetId, botVersionId, importPoolType);
      setStatusText(`Бот ${botVersionId} импортирован в пул лиги: ${importPoolType}.`);
    });
  }

  async function onToggleLegacy(bot: BotVersionDTO) {
    await withBusy(async () => {
      const isLegacy = bot.tags.includes('legacy');
      await patchBotLabels(bot.bot_version_id, { is_legacy: !isLegacy });
      await refreshData();
      setStatusText(`Бот ${bot.bot_version_id}: legacy = ${!isLegacy}.`);
    });
  }

  function onUseAsSeed(botVersionId: string) {
    window.localStorage.setItem(SEED_BOT_STORAGE_KEY, botVersionId);
    setSeedBotId(botVersionId);
    setStatusText(`Seed-бот для тренировки выбран: ${botVersionId}.`);
  }

  return (
    <section className="screen-layout">
      <aside className="panel controls">
        <h2>Боты</h2>

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
          Фильтр policy
          <input value={policyFilter} onChange={(event) => setPolicyFilter(event.target.value)} placeholder="probability_strong" />
        </label>

        <label>
          Фильтр схемы признаков
          <input value={schemaFilter} onChange={(event) => setSchemaFilter(event.target.value)} placeholder="classic_features_v1" />
        </label>

        <label>
          Показывать legacy
          <input type="checkbox" checked={includeLegacy} onChange={(event) => setIncludeLegacy(event.target.checked)} />
        </label>

        <label>
          Пул лиги для импорта
          <select value={importPoolType} onChange={(event) => setImportPoolType(event.target.value as LeaguePoolType)}>
            <option value="active">active (кандидаты)</option>
            <option value="baseline">baseline (базовые)</option>
            <option value="league">league (лига)</option>
          </select>
        </label>

        <button type="button" className="ghost-btn" onClick={() => void refreshData()} disabled={isBusy}>
          Обновить
        </button>

        <div className="status" data-testid="bots-status-text">
          {statusText}
        </div>

        <div data-testid="bots-seed-selection">Seed тренировки: {seedBotId || '-'}</div>

        {errorText && <div role="alert">{errorText}</div>}
      </aside>

      <div className="screen-content">
        <section className="panel">
          <h3>Версии ботов</h3>
          <table className="data-table" data-testid="bots-table">
            <thead>
              <tr>
                <th>Версия бота</th>
                <th>Политика</th>
                <th>Схема</th>
                <th>Лукахед</th>
                <th>Источник</th>
                <th>Теги</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {bots.map((bot) => (
                <tr key={bot.bot_version_id}>
                  <td>{bot.bot_version_id}</td>
                  <td>{bot.policy_type}</td>
                  <td>{bot.feature_schema_version}</td>
                  <td>{bot.lookahead_policy_version}</td>
                  <td>{bot.source_job_id ?? '-'}</td>
                  <td>{bot.tags.join(', ') || '-'}</td>
                  <td>
                    <button type="button" className="mini-btn" onClick={() => onUseAsSeed(bot.bot_version_id)}>
                      Выбрать как seed
                    </button>{' '}
                    <button
                      type="button"
                      className="mini-btn"
                      onClick={() => void onImportToLeague(bot.bot_version_id)}
                      disabled={isBusy}
                    >
                      Импорт в лигу
                    </button>{' '}
                    <button type="button" className="mini-btn ghost-btn" onClick={() => void onToggleLegacy(bot)} disabled={isBusy}>
                      Переключить legacy
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
