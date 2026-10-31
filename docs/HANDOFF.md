> Latest autonomous Market Brain work: read docs/BRAIN-EVIDENCE-HANDOFF.md first. Existing PAPER services are preserved; no profitable candidate has been established.

# Передача проекта другим ИИ — 30 октября 2026

## С чего начать

1. Прочитать `AGENTS.md`, `docs/SERVER.md`, этот файл.
2. Проверить `git status --short`, `git fetch origin`, `git log -3 --oneline`.
   При чистой рабочей папке обновляться через `git pull --ff-only`.
   Если есть чужие правки — сначала сохранить и сопоставить; не делать reset --hard.
3. Задание: `docs/CODEX-ADAPTIVE-BOT-TASK-2026-10-30.md`.
   Все 10 пользовательских гипотез: `docs/USER-TRADING-IDEAS.md`.
4. Реальный результат и ограничения: `docs/ADAPTIVE-REPORT-2026-10-30.md`;
   компактные результаты с протоколом: `docs/adaptive-results-2026-10-30.json`.

## Где продолжать

- GitHub: `https://github.com/fermiums22/cripto_staff`, ветка `main`.
- Домашний сервер, CT 103: `/home/codex/workspace/cripto_staff`, пользователь `codex`.
  Здесь находятся актуальные данные, модели, отчёты и запущенные сервисы.
- Основная рабочая папка Windows: `D:\w_spase\cripto_staff`.
- Дополнительная синхронизированная копия: `C:\Users\v.taranov\cripto_staff-adaptive`.
  Она была создана при заполнении D:. Не вести независимые правки в двух копиях.
- Доступ к серверу только по SSH согласно `docs/SERVER.md`; не управлять рабочим
  столом владельца, не трогать HA/TrueNAS/VPN/Nika.

## Что работает

- Новый read-only дашборд: `http://192.168.0.8:8765/adaptive` (дом/VPN).
  Старый дашборд и исследования: `http://192.168.0.8:8765/`.
- `cripto-adaptive.service` получает публичные данные 20 инструментов.
  Общий виртуальный кошелёк $15 сохраняется в SQLite. Реальных ордеров нет.
- **Входы отключены критерием отбора**, а не неисправностью: выбранный
  `leadlag_trail_0.003` потерял деньги и на train, и на validation.
  На момент передачи: $15, без позиций, свежие данные, без ошибки цикла.
- Контрольный тест: базовый $12.6677, оптимистичный $15.0112, стресс $10.3494.
  $30/$100/$2000 не достигнуты. Не выдавать это за прибыльную стратегию.
- Старые PAPER-сервисы и их балансы сохранены. Новая служба соблюдает общую паузу.
- Кнопка «График» в Telegram показывает живой кошелёк адаптивного бота,
  свежесть данных и допуск входов. Источник — `artifacts/adaptive_live.json`;
  построение — `dashboard.graph_png()`, отправка — `telegram_control.py`.
- Telegram «Статус» и уведомления также относятся только к адаптивному PAPER.
  Его события сохраняются атомарно с кошельком в `data/adaptive.sqlite3.events`,
  затем один раз переносятся в общий журнал через `adaptive_bridge`.
  Подписки сохранены; старые стратегии не рассылаются, сделки задним числом
  не восстанавливаются по счётчикам. Устаревший `top_bot_feed.py` удалён.

## Код и сохранённое состояние

- `adaptive_engine.py`: кошелёк, сигналы, риск, комиссии, funding, stop/trailing,
  приближённая ликвидация, историческая симуляция.
- `adaptive_research.py`: аудит данных, 24 кандидата, хронологический отбор,
  фиксация протокола до теста, абляции на validation, сценарии издержек/плеча.
- `adaptive_live.py`: только публичные GET, один процесс, транзакционный кошелёк,
  свежесть котировок, восстановление без сброса капитала; live ограничен 1x.
- `dashboard.py`, `web/adaptive.*`, `deploy/cripto-adaptive.service`.
- На сервере: `artifacts/adaptive_research.json`, `adaptive_protocol.json`,
  `adaptive_live.json`, `adaptive_delivery_report.md`; `data/adaptive.sqlite3`.
- История: `data/portfolio/*.json.gz` (linear 15m), `data/research.sqlite3`
  (spot 1m), `data/market_stream/` (ограниченное хранение публичного потока).
- Эти рабочие данные, секреты и ключи исключены из Git. Синхронизация Git не
  означает копирование живых баз или секретов на другие компьютеры. Для работы
  с историей использовать сервер; не заменять его базы локальными старыми копиями.

## Проверено

На сервере: `.venv/bin/python -m unittest discover -s tests` — 83 теста прошли.
`node --check web/adaptive.js` — пройдено на Windows. Шесть HTTP-маршрутов,
read-only API, запрет доступа к секретам через HTTP и сохранение кошелька при
перезапуске проверены. Браузерный скриншот заблокирован политикой инструмента;
визуальная проверка desktop/mobile не выполнена.

Домашние исследовательские скрипты и локальные ranker/microstructure-тесты
сохранены отдельным коммитом `23d899d`; новая реализация — `2488c91`.
Результат Claude не использовался; его запуск агентом не выполнялся. Необязательный
короткий промпт для второго ревью: `docs/CLAUDE-ADAPTIVE-REVIEW.md`.

## Что осталось

- Прибыльная стратегия не получена. Не снимать gate ради видимости активности.
- История ранее изучалась; текущий holdout не является нетронутой выборкой.
  Не подбирать параметры на нём. Для нового исследования зафиксировать новую
  версию протокола и будущий период; текущие отчёты и кошелёк не перезаписывать.
- Микроструктура пока только аудирована на реально сохранённых сессиях:
  валидированного торгового сигнала нет. Для новостей и сравнения задержек
  сайта/API недостаточно подходящей point-in-time истории.
- Комиссии других монет — сценарные; исторические правила, глубина исполнения
  и механика ликвидаций не воспроизведены полностью. Подробности в отчёте.
- Сделать визуальную проверку на телефоне/desktop и независимое ревью движка.
- Не запускать старые 20d/oracle-скрипты вслепую: некоторые перезаписывают
  исследовательские HTML-артефакты; их результаты не являются live-торговлей.

После любых новых правок: узкие тесты, коммит, push; на другой машине — сначала
проверка незакоммиченного состояния и fast-forward. Секреты в Git не добавлять.


## A/B/C $15 execution experiment (2026-10-31)

Concrete comparison completed; see docs/THREE-HYPOTHESES-2026-10-31.md and
three-hypotheses-2026-10-31.json/.csv. Modules research/hypothesis_a,b,c and
research.compare; isolated wallets, no live orders or production changes.
Train Oct2, early Oct3, execution Oct4-5, ALL DEVELOPMENT previously examined.
A 18trades: midgross+.05016, net-.273465; B rule19: -.429556; C rule9: -.165594.
XGBoost/MLP B/C hit ~10% drawdown stop with net around-$1.50. All stress/slow
variants nonpositive. CASH wins. BTC min lot observed >=$84.6773 unavailable
at $15/1x; SOL baseline mostly unavailable at $12 cap. No PAPER candidate.
Archive receive time is simulated, 1s top10 alt execution/5s BTC snapshots;
lot rules are snapshot scenario. Do not call this independent or exact-tick proof.
Leader reaction lags1..120s saved with actual snapshot offsets. Prior raw leader
study Oct2-5 completed:42 BTC/ETH events, no aligned positive net group.
Storage three-hypotheses-v3 includes checkpoints, models, costs, trade journal,
reactions, artifacts.json; resume command in report verified checksum-only no rerun.
v1/v2 preserved: JSON serialization and summary CASH-prefix defects corrected
through checkpoint recovery; trading results and model parameters verified
identical, no retraining/parameter search.12 narrow tests pass. Six cripto
services remain active; unrelated dirty files untouched. Broad profit goal
remains unachieved; latest bounded task has measured negative evidence.
Do not repeat these experiments or expand population; new information or a
new justified mechanism needs a separately frozen protocol and prospective
validation before any promotion.
