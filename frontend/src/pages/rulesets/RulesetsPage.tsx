import { useEffect, useMemo, useState } from 'react';

import {
  activateRuleset,
  archiveRuleset,
  cloneRuleset,
  createRuleset,
  getRulesetsWithArchived,
  updateRuleset,
} from '../../shared/api/client';
import type { RulesetDTO } from '../../shared/api/types';

type RulesetForm = {
  id: string;
  name: string;
  boardSize: string;
  fleet: string;
  placementNoTouch: boolean;
  extraTurnOnHit: boolean;
};

const EMPTY_FORM: RulesetForm = {
  id: '',
  name: '',
  boardSize: '10',
  fleet: '5,4,3,3,2',
  placementNoTouch: false,
  extraTurnOnHit: true,
};

function fleetToText(fleet: number[]): string {
  return fleet.join(',');
}

function parseFleet(input: string): number[] {
  const parts = input
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => Number(item));

  if (parts.length === 0 || parts.some((value) => !Number.isInteger(value) || value <= 0)) {
    throw new Error('Флот должен быть задан через запятую: только положительные целые, например 5,4,3,3,2');
  }

  return parts;
}

function normalizeRulesets(items: RulesetDTO[]): RulesetDTO[] {
  return [...items].sort((a, b) => {
    const scoreA = a.is_active ? 0 : 1;
    const scoreB = b.is_active ? 0 : 1;
    if (scoreA !== scoreB) {
      return scoreA - scoreB;
    }
    return a.id.localeCompare(b.id);
  });
}

export function RulesetsPage() {
  const [rulesets, setRulesets] = useState<RulesetDTO[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [form, setForm] = useState<RulesetForm>(EMPTY_FORM);
  const [cloneId, setCloneId] = useState('');
  const [cloneName, setCloneName] = useState('');

  const [statusText, setStatusText] = useState('Загрузка профилей правил...');
  const [errorText, setErrorText] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const selectedRuleset = useMemo(
    () => rulesets.find((item) => item.id === selectedId) ?? null,
    [rulesets, selectedId],
  );

  function applySelectedToForm(ruleset: RulesetDTO | null) {
    if (!ruleset) {
      return;
    }

    setForm({
      id: ruleset.id,
      name: ruleset.name,
      boardSize: String(ruleset.board_size),
      fleet: fleetToText(ruleset.fleet),
      placementNoTouch: ruleset.placement_no_touch,
      extraTurnOnHit: ruleset.extra_turn_on_hit,
    });
  }

  async function refreshRulesets(nextSelectedId?: string) {
    const items = normalizeRulesets(await getRulesetsWithArchived());
    setRulesets(items);
    const targetSelectedId = nextSelectedId ?? selectedId;

    if (!targetSelectedId && items.length > 0) {
      setSelectedId(items[0].id);
      applySelectedToForm(items[0]);
      return;
    }

    const selected = items.find((item) => item.id === targetSelectedId);
    if (selected) {
      setSelectedId(selected.id);
      applySelectedToForm(selected);
    }
  }

  useEffect(() => {
    let mounted = true;

    refreshRulesets()
      .then(() => {
        if (mounted) {
          setStatusText('Готово к управлению профилями правил.');
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
  }, []);

  function onSelectRuleset(ruleset: RulesetDTO) {
    setSelectedId(ruleset.id);
    applySelectedToForm(ruleset);
    setErrorText(null);
  }

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

  async function onCreateRuleset() {
    await withBusy(async () => {
      const payload = {
        id: form.id.trim(),
        name: form.name.trim(),
        board_size: Number(form.boardSize),
        fleet: parseFleet(form.fleet),
        placement_no_touch: form.placementNoTouch,
        extra_turn_on_hit: form.extraTurnOnHit,
      };
      await createRuleset(payload);
      setStatusText(`Профиль правил ${payload.id} создан.`);
      setSelectedId(payload.id);
      await refreshRulesets(payload.id);
    });
  }

  async function onUpdateRuleset() {
    if (!selectedRuleset) {
      return;
    }

    await withBusy(async () => {
      const payload = {
        name: form.name.trim(),
        board_size: Number(form.boardSize),
        fleet: parseFleet(form.fleet),
        placement_no_touch: form.placementNoTouch,
        extra_turn_on_hit: form.extraTurnOnHit,
      };

      await updateRuleset(selectedRuleset.id, payload);
      setStatusText(`Профиль правил ${selectedRuleset.id} обновлён.`);
      await refreshRulesets();
    });
  }

  async function onCloneRuleset() {
    if (!selectedRuleset) {
      return;
    }

    await withBusy(async () => {
      const newId = cloneId.trim();
      const newName = cloneName.trim();
      await cloneRuleset(selectedRuleset.id, { new_id: newId, new_name: newName });
      setStatusText(`Профиль правил ${selectedRuleset.id} клонирован в ${newId}.`);
      setCloneId('');
      setCloneName('');
      await refreshRulesets();
    });
  }

  async function onActivateRuleset() {
    if (!selectedRuleset) {
      return;
    }

    await withBusy(async () => {
      await activateRuleset(selectedRuleset.id);
      setStatusText(`Профиль правил ${selectedRuleset.id} активирован.`);
      await refreshRulesets();
    });
  }

  async function onArchiveRuleset() {
    if (!selectedRuleset) {
      return;
    }

    await withBusy(async () => {
      await archiveRuleset(selectedRuleset.id);
      setStatusText(`Профиль правил ${selectedRuleset.id} архивирован.`);
      await refreshRulesets();
    });
  }

  function onResetCreateForm() {
    setSelectedId('');
    setForm(EMPTY_FORM);
    setErrorText(null);
  }

  return (
    <section className="screen-layout">
      <aside className="panel controls">
        <h2>Профили правил</h2>

        <button type="button" className="ghost-btn" onClick={onResetCreateForm}>
          Новая форма профиля
        </button>

        <label>
          ID
          <input
            aria-label="ID профиля правил"
            value={form.id}
            onChange={(event) => setForm((prev) => ({ ...prev, id: event.target.value }))}
            disabled={Boolean(selectedRuleset)}
          />
        </label>

        <label>
          Название
          <input
            aria-label="Название профиля правил"
            value={form.name}
            onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
          />
        </label>

        <label>
          Размер поля
          <input
            aria-label="Размер поля"
            value={form.boardSize}
            onChange={(event) => setForm((prev) => ({ ...prev, boardSize: event.target.value }))}
          />
        </label>

        <label>
          Флот
          <input
            aria-label="Флот"
            value={form.fleet}
            onChange={(event) => setForm((prev) => ({ ...prev, fleet: event.target.value }))}
          />
        </label>

        <label>
          <input
            type="checkbox"
            checked={form.placementNoTouch}
            onChange={(event) => setForm((prev) => ({ ...prev, placementNoTouch: event.target.checked }))}
          />
          Запрет соприкосновения кораблей
        </label>

        <label>
          <input
            type="checkbox"
            checked={form.extraTurnOnHit}
            onChange={(event) => setForm((prev) => ({ ...prev, extraTurnOnHit: event.target.checked }))}
          />
          Дополнительный ход при попадании
        </label>

        <div className="button-row">
          <button type="button" onClick={onCreateRuleset} disabled={isBusy || Boolean(selectedRuleset)}>
            Создать
          </button>
          <button type="button" onClick={onUpdateRuleset} disabled={isBusy || !selectedRuleset}>
            Сохранить
          </button>
          <button
            type="button"
            className="ghost-btn"
            onClick={onActivateRuleset}
            disabled={isBusy || !selectedRuleset || Boolean(selectedRuleset?.is_active)}
          >
            Активировать
          </button>
          <button
            type="button"
            className="ghost-btn"
            onClick={onArchiveRuleset}
            disabled={isBusy || !selectedRuleset || Boolean(selectedRuleset?.is_archived)}
          >
            Архивировать
          </button>
        </div>

        <hr className="divider" />

        <label>
          ID клона
          <input aria-label="ID клона" value={cloneId} onChange={(event) => setCloneId(event.target.value)} />
        </label>

        <label>
          Название клона
          <input aria-label="Название клона" value={cloneName} onChange={(event) => setCloneName(event.target.value)} />
        </label>

        <button
          type="button"
          onClick={onCloneRuleset}
          disabled={isBusy || !selectedRuleset || !cloneId.trim() || !cloneName.trim()}
        >
          Клонировать выбранный
        </button>

        <div className="status" data-testid="rulesets-status-text">
          {statusText}
        </div>

        {errorText && <div role="alert">{errorText}</div>}
      </aside>

      <div className="screen-content">
        <section className="panel">
          <h3>Каталог профилей правил</h3>
          <table className="data-table" data-testid="rulesets-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Название</th>
                <th>Флот</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {rulesets.map((item) => {
                const isSelected = item.id === selectedId;
                const statuses = [item.is_active ? 'активен' : '', item.is_archived ? 'в архиве' : '']
                  .filter(Boolean)
                  .join(', ') || 'обычный';

                return (
                  <tr key={item.id}>
                    <td>
                      <button type="button" className={isSelected ? 'mini-btn' : 'mini-btn ghost-btn'} onClick={() => onSelectRuleset(item)}>
                        {item.id}
                      </button>
                    </td>
                    <td>{item.name}</td>
                    <td>{fleetToText(item.fleet)}</td>
                    <td>{statuses}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      </div>
    </section>
  );
}
