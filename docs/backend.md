# Polar Lights backend

Backend запускается отдельно от `main.py`. Тетради, `PlotConstructor` и существующие
пайплайны сохраняют прежние интерфейсы. HTTP routes вызывают сервисы, а сервисы —
существующие Downloader/Processor. Парсинга научных файлов в routes нет.

## Установка и запуск

```bash
poetry install --extras backend
poetry run uvicorn app.backend.api:create_app --factory --host 127.0.0.1 --port 8000
# В отдельном терминале:
poetry run python -m app.backend.worker
```

Документация: `http://127.0.0.1:8000/docs`, схема: `/openapi.json`.
Backend-зависимости выделены в optional extra: обычная установка для тетрадей не
требует FastAPI, Arrow или браузера. Существующие версии пакетов в lock-файле сохранены.

| Переменная окружения | Назначение |
|---|---|
| `POLAR_DATA_ROOT` | Корень хранилища, по умолчанию `files` |
| `SIMURG_EMAIL` | Учётная запись для получения отсутствующих ROTI/TEC-карт |
| `POLAR_API_KEY` | Если задан, все HTTP-запросы требуют `X-API-Key` |
| `POLAR_CORS_ORIGINS` | Разрешённые origins через запятую, по умолчанию CORS выключен |
| `POLAR_RENDER_ASSETS` | Каталог закреплённых MapLibre assets, по умолчанию `files/render-assets` |
| `PLAYWRIGHT_BROWSERS_PATH` | Необязательный каталог браузеров Playwright |

Остальные ограничения задаются через `Settings` при создании приложения: 366 дней
для рядов, 200 000 строк, 1 000 000 ячеек, 2 000 000 точек карты, 64 MiB ответа,
64 KiB тела запроса, 32 активных/ожидающих задания, два worker-процесса и 1800 секунд
для временных рядов; длительные операции — 12 часов. Ограничение кеограммы —
три календарные даты и тот же лимит ячеек. Подробности: [worker](worker.md).

Для публичного развёртывания задайте API key, разрешённые origins и HTTPS на reverse
proxy. SQLite-очередь и file locks рассчитаны на несколько ASGI workers **одного
хоста с локальным диском**. Это не распределённая очередь для нескольких машин/NFS.

## Поддерживаемые продукты

| productId | Данные / естественная или явно выбранная частота |
|---|---|
| `omni` | `omni_bx/by/bz`, `omni_speed`, `omni_proton_density`, `omni_flow_pressure`, `omni_ae`, `omni_sym_h`; 60 s |
| `kp` | `kp`; 3 h |
| `kyoto-dst` | `kyoto_dst`; 1 h |
| `nmdb` | `nmdb_<station>_counts`; абсолютные отсчёты NMDB с явно выбранным 10-минутным разрешением |
| `giro` | `giro_al945_fof2`, `giro_al945_hmf2`; политика станции AL945 450 s |
| `timeseries` | Совместный запрос колонок разных источников |
| `roti-map`, `tec-adjusted-map`, `gim-map` | Один точный timestamp, Arrow IPC по умолчанию; GIM типа UQRG |
| `roti-keogram`, `tec-adjusted-keogram` | Потоковая кеограмма по существующему алгоритму тетрадей |

Каталог содержит только реализованные продукты. Для GIRO сейчас зарегистрирована
станция AL945; добавление другой станции требует её явной frequency policy и
адаптера. Неизвестная частота не угадывается из общих min/max данных.
Для NMDB допустимы коды станций из 3–6 букв/цифр; источник подтверждает их наличие.
Catalog/availability включают уже известные колонки и станции.

OMNI BX/BY/BZ — GSE, как в существующем Downloader. NMDB-кэш тетрадей содержит
амплитуды относительно медианы окна. Его нельзя переименовать в абсолютные
отсчёты: backend использует суффикс `_counts` и не импортирует старый `nmdb.csv`.
Отсчёты с частотой 10 минут и 450 секунд — отдельные политики источников, не общая
сетка для всех данных. API не выполняет interpolation/ffill/bfill.

## HTTP-контракт

`GET /api/v1/catalog` возвращает продукты, типы графиков, поля формы, defaults,
допустимые значения, единицы, частоты и capabilities. Типизированные схемы запросов,
catalog, availability и job status доступны в OpenAPI для генерации TypeScript.

`GET /api/v1/products/{productId}/availability?start=...&end=...&offset=0&limit=1000`
возвращает интервалы заполненных колонок либо timestamps карт. Пагинация ограничена
5000 элементами; `nextOffset` указывает следующую страницу. Значения измерений и
raw-файлы через этот endpoint не передаются. Метаданные кэшируются до изменения
файла; индекс HDF5 инвалидируется по размеру и времени изменения.

```http
POST /api/v1/data
Content-Type: application/json

{
  "productId": "timeseries",
  "parameters": {
    "start": "2026-01-19T00:00:00Z",
    "end": "2026-01-19T06:00:00Z",
    "columns": ["omni_bz", "kp"]
  }
}
```

Обе границы включены. Timestamps требуют timezone и точности до целой секунды;
offset переводится в UTC. При полном локальном покрытии API сразу возвращает
`200`. Ответ содержит `time`, массивы `columns`, metadata и provenance по колонкам.
`null` на штатной временной сетке колонки означает `missing_data`; вне неё —
`no_sample_expected`. `frequencySeconds`, `offsetSeconds`, `missingCount` и
`missingIntervals` позволяют различать эти случаи без подстановки значений.

Если требуются скачивание/обработка, ответ имеет статус `202`:

```json
{
  "status": "processing",
  "jobId": "...",
  "statusUrl": "/api/v1/jobs/...",
  "resultUrl": "/api/v1/jobs/.../result"
}
```

Опросите `statusUrl`; после `completed` получите результат по `resultUrl`.
Формат результата совпадает с синхронным ответом. `Prefer: respond-async` позволяет
заказать job даже для локальных данных. Состояния: `queued`, `downloading`,
`processing`, `waiting_external`, `retrying`, `completed`, `failed`, `cancelled`. `DELETE /api/v1/jobs/{jobId}`
отменяет незавершённое задание. Готовые результаты сохраняются для повторного чтения.

Очередь и статусы сохраняются в SQLite. Один координатор выбирается file lock.
Совпадающие активные запросы используют одно задание. После рестарта queued jobs
продолжаются, прерванные running jobs повторяются с ограниченным числом попыток
и задержкой. API по умолчанию не запускает исполнителей; нужен отдельный worker. Таймаут и отмена
останавливают отдельный worker-процесс. Raw-кэш и завершённые файлы не удаляются
автоматически; срок хранения job artifacts задаётся эксплуатационной политикой.

При частичном отказе источника доступные ряды возвращаются с `metadata.partial`
и `metadata.errors`. Если нет ни одного запрошенного значения — ошибка. Единый
формат ошибок: `{ "code": "...", "message": "...", "details": {} }`.
Недоступный timestamp карты не заменяется ближайшим; ошибка содержит известные
`nearestTimestamps`.

## Карты и кеограммы

```json
{
  "productId": "roti-map",
  "parameters": { "timestamp": "2026-01-19T00:00:00Z", "resolution": "full" }
}
```

Ответ — `application/vnd.apache.arrow.stream`; колонки `lat`, `lon`, `value`
имеют тип float32. Schema metadata содержит JSON-кодированные `productId`,
`timestamp`, `units`, `datasetVersion`, `resolution`, `pointCount`, `missingData`,
`generatedAt`, `source`. Нечисловые значения превращаются в Arrow null.
`format: "json"` предназначен для разработки.

`medium` читает каждую четвёртую точку, `low` — каждую шестнадцатую; это явное
прореживание, не пространственная интерполяция. HDF5-reader выбирает только один
точный dataset и три поля, проверяет размер до чтения и всегда закрывает файл.
Имена файлов и многодневные SIMuRG datasets сохраняются.

```json
{
  "productId": "roti-keogram",
  "parameters": {
    "start": "2026-01-19T00:00:00Z",
    "end": "2026-01-19T06:00:00Z",
    "timeStepMinutes": 5,
    "latitudeStepDegrees": 2.5,
    "hemisphere": "west"
  }
}
```

Кеограмма читает срезы по одному и использует существующий
`build_keogram_matrix_from_slices`. Матрица имеет порядок `[latitude][time]`,
отсутствующие временные срезы остаются null. Научные правила существующего reducer,
включая исключение нулевых значений, сохранены.

## Общее хранилище и совместимость

Backend пишет только `files/processed/data.csv`: первые шесть колонок —
`year,month,day,hour,minute,second`, одна строка на уникальный UTC timestamp.
Merge выполняется под process-safe lock: read → merge → validation → temporary
file → flush/fsync → atomic replace. Новое непустое значение заменяет старое;
новое null его не стирает. Пустой или невалидный результат не повреждает файл.

При запуске старые `omni.csv`, `kp.csv`, `kyoto.csv` импортируются без изменения
исходников и без замены уже имеющихся значений общего CSV. Тетради могут продолжать
работать со старыми файлами. Backend не создаёт новые processed CSV по источникам.
Справочники станций и наблюдения с несколькими объектами в один момент времени
сохраняют свой прежний формат.

`BaseProcessor.get_data` получил необязательные `columns` и `frequency_policies`.
Без этих аргументов старые сигнатура и формат результата сохраняются. Для backend
покрытие проверяется по ненулевым значениям каждой колонки, включая внутренние gaps.
Отдельные locks источников предотвращают дублирующие скачивания; общий CSV lock не
удерживается во время сети.

Фактическая гранулярность источников ограничивает загрузку: OMNI принимает часовые
границы, GFZ/GIRO — дни, Kyoto — месячные файлы, SIMuRG — свои многодневные продукты.
Сервис запрашивает минимальные интервалы, поддержанные существующим источником,
и сохраняет в общий CSV только запрошенные колонки/интервалы. Raw остаётся кэшем.

## Render jobs

Однократная подготовка закреплённых assets и браузера:

```bash
poetry run python -m app.backend.setup_render
poetry run python -m playwright install chromium
```

Для Chromium, установленного в кэш проекта на Windows:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.cache\playwright"
```

`GET /api/v1/render-assets` возвращает `assetVersion` и SHA-256 каждого файла.
Frontend может использовать те же JS/CSS/style через `/api/v1/render-assets/{filename}`.
Закреплены MapLibre GL JS 5.6.1, Playwright 1.55.0 с соответствующей сборкой Chromium,
DPR=1, UTC, viewport и software rendering. Стандартный offline-style показывает
точки данных на однотонном фоне; внешних tiles, fonts, glyphs и sprites в нём нет.
Это позволяет не зависеть от изменяемых внешних ресурсов. Pixel-identical output
между разными ОС/GPU не гарантируется; для повторяемости используйте одинаковый образ ОС.

```json
{
  "productId": "roti-map",
  "timestamps": ["2026-01-19T00:00:00Z"],
  "assetVersion": "<SHA-256 из /api/v1/render-assets>",
  "width": 1200,
  "height": 700,
  "center": [0, 40],
  "zoom": 1,
  "minimum": 0,
  "maximum": 1,
  "resolution": "medium"
}
```

Отправьте спецификацию в `POST /api/v1/map-render-jobs`. Frozen `MapRenderSpec`
сериализуется канонически для `specHash`. Далее доступны:

- `GET /api/v1/map-render-jobs/{jobId}` — статус и hash;
- `GET /api/v1/map-render-jobs/{jobId}/files` — ссылки на PNG, provenance каждого
  среза и `spec.json`;
- `DELETE /api/v1/map-render-jobs/{jobId}` — отмена незавершённого рендера.

Произвольные URL/styles/пути от HTTP-клиента renderer не принимает; браузерные
сетевые обращения отключены. Готовые файлы доступны только по зарегистрированным
именам. Серия ограничена 48 картами.

## Проверки

```bash
poetry run python -m pytest tests -q
```

Текущие тесты используют временные хранилища и локальные источники-заглушки.
Проверки восстановления после SIGKILL, конкурирующих координаторов, API/worker,
миграции и frontend описаны в [worker.md](worker.md). Реальные внешние источники
и Chromium требуют отдельной проверки с установленными assets и учётной записью.

В логах backend доступны requestId/jobId, productId, параметры, cache hit/miss,
missing intervals, Downloader/Processor, длительность стадий, версия и размер
ответа. Настройте logging level INFO в конфигурации сервера для записи этих событий.

Настройки TOML, приоритеты и режимы Hot Reload описаны в [конфигурации](configuration.md).
