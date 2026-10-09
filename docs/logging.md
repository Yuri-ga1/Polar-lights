# Централизованное логирование

Python использует стандартный `logging` через общий модуль `app/logging_config.py`.
Логгеры `app.backend.*` пишут в `logs/backend/backend.jsonl`, `app.frontend.*` —
в `logs/frontend/frontend.jsonl`, остальные `app.*` — в `logs/pipeline/pipeline.jsonl`.
Корневой логгер Python не перенастраивается; сторонние библиотеки не засоряют журналы.
Frontend отправляет события асинхронными пакетами в `POST /api/v1/logs`.

## Запуск и настройки

CLI `main.py`, CLI солнечного диска, фабрика FastAPI, дочерние процессы заданий,
публичные pipeline/plotting-функции и обе тетради подключают логирование.
Повторный вызов `configure_logging()` сохраняет существующие обработчики.
Настройка не выполняется при импорте. Для отдельных вызовов Downloader/Processor
в собственной тетради или скрипте сначала вызовите:

```python
from app.logging_config import LoggingConfig, configure_logging
configure_logging(LoggingConfig(console=False))  # Файлы продолжают записываться.
```

Явно переданный `LoggingConfig` заменяет конфигурацию. После изменения переменных
окружения в работающей тетради используйте `configure_logging(force=True)`.

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `POLAR_LOG_DIR` | `logs` | Каталог относительно рабочей директории |
| `POLAR_LOG_FRONTEND_LEVEL` | `INFO` | Порог сохранения frontend |
| `POLAR_LOG_BACKEND_LEVEL` | `INFO` | Порог backend |
| `POLAR_LOG_PIPELINE_LEVEL` | `INFO` | Порог pipeline |
| `POLAR_LOG_MAX_BYTES` | `20971520` | Размер текущего файла |
| `POLAR_LOG_RETENTION_DAYS` | `30` | Срок хранения gzip-архивов |
| `POLAR_LOG_CONSOLE` | `true` | Читаемый вывод в stderr |
| `POLAR_LOG_FILES` | `true` | Запись файлов |
| `VITE_LOG_LEVEL` | `INFO` | Порог браузерного логгера при сборке |

Булевы параметры включаются значениями `true`, `1`, `yes`. Уровни: `DEBUG`, `INFO`,
`WARNING`, `ERROR`, `CRITICAL`. Все процессы должны использовать один абсолютный
`POLAR_LOG_DIR` и одинаковые параметры ротации. Новых зависимостей нет.

## Схема и связь событий

Обязательны UTC timestamp с миллисекундами, level, service, module, event и message.
Идентификаторы событий — snake_case, технические сообщения — английские.
Дополнительные поля: `request_id`, `job_id`, `run_id`, `duration_ms`, `context`, `error`.
`error` содержит тип, сообщение, доступный код и стек исключения.
Старые вызовы стандартного логгера без `event` получают `diagnostic_message`.

Иллюстративные события:

```json
{"timestamp":"2026-10-09T08:15:32.421Z","level":"INFO","service":"frontend","module":"app.frontend.workspace","event":"job_accepted","message":"Background job accepted","request_id":"req-123","job_id":"job-456","context":{"untrusted_client":true}}
{"timestamp":"2026-10-09T08:15:32.422Z","level":"INFO","service":"backend","module":"app.backend.api","event":"request_completed","message":"Request completed","request_id":"req-123","duration_ms":12.5,"context":{"method":"POST","path":"/api/v1/data","status":202}}
{"timestamp":"2026-10-09T08:15:33.421Z","level":"INFO","service":"pipeline","module":"app.omni.omni_processor","event":"processing_completed","message":"Stage completed","request_id":"req-123","job_id":"job-456","duration_ms":31.2,"context":{"source":"omni","records":1440}}
```

Frontend передаёт `X-Request-ID`. Backend принимает только безопасный идентификатор
длиной до 64 символов, иначе генерирует свой, и возвращает его, включая ответы
401/413/500. Контекст сбрасывается после запроса. CORS разрешает этот заголовок.
Происхождение задания хранится в SQLite `job_context`, поэтому `request_id` и
`job_id` восстанавливаются в отдельном процессе. Пользовательский `LoggingConfig`
также передаётся spawned worker, включая каталог и уровни. Самостоятельный pipeline получает
`run_id`, а его рабочие потоки — копию контекста. Для своего сценария:

```python
from app.logging_config import log_context
with log_context(run_id="experiment-42"):
    # Все app.* события в этом контексте связаны с экспериментом.
    ...
```

## Ротация, надёжность и ограничения

Перед записью проверяются дата UTC и размер. Файл закрывается и сжимается при
смене суток или превышении 20 МиБ следующей записью. Имя архива:
`pipeline.YYYY-MM-DD.<uuid>.jsonl.gz`; несколько ротаций за день не перезаписываются.
Архив сначала создаётся во временном файле. Межпроцессная блокировка постоянного
sidecar-файла охватывает ротацию, запись и очистку. Текущий файл открывается заново
для каждой записи; устаревших открытых дескрипторов после ротации нет.
Используются `flock` на Unix и `msvcrt.locking` на Windows.

Очистка архивов старше 30 дней выполняется при первой записи процесса, затем
не чаще раза в час. Ротация по времени и очистка происходят при следующем событии,
а не отдельным ночным таймером. Для локального диска проверена запись и ротация
четырьмя процессами. Семантика блокировок на NFS/сетевых файловых системах и ветка
Windows в этой среде не проверялись.

Это best-effort журнал: отказ диска, сериализации или ожидание блокировки свыше
двух секунд приводит к пропуску события, вычисления продолжаются. Сжатие выполняется
синхронно под блокировкой. Не гарантируется сохранение последнего события при
аварийном отключении питания; после сбоя в момент завершения ротации возможен
дублирующий архив. Это не аудит с гарантированной доставкой.

Массивы/DataFrame не сериализуются; записываются тип, число строк или размерность.
Коллекции и строки ограничены, рекурсивные структуры обрезаются. Секретные ключи,
известные секреты из окружения, email, Bearer credentials и query URL удаляются.
Не передавайте секреты в свободный текст: автоматическая санитизация не способна
распознать произвольную неизвестную строку как пароль.

## Frontend и доступ

События: глобальные JS/Promise ошибки, ошибки API, запуск/завершение/отмена загрузки
и рендера, удаление графика, ошибки Plotly/MapLibre. Нет логирования движений мыши,
точек данных или каждого шага polling. Очередь ограничена 100 событиями; каждые
две секунды отправляется до 20 событий и до 60 КБ UTF-8. Неудачные пакеты теряются
без повторов и рекурсивного логирования. При закрытии страницы используется
`keepalive`; доставка всё равно не гарантируется. Mock-режим отключает отправку.

Endpoint использует существующий `POLAR_API_KEY`, проверяет Origin, отклоняет
неизвестные поля/уровни/компоненты, ограничивает тело 64 КиБ и пакет 20 событиями.
Лимит — 60 пакетов в минуту на весь backend, общий для всех процессов через SQLite.
Он намеренно глобальный, без неограниченного словаря пользовательских IP.
При выключенном API-ключе сохраняется существующий режим локального API; для
публичного размещения используйте его штатную авторизацию.

Через Vite сохраняется исходный Host, поэтому Origin совпадает. При раздельных
origin задайте `POLAR_CORS_ORIGINS` с точным адресом интерфейса. В production
reverse proxy должен сохранять Host либо origin должен быть явно разрешён.
Штатный способ авторизации frontend — same-origin proxy, добавляющий ключ.
Встраиваемый клиент также может передать ключ в память через `setApiKey()`;
он используется одинаково для API и телеметрии, не сохраняется в localStorage
и не включается в события. Не встраивайте секрет в `VITE_*`.

Временная метка frontend сохраняется как недоверенный `context.client_timestamp`;
основная метка — серверная. Клиентские идентификаторы пригодны для корреляции,
но не являются доказательством принадлежности запроса или задания.

## Добавление событий и просмотр

```python
from app.logging_config import get_logger
logger = get_logger(__name__)  # Модуль должен находиться в app.*.
logger.info("Cache inspected", extra={
    "event": "cache_hit",
    "context": {"source": "omni", "product": "solar-wind"},
})
# В обработчике исключения на уровне, который отвечает за ошибку:
# logger.exception("Processing failed", extra={"event": "processing_failed"})
```

Для крупных этапов используйте `@logged_stage("processing")`, для самостоятельных
точек входа — `@logged_stage("pipeline", entry=True)`. Не декорируйте обработку
каждой точки или timestamp карты. Исключение записывает отвечающий за него уровень:
самостоятельный этап, HTTP boundary или job worker. Пропуски данных и ожидаемые
4xx не превращаются автоматически в ERROR. Прогресс в журнале — не чаще раза
в 30 секунд, отдельный интерактивный ProgressBar сохранён.

```sh
tail -f logs/pipeline/pipeline.jsonl
jq 'select(.level == "ERROR")' logs/backend/backend.jsonl
jq 'select(.job_id == "job-456")' logs/*/*.jsonl
zcat logs/pipeline/*.jsonl.gz | jq 'select(.event == "processing_completed")'
```

## Аудит print и проверки

Технические `print()` заменены в BaseDownloader, SIMuRG client/downloader,
GIM downloader/processor, NMDB metadata, ObservationLinksFinder/Parser,
observation_workflow и plot_constructor_data_loader. Ошибки IONEX теперь содержат
структурированное исключение. Диагностика GIRO и ограниченный прогресс добавлены
без изменения алгоритмов загрузки и обработки.

Сохранены три пользовательских `print()`:
- `backend/setup_render.py`: CLI выдаёт JSON-манифест.
- `pipeline/solar_disk_pipeline.py`: CLI выдаёт путь результата.
- `pipeline/observation_pipeline.py`: интерактивная сводка числа наблюдений;
  структурированная копия имеет DEBUG, чтобы не дублировать обычный вывод.

`display()`, вывод DataFrame, графики и существующие ячейки результатов не менялись.
В тетради добавлена только ячейка настройки после bootstrap импортов.

Проверки: `python -m pytest -q tests`, `cd frontend && npm test`, `npm run build`.
До изменения в checkout не было Python-тестов и файлов frontend-тестов, хотя README
упоминает прежние suites. Новые тесты покрывают схему, разделение, уровни, ротацию,
gzip/очистку, процессы, контекст, исключения, frontend validation/auth/rate/size,
повторную настройку, пользовательский вывод, отказ диска, локальный кэш, сохранение
научного DataFrame, CORS и клиентскую очередь. Сетевые загрузки внешних научных
источников и полный запуск тетрадей не выполнялись.

## Результаты проверки реализации

- Python: **23 passed** (17,75 с), включая четыре конкурентных процесса и отдельный spawned job worker.
- Frontend: **4 passed**.
- `npm run build` и `npm run lint`: успешно.
- Ruff для новых Python-модулей и тестов, проверка неопределённых имён в `app`, `compileall` и `git diff --check`: успешно.
- Некритичные предупреждения: Starlette о будущем переходе TestClient с httpx на httpx2; Vite о крупных chunks существующих графических библиотек.
- FastAPI TestClient проверен вне ограниченной песочницы: её ограничения мешают запуску внутреннего event loop. Внешние сервисы тесты не вызывают.

## Изменённые и созданные файлы

- [.gitignore](../.gitignore)
- [README.md](../README.md)
- [app/backend/adapters.py](../app/backend/adapters.py)
- [app/backend/api.py](../app/backend/api.py)
- [app/backend/frontend_logs.py](../app/backend/frontend_logs.py)
- [app/backend/jobs.py](../app/backend/jobs.py)
- [app/backend/logging.py](../app/backend/logging.py)
- [app/backend/maps.py](../app/backend/maps.py)
- [app/base_classes/base_downloader.py](../app/base_classes/base_downloader.py)
- [app/base_classes/base_processor.py](../app/base_classes/base_processor.py)
- [app/gfz/gfz_downloader.py](../app/gfz/gfz_downloader.py)
- [app/gfz/gfz_processor.py](../app/gfz/gfz_processor.py)
- [app/ionosonde/ionosonde_downloader.py](../app/ionosonde/ionosonde_downloader.py)
- [app/ionosonde/ionosonde_processor.py](../app/ionosonde/ionosonde_processor.py)
- [app/kyoto/kyoto_dst_downloader.py](../app/kyoto/kyoto_dst_downloader.py)
- [app/kyoto/kyoto_dst_processor.py](../app/kyoto/kyoto_dst_processor.py)
- [app/logging_config.py](../app/logging_config.py)
- [app/nmdb/nmdb_downloader.py](../app/nmdb/nmdb_downloader.py)
- [app/nmdb/nmdb_processor.py](../app/nmdb/nmdb_processor.py)
- [app/observation/aurorasaurus_downloader.py](../app/observation/aurorasaurus_downloader.py)
- [app/observation/observation_links_finder.py](../app/observation/observation_links_finder.py)
- [app/observation/observation_parser.py](../app/observation/observation_parser.py)
- [app/omni/omni_downloader.py](../app/omni/omni_downloader.py)
- [app/omni/omni_processor.py](../app/omni/omni_processor.py)
- [app/pipeline/adjusted_tec_pipeline.py](../app/pipeline/adjusted_tec_pipeline.py)
- [app/pipeline/aurora_pipeline.py](../app/pipeline/aurora_pipeline.py)
- [app/pipeline/main_pipeline.py](../app/pipeline/main_pipeline.py)
- [app/pipeline/misc_pipeline.py](../app/pipeline/misc_pipeline.py)
- [app/pipeline/observation_pipeline.py](../app/pipeline/observation_pipeline.py)
- [app/pipeline/observation_workflow.py](../app/pipeline/observation_workflow.py)
- [app/pipeline/plot_constructor_data_loader.py](../app/pipeline/plot_constructor_data_loader.py)
- [app/pipeline/roti_pipeline.py](../app/pipeline/roti_pipeline.py)
- [app/pipeline/solar_disk_pipeline.py](../app/pipeline/solar_disk_pipeline.py)
- [app/pipeline/space_weather_pipeline.py](../app/pipeline/space_weather_pipeline.py)
- [app/progress_bar.py](../app/progress_bar.py)
- [app/simurg/gim_downloader.py](../app/simurg/gim_downloader.py)
- [app/simurg/gim_processor.py](../app/simurg/gim_processor.py)
- [app/simurg/simurg_client.py](../app/simurg/simurg_client.py)
- [app/simurg/simurg_downloader.py](../app/simurg/simurg_downloader.py)
- [app/simurg/simurg_processor.py](../app/simurg/simurg_processor.py)
- [app/solar/solar_downloader.py](../app/solar/solar_downloader.py)
- [app/solar/solar_processor.py](../app/solar/solar_processor.py)
- [app/visualization/aurora_map_plotter.py](../app/visualization/aurora_map_plotter.py)
- [app/visualization/cosmic_ray_plotter.py](../app/visualization/cosmic_ray_plotter.py)
- [app/visualization/gim_plotter.py](../app/visualization/gim_plotter.py)
- [app/visualization/ionosonde_plotter.py](../app/visualization/ionosonde_plotter.py)
- [app/visualization/keogram_plotter.py](../app/visualization/keogram_plotter.py)
- [app/visualization/plot_constructor.py](../app/visualization/plot_constructor.py)
- [app/visualization/roti_plotter.py](../app/visualization/roti_plotter.py)
- [app/visualization/solar_and_indexes_plotter.py](../app/visualization/solar_and_indexes_plotter.py)
- [app/visualization/solar_disk_plotter.py](../app/visualization/solar_disk_plotter.py)
- [docs/logging.md](../docs/logging.md)
- [frontend/src/api/client.ts](../frontend/src/api/client.ts)
- [frontend/src/logging.ts](../frontend/src/logging.ts)
- [frontend/src/main.tsx](../frontend/src/main.tsx)
- [frontend/src/renderTasks.ts](../frontend/src/renderTasks.ts)
- [frontend/src/requests.ts](../frontend/src/requests.ts)
- [frontend/src/visualizations/MapView.tsx](../frontend/src/visualizations/MapView.tsx)
- [frontend/src/visualizations/PlotView.tsx](../frontend/src/visualizations/PlotView.tsx)
- [frontend/tests/logging.test.ts](../frontend/tests/logging.test.ts)
- [frontend/tests/setup.ts](../frontend/tests/setup.ts)
- [frontend/vite.config.ts](../frontend/vite.config.ts)
- [main.py](../main.py)
- [notebooks/00_examples_and_run.ipynb](../notebooks/00_examples_and_run.ipynb)
- [notebooks/01_plot_constructor.ipynb](../notebooks/01_plot_constructor.ipynb)
- [tests/test_logging.py](../tests/test_logging.py)
