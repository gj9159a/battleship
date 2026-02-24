# Battleship

Desktop-first приложение (Windows 11) для игры в Морской бой против бота, тренировки ботов и ведения лиги.

## Текущий статус

Проект **готов для локального запуска MVP**:
- backend API (FastAPI, REST + WS)
- frontend UI (Game / Training / League / Rulesets / Bots)
- desktop shell (Tauri) с автозапуском backend
- тренировка job lifecycle (start/pause/resume/stop), checkpoints, управление через UI
- league с TrueSkill и сортировкой по `mu - 3*sigma`

## Быстрый старт (Windows 11, dev)

### 1) Предусловия
- Python 3.11+
- Node.js 20+
- Rust (stable) + Cargo
- Microsoft WebView2 Runtime

### 2) Установка зависимостей
```powershell
powershell -ExecutionPolicy Bypass -File scripts/windows/setup-dev.ps1
```

### 3) Запуск desktop приложения
```powershell
powershell -ExecutionPolicy Bypass -File scripts/windows/run-desktop-dev.ps1
```

Приложение поднимет frontend dev-сервер и откроет Tauri окно. Backend стартует автоматически из desktop-процесса.

## Проверка готовности

Backend tests:
```bash
cd backend
PYTHONPATH=. pytest -s
```

Frontend tests:
```bash
cd frontend
npm run test -- --run
npm run build
```

Desktop check:
```bash
cd desktop/src-tauri
cargo check
```

## Что уже можно делать в UI
- `Game`: играть матч против бота
- `Training`: создать job, управлять lifecycle, смотреть метрики и checkpoints
- `League`: регистрировать ботов, запускать season job, смотреть таблицу/матрицу
- `Rulesets`: создать/клонировать/редактировать/архивировать/активировать ruleset
- `Bots`: промоутить checkpoints в bot versions, импортировать в лигу, выбрать seed bot

## Ограничения текущего MVP
- Trainer использует реальную self-play симуляцию матчей `strong vs baseline/active` c эволюционной мутацией весов.
- Desktop CI проверяет `cargo check`; полноценная упаковка инсталлятора пока не включена в pipeline.
