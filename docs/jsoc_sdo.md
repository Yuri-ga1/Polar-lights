# JSOC / SDO: получение одного научного кадра

Для первого продукта поддерживается `hmi.Ic_720s{continuum}`. Используется полное
разрешение FITS, не интенсивность визуального JP2. Прежние вызовы SolarDiskConfig
сохраняют provider=`helioviewer`; пример в основном notebook явно выбирает `jsoc`.
API/worker сейчас обслуживают прежние продукты каталога: новый HTTP endpoint или
новая очередь для солнечного диска не добавлены. Notebook и PlotConstructor
используют прежний `prepare_solar_disk` и объект `SolarDiskData`.

## Пример

В Conda `polar-lights` установите зависимости Poetry согласно `poetry.lock`.
Email должен быть зарегистрирован в JSOC и задаётся пользователем в notebook:

```python
from app.pipeline.solar_disk_pipeline import SolarDiskConfig, prepare_solar_disk, build_solar_disk
from app.solar.sdo import JSOCSettings, SDOProduct

email = input("Registered JSOC email: ").strip()
config = SolarDiskConfig(
    requested_time="2026-01-20T12:00:00Z",
    provider="jsoc",                   # строгий научный режим
    jsoc_email=email,
    sdo_product=SDOProduct(),           # hmi.Ic_720s, continuum, QUALITY == 0
    jsoc=JSOCSettings(),
    max_time_delta_minutes=30,
)
data = prepare_solar_disk(config)
fig, ax = build_solar_disk(config)
print(data.metadata["jsoc"]["record"])
```

CLI: `python -m app.pipeline.solar_disk_pipeline --provider jsoc --jsoc-email EMAIL
--date 2026-01-20 --time 12:00:00`. Email не входит в repr конфигурации, ключ
наблюдения, имена файлов или provenance графика. Не помещайте настоящий email
в закоммиченные notebook-выводы.

`provider="auto"` разрешает резервный Helioviewer для HMI continuum. Лог явно
сообщает переход, provenance содержит `scientific: false`, `fallback: true`,
причину и фактический provider. `jsoc` никогда не возвращает JP2. Для AIA и других
продуктов автоматическая подмена на HMI запрещена. Исходные координаты NOAA
вращаются прежней моделью Howard к observer и reference_date фактического кадра.

## Последовательность и идентичность

1. Под общей блокировкой продукта проверяется SQLite-индекс ближайших пригодных
   кадров в заданном допуске. Проверяется существование и SHA-256 HDF5, затем
   читается научная Map. Это **0 HTTP-запросов к JSOC**, без создания DRMS-клиента.
   Если уже локально есть несколько кадров, выбирается ближайший из локальных.
2. При отсутствии постоянного изображения используется существующий raw FITS.
   Детерминированное имя восстанавливает работу после падения до записи его пути.
3. Известные метаданные/экспорты переиспользуются между пользователями. Метаданные
   известного пригодного кадра не требуют повторного серверного поиска после TTL.
4. Иначе выполняется один ограниченный `query` на ±search_window_seconds от
   target. По умолчанию это **час суммарно**, не сутки. TAI-границы вычисляет
   Astropy; соседние UTC-сутки не отсекаются. Сегмент должен существовать, QUALITY
   проверяется маской продукта. Сохраняются все найденные записи этого малого окна,
   но экспортируется только ближайшая подходящая запись и только один сегмент.
5. Сначала `url_quick/as-is`; при неполных WCS/observer/time/unit метаданных или
   явном отказе используется `url/fits`. Быстрый режим тоже делает HTTP-запросы.
   Сохранённый полноценный экспорт имеет приоритет перед повтором quick.
6. До отправки экспорта записывается intent, после ответа немедленно сохраняются
   ID/статус. Готовые URL используются непосредственно; pending ID восстанавливается
   через `export_from_id`. Если готовый URL истёк, сначала обновляется старый ID;
   новая заявка допустима только после явной недоступности/отказа.
7. Готовность проверяется не чаще одного раза в 60 с, даже после рестарта.
   Ожидание ограничено wait_timeout. Таймаут не инвалидирует существующий ID.
8. Скачивается ровно один файл в `.part`, затем атомарно публикуется raw FITS.
   Неполные передачи не становятся валидными raw. После обрыва повторяется один
   файл с тем же экспортом, без Range-докачки. Попытки ограничены.
9. Проверяются двумерные данные, checksum FITS при наличии, WCS/observer/единицы,
   время reference_date относительно выбранного T_OBS и QUALITY. Запись HDF5
   проверяется чтением назад: точное равенство пикселей (включая NaN), dtype и WCS.
   После fsync/rename и чтения окончательного пути сохраняется SHA-256 в SQLite.
   Только затем `raw_operation` получает подтверждение и удаляет исходный FITS.

Ключ включает instrument, полное имя серии, segment, channel/prime-key selectors,
processing_version, критерий качества, точный record specification и фактический
T_OBS. Export ID является отдельной сущностью и не служит идентификатором кадра.
Email принадлежит только экспортной заявке. Старый raw_path не означает, что файл
сохранился: перед использованием всегда проверяется диск.

## Постоянное хранение

```text
files/raw/sdo/<instrument>/<series>/<segment>/<channel-or-all>/<identity>.fits
files/maps/sdo/<instrument>/<series>/<segment>/<channel-or-all>/<identity>.h5
files/raw/noaa/srs/<YYYYMMDD>SRS.txt[.json]
files/cache/jsoc/exports.sqlite[-wal,-shm]
files/cache/jsoc/<product-key>.lock
results/<date>/Solar_disk_<time>.png
```

Пути создаются через DataPaths. SDOImageStorage отделён от точечного
HDF5MapStorage; используются существующие publish/fsync, FileLock и raw_operation.
Выбран **один неизменяемый HDF5 на наблюдение**, поэтому добавление не копирует
ранее сохранённые изображения. Месячная разбивка не используется. В HDF5 хранится
`image` с исходным dtype декодированных научных пикселей и lossless LZF/shuffle,
полный объединённый FITS header в `fits_header` (включая историю, observer, даты,
единицы), `provenance` с продуктом/record/UTC. Это не нормализованный uint8 PNG.

Старый Helioviewer JP2/XML кеш остаётся в `files/<date>/solar`. NOAA SRS теперь
пишется отдельно в raw/noaa/srs; старые файлы читаются без удаления или миграции.
SRS сохраняется как повторно используемый исходный отчёт: преобразованного
постоянного архива NOAA в этой задаче нет, поэтому удалять его после PNG нельзя.
Provenance графика сохраняется в прежнем `files/<date>/solar/*.json`. `results`
содержит визуальные результаты. `keep_fits=True` оставляет научный FITS для
диагностики; по умолчанию он удаляется только после публикации HDF5.

## SQLite и координация

SQLite на локальной файловой системе использует WAL, foreign_keys, FULL synchronous,
короткие транзакции, уникальные ключи и индекс `(product, utc)`:

| Таблица | Назначение |
| --- | --- |
| observations | hash ID, product key, полный spec, TAI, UTC timestamp, QUALITY |
| local_artifacts | observation FK, raw/map paths, SHA-256, downloaded/published |
| exports | локальный ID, JSOC remote_id, приватный email, method, status, created/checked, URL, error, attempts |
| export_items | связь many-to-many export ↔ observation |
| lookup_cache | проверенные start/end окна и expires; TTL применяется также к отсутствию подходящего кадра |

Начальные статусы — `submitting`, затем `pending`/`ready`; явно недоступные
экспорты получают `unusable`, непригодные научные результаты — `invalid`.
Это индекс приобретения данных, а не дубликат backend jobs: здесь нет очереди,
пользовательских заданий или фонового scheduler. Работа выполняется по запросу.

Для всех пересекающихся запросов одного продукта держится один межпроцессный
FileLock, дополнительно действуют raw retention lock и lock окончательного HDF5.
Это консервативно сериализует и разные времена одного продукта. Lease/heartbeat
не нужен: файловая блокировка ОС освобождается при смерти процесса, поэтому
зависшей SQLite-аренды не остаётся. Ожидание блокировки ограничено lock_timeout.
Не удаляйте lock-файл вручную, пока процессы работают. SQLite/HDF5/FileLock
предполагают согласованные POSIX-блокировки локального диска; NFS не проверялся.

После падения между rename HDF5 и SQLite commit кадр восстанавливается по
детерминированному пути. Если процесс умер после удалённой отправки, но до
сохранения Export ID, intent остаётся `submitting`: автоматическая повторная
отправка запрещена. Оператор должен найти ID в JSOC и связать его с intent либо
подтвердить отсутствие заявки, прежде чем снять неоднозначность. Это ограничение
JSOC без idempotency key; автоматическое «точно один экспорт» через такой разрыв
не гарантируется. Повреждённый постоянный файл сохраняется для проверки и требует
восстановления из backup; исходный FITS при неудачной публикации не удаляется.

## Настройки

Все сетевые параметры находятся в JSOCSettings, научная идентичность — в SDOProduct:

| Настройка | По умолчанию |
| --- | --- |
| search_window_seconds | 1800 в каждую сторону; должна покрывать допуск |
| metadata_ttl / negative_ttl | 3600 / 120 секунд |
| poll_seconds / wait_timeout | 60 / 1800 секунд |
| http_timeout | 90 секунд на HTTP I/O |
| retries / backoff_seconds | 3 / 1; ограниченный exponential backoff + jitter |
| lock_timeout | 2100 секунд |
| quick / keep_fits | True / False |
| SDOProduct.time_key / quality_mask | T_OBS / 0xffffffff (строго QUALITY=0) |
| processing_version | "1"; изменение отделяет несовместимую обработку |

Повторные GET метаданных/загрузок учитывают Retry-After. Создание экспорта
автоматически не повторяется при потере ответа. Status HTTP не использует короткие
внутренние повторы: сохранённый checked ограничивает частоту между потребителями.
DRMS 0.9.x использует изолированный адаптер JSON-запросов для таймаутов; его
private interface покрыт офлайн contract-тестом и требует проверки при обновлении.
Логи содержат события local hit, metadata lookup, reuse, quick, export, validation,
publication, raw cleanup, visual fallback без email и длинных URL.

Для новых продуктов передавайте отдельные SDOProduct **и** JSOCSettings, явно
выбирая период/окно, допуск и quality mask по документации инструмента. Например,
AIA может использовать instrument=`aia`, series=`aia.lev1_euv_12s`, segment=`image`,
channel=`171`, selectors=`[171]`. Это пример адресации, а не подтверждённая
проверка пригодности AIA: её cadence, QUALITY и научная отрисовка требуют отдельной
валидации. Существующий plotter оптимизирован для HMI continuum; хранилище и
provider не зависят от жёстко заданного пути HMI.

## Проверки и эксплуатация

Офлайн: `python -m pytest tests/test_jsoc_sdo.py -q`. Проверяются независимые
пользователи и процессы, нулевой HTTP на постоянном hit, raw recovery, ID reuse и
expiry, UTC/TAI и предыдущие сутки, QUALITY, quick fallback, разрыв передачи,
рестарт pending экспорта, частота опроса, TTL, сохранность raw, WCS/dtype/NaN,
старый JP2 + NOAA + PNG и cache volume.

Необязательная живая проверка одного кадра (требует зарегистрированного email):

```bash
python -m deploy.jsoc_check --email YOUR_REGISTERED_EMAIL --root files --annotations --check-export-session
```

Она получает один кадр около 2026-01-20 12:00 UTC, строит график и запрещает HTTP
при повторном запросе. Последний флаг пробует чтение существующего Export ID из
нового независимого DRMS-клиента. Это проверка доступа данного ID в момент запуска,
не гарантия вечной доступности экспортов или всех аккаунтов. CI её не запускает.
Доступ между сессиями в офлайн-тестах моделируется; до живой проверки с реальным
ID не следует считать серверное поведение подтверждённым.

API и worker получают общий bind mount `./files/cache:/app/files/cache` с теми же
POLAR_UID/POLAR_GID. Каталог и backup приватны: SQLite хранит email и временные URL.
Еженедельная очистка jobs не очищает этот индекс или постоянные maps. Сохраняйте
cache вместе с raw/maps при backup. Останавливайте всех writers, checkpoint WAL
или используйте SQLite backup API; нельзя копировать только основной SQLite-файл
при живом WAL. Подробнее: [deployment](deployment.md#consistent-backup-and-restore).

## Оценка размера хранения

Локальный синтетический замер в Conda polar-lights: массив 4096×4096 float32
(случайные значения, seed=0) — 64,0 МиБ в памяти, 51,4 МиБ в HDF5 LZF/shuffle;
запись 0,777 с, чтение 0,210 с, точное численное равенство подтверждено. Это замер
HDF5 I/O, без FITS-декодирования, WCS и fsync; реальные HMI изображения и другой
диск дадут другие результаты. При добавлении нового наблюдения прежние файлы
не копируются. Это ограничивает стоимость добавления одним изображением.

## Изменённые файлы

- Приобретение и политика: `app/solar/sdo.py`, `app/solar/jsoc_index.py`,
  `app/solar/jsoc_transport.py`, `app/solar/jsoc_provider.py`, `app/solar/providers.py`.
- Хранение: `app/storage/data_paths.py`, `app/storage/sdo_storage.py`.
- Интеграция: `app/solar/models.py`, `app/solar/solar_downloader.py`,
  `app/solar/solar_processor.py`, `app/pipeline/solar_disk_pipeline.py`,
  `app/visualization/solar_disk_plotter.py`.
- Notebook: `notebooks/00_examples_and_run.ipynb`.
- Зависимости: `pyproject.toml`, `poetry.lock` (drms 0.9.1).
- Развёртывание: `compose.yaml`, `deploy/integration.py`, `deploy/jsoc_check.py`.
- Тесты: `tests/test_jsoc_sdo.py`, `tests/test_deployment.py`. В последнем исправлена
  подготовка старого cancelled-задания: retention использует finished, поэтому
  одного изменения updated недостаточно. Падение исходного теста воспроизведено
  на неизменённом HEAD в отдельном каталоге; код очистки не менялся.
- Документация: `README.md`, `docs/solar_disk.md`, `docs/jsoc_sdo.md`,
  `docs/backend.md`, `docs/worker.md`, `docs/deployment.md`.

Живая проверка в этой работе ограничилась одним малым запросом метаданных
(±900 с от 2026-01-20T12:00:00Z, без email, экспорта или FITS). Он завершился
JSOCTransportError на HTTP/JSON этапе. Поэтому реальные поиск/экспорт/скачивание,
WCS конкретного HMI FITS и доступ Export ID из разных сессий **не подтверждены**.
Проверки этих сценариев выполнены на офлайн-моделях. Docker Compose configuration
проверена, но сборка образов и запуск полного Docker-стека в этой работе не выполнялись.

Итоговая локальная проверка в Conda `polar-lights`: **42 теста прошли**
(`python -m pytest tests -q --disable-warnings`, 57,95 с; одно предупреждение).
Из них 32 — новый офлайн-набор JSOC/SDO. Полный Ruff и проверка форматирования
16 файлов интеграции прошли; проверка E9/F63/F7/F82 для app/tests/deploy,
compileall новых модулей, `poetry check --lock`, `git diff --check` и
`docker compose config --quiet` также прошли. Poetry сообщает существующее
предупреждение об устаревшей форме project.license. Frontend не изменялся.
Повторный/близкий запрос, другой email и три независимых worker-процесса в тестах
переиспользуют один кадр; после публикации повторный запрос не вызывает ни поиск,
ни экспорт, ни скачивание. Реальный парсер DRMS отдельно проверен на отсутствие
скрытого `series_struct`-запроса: численное преобразование QUALITY выполняется
локально через `convert_numeric=False`.
