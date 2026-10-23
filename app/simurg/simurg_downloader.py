from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.base_classes.base_downloader import BaseDownloader
from app.logging_config import get_logger, logged_stage
from app.simurg.simurg_client import SimurgClient

logger = get_logger(__name__)

__all__ = [
    "RotiDownloader",
    "AdjustedTecDownloader",
]


class _SimurgDownloader(BaseDownloader):
    """Базовый класс-загрузчик для конкретного типа продукта.

    В подклассах следует определить атрибут ``product_type`` и при
    необходимости переопределить ``_make_time_range``.
    """

    _method: str = ""
    _args: Dict[str, Any] = {}

    def __init__(self, client: SimurgClient, out_dir: str = "."):
        super().__init__(out_dir=out_dir)
        self.client = client

    @staticmethod
    def _to_simurg_date(dt: datetime) -> str:
        """Преобразует datetime в ISO 8601 без дробной части секунд."""
        return dt.strftime("%Y-%m-%d %H:%M")

    def _make_time_range(
        self, date_str: str, end_date: Optional[str] = None
    ) -> tuple[str, str]:
        """Формирует строковые временные границы.

        Если задан только ``date_str``, возвращает интервал в 24 часа
        (от 00:00 до 23:59:59) этого дня.  Если задан диапазон (``end_date``),
        использует начало и конец диапазона.  Даты могут быть в формате
        ``YYYY-MM-DD``.
        """
        start_date = datetime.strptime(date_str, "%Y-%m-%d")
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        else:
            end_dt = start_date + timedelta(days=1) - timedelta(minutes=1)
        return _SimurgDownloader._to_simurg_date(
            start_date
        ), _SimurgDownloader._to_simurg_date(end_dt)

    def _find_existing_hdf5_result(self, start_iso: str) -> str | None:
        options = self._args.get("options", {})

        if options.get("format") != "hdf5":
            return None

        product_type = options.get("product_type")
        if not product_type:
            return None

        file_date = datetime.strptime(start_iso, "%Y-%m-%d %H:%M").date()
        year = file_date.year
        doy = file_date.timetuple().tm_yday
        prefix = f"{product_type}_{year}_{doy:03d}_-90_90_N_-180_180_E_"

        if not os.path.isdir(self.out_dir):
            return None

        for filename in sorted(os.listdir(self.out_dir)):
            if not filename.startswith(prefix) or not filename.endswith(".h5"):
                continue

            existing_file = self._get_existing_file(filename)
            if existing_file:
                logger.info(
                    f"Using local cached SIMuRG file: {existing_file}",
                    extra={"event": "cache_hit"},
                )
                return existing_file

        return None

    @staticmethod
    def contains_timestamp(path, timestamp) -> bool:
        import h5py

        from app.storage.timeseries import utc

        try:
            with h5py.File(path, "r") as handle:
                return "data" in handle and any(
                    utc(key) == utc(timestamp) for key in handle["data"]
                )
        except (OSError, ValueError):
            return False

    @logged_stage("download", entry=False)
    def download(
        self,
        date_str: str,
        end_date: Optional[str] = None,
        *,
        window=None,
        target_timestamp=None,
    ) -> str:
        """Запускает формирование запроса и скачивает результат.

        :param date_str: начальная дата (формат ``YYYY-MM-DD``)
        :param end_date: опциональная конечная дата (формат ``YYYY-MM-DD``)
        :param kwargs: дополнительные параметры для API
        :returns: путь к результату
        """
        start_iso, end_iso = window or self._make_time_range(date_str, end_date)
        existing_file = self._find_existing_hdf5_result(start_iso)
        if (
            existing_file
            and target_timestamp is not None
            and not self.contains_timestamp(existing_file, target_timestamp)
        ):
            existing_file = None
        if existing_file:
            return existing_file

        # Backend jobs persist identity before yielding; notebooks keep blocking behavior.
        from app.backend.logging import job_id as current_job_id

        durable_id = current_job_id.get()
        store = None
        acquisition = None
        if durable_id:
            from app.backend.jobs import _acquisition_key, _execution_store

            store = _execution_store.get()
            acquisition = _acquisition_key.get()
        external = {}
        key = (
            "query_ids"
            if acquisition
            else f"{self._method}:{start_iso}:{end_iso}:{self._args}"
        )
        if durable_id:
            import json

            from app.backend.config import Settings
            from app.backend.jobs import JobStore

            store = store or JobStore(Settings())
            if acquisition:
                from contextlib import closing

                with closing(store.connect()) as db:
                    saved = db.execute(
                        "SELECT external,created FROM simurg_acquisitions WHERE key=?",
                        (acquisition,),
                    ).fetchone()
                external = json.loads(saved[0] or "{}")
                acquisition_created = saved[1]
            else:
                external = json.loads(store.get(durable_id)["external"] or "{}")

        def checkpoint():
            if not store:
                return
            from contextlib import closing

            with closing(store.connect()) as db:
                if acquisition:
                    db.execute(
                        "UPDATE simurg_acquisitions SET external=? WHERE key=?",
                        (json.dumps(external), acquisition),
                    )
                else:
                    db.execute(
                        "UPDATE jobs SET external=? WHERE id=?",
                        (json.dumps(external), durable_id),
                    )

        query_ids = external.get(key)
        if query_ids == "submitting":
            # A crash may have occurred after the remote POST but before saving IDs.
            # Reconcile, never blindly submit the ambiguous request again.
            payload_args = {"begin": start_iso, "end": end_iso, **self._args}
            query_ids = [
                str(q["id"])
                for q in self.client.checking_by_mail()
                if q.get("id") is not None
                and self.client._payload_match(q, self._method, payload_args)
            ]
            if not query_ids:
                from app.backend.errors import BackendError

                raise BackendError(
                    "REMOTE_SUBMISSION_UNCERTAIN",
                    "Remote submission could not be reconciled; inspect SIMuRG before retry",
                    409,
                )
        if not query_ids:
            if store:
                from contextlib import closing

                def submitting():
                    external[key] = "submitting"
                    checkpoint()

                self.client.before_create = submitting
            query_ids = self.client.create_or_reuse_query_ids(
                start_time=start_iso,
                end_time=end_iso,
                method=self._method,
                args_params=self._args,
            )
        if store:
            import json
            from contextlib import closing

            external[key] = query_ids
            checkpoint()
            statuses = None
            if acquisition:
                with closing(store.connect()) as db:
                    saved = db.execute(
                        "SELECT statuses,checked FROM simurg_acquisitions WHERE key=?",
                        (acquisition,),
                    ).fetchone()
                if saved[0] and time.time() - (saved[1] or 0) < 60:
                    cached = json.loads(saved[0])
                    if set(cached) == set(query_ids):
                        statuses = cached
            if statuses is None:
                statuses = self.client.check_statuses(query_ids)
                if acquisition:
                    with closing(store.connect()) as db:
                        db.execute(
                            "UPDATE simurg_acquisitions SET statuses=?,checked=? WHERE key=?",
                            (json.dumps(statuses), time.time(), acquisition),
                        )
            if any(q.get("status") == "not_found" for q in statuses.values()):
                # A cached not_found is not proof of deletion. Only a successful
                # fresh account listing can invalidate persisted remote IDs.
                queries = self.client.checking_by_mail()
                present = self.client._to_id_set(queries)
                missing = set(query_ids) - present
                if missing:
                    external[key] = [qid for qid in query_ids if qid not in missing]
                    with closing(store.connect()) as db:
                        db.execute("BEGIN IMMEDIATE")
                        if acquisition:
                            db.execute(
                                "UPDATE simurg_acquisitions SET external=?,statuses=NULL,checked=NULL WHERE key=?",
                                (json.dumps(external), acquisition),
                            )
                        db.execute(
                            "UPDATE jobs SET external=? WHERE id=?",
                            (json.dumps(external), durable_id),
                        )
                        db.commit()
                    self.client.remove_query_ids(missing)
                    # Yield before rediscovery: the next session uses the normal
                    # cache/shared/reuse/create path and account-limit lock.
                    from app.backend.jobs import ExternalPending

                    store.defer(durable_id, external=external)
                    raise ExternalPending()
                statuses = {
                    str(q["id"]): q for q in queries if str(q["id"]) in query_ids
                }
                if acquisition:
                    with closing(store.connect()) as db:
                        db.execute(
                            "UPDATE simurg_acquisitions SET statuses=?,checked=? WHERE key=?",
                            (json.dumps(statuses), time.time(), acquisition),
                        )
            if acquisition:
                compatible = [
                    q
                    for q in statuses.values()
                    if self.client._payload_match(
                        q,
                        self._method,
                        {"begin": start_iso, "end": end_iso, **self._args},
                    )
                ]
                if compatible:
                    covered_begin = min(
                        self.client._norm_dt(q["begin"])[:16] for q in compatible
                    )
                    covered_end = max(
                        self.client._norm_dt(q["end"])[:16] for q in compatible
                    )
                    with closing(store.connect()) as db:
                        db.execute(
                            "UPDATE simurg_acquisitions SET begin=?,end=? WHERE key=?",
                            (covered_begin, covered_end, acquisition),
                        )
            if any(q.get("status") == "not_found" for q in statuses.values()):
                from app.backend.errors import BackendError

                raise BackendError(
                    "REMOTE_QUERY_MISSING",
                    "A known SIMuRG request was removed; inspect it before retrying",
                    409,
                )
            if any(
                self.client.status_has_keyword(q.get("status"), "error")
                or self.client.status_has_keyword(q.get("status"), "failed")
                for q in statuses.values()
            ):
                from app.backend.errors import BackendError

                raise BackendError(
                    "REMOTE_GENERATION_FAILED",
                    "SIMuRG generation failed; inspect remote request",
                    409,
                )
            if len(statuses) != len(query_ids) or not all(
                self.client.status_has_keyword(q.get("status"), "done")
                for q in statuses.values()
            ):
                from app.backend.errors import BackendError
                from app.backend.jobs import ExternalPending

                row = store.get(durable_id)
                if (
                    time.time()
                    - (acquisition_created if acquisition else row["created"])
                    > store.settings.external_wait_timeout
                ):
                    raise BackendError(
                        "EXTERNAL_TIMEOUT", "SIMuRG generation deadline exceeded", 408
                    )
                store.defer(durable_id, external=external)
                raise ExternalPending()
        file_path = self._wait_and_download(query_ids, statuses if store else None)
        return file_path

    def _wait_and_download(self, query_ids: list[str], initial_statuses=None) -> str:
        """Ожидает готовность по множеству id и скачивает все готовые результаты."""
        pending_ids = {str(query_id) for query_id in query_ids}
        if not pending_ids:
            raise RuntimeError("SIMURG не вернул id запросов для проверки статуса")

        self.client.query_ids.update(pending_ids)
        downloaded_paths: list[str] = []

        deadline = time.monotonic() + 3600 * 24
        while pending_ids:
            if time.monotonic() >= deadline:
                raise RuntimeError("SIMuRG polling deadline exceeded")
            status_map = (
                initial_statuses
                if initial_statuses is not None
                else self.client.check_statuses(sorted(pending_ids))
            )
            initial_statuses = None
            done_ids: list[str] = []

            for query_id, status_data in status_map.items():
                status = status_data.get("status")
                if self.client.status_has_keyword(status, "done"):
                    result_path = (status_data.get("paths") or {}).get("data")
                    if not result_path:
                        raise RuntimeError(
                            f"Запрос {query_id} завершён (done), но paths.data отсутствует: {status_data}"
                        )

                    full_result_url = (
                        f"{self.client.download_url}/{str(result_path).lstrip('/')}"
                    )
                    downloaded_paths.append(self._download_result(full_result_url))
                    done_ids.append(query_id)
                    continue

                if status == "not_found":
                    raise RuntimeError(f"Запрос {query_id} был удален или изменен")

                in_progress_keywords = (
                    "new",
                    "prepared",
                    "processed",
                    "plot",
                    "processing",
                )
                if not any(
                    self.client.status_has_keyword(status, keyword)
                    for keyword in in_progress_keywords
                ):
                    raise RuntimeError(
                        f"Запрос {query_id} имеет неожиданный статус: {status_data}"
                    )

            if done_ids:
                pending_ids.difference_update(done_ids)
                self.client.remove_query_ids(done_ids)
                continue

            time.sleep(self.client.polling_interval)

        if not downloaded_paths:
            raise RuntimeError(
                "Не удалось скачать данные SIMURG: отсутствуют готовые запросы"
            )

        return downloaded_paths[0]

    @logged_stage("download", entry=False)
    def _download_result(self, url: str) -> str:
        import hashlib
        import sqlite3
        from contextlib import closing
        from pathlib import Path

        from app.backend.logging import job_id as current_job_id

        name = hashlib.sha256(url.encode()).hexdigest()
        durable_id = current_job_id.get()
        with closing(
            sqlite3.connect(
                Path(self.out_dir) / f".{name}.download.sqlite3",
                timeout=0 if durable_id else self.client.timeout,
            )
        ) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError:
                if durable_id:
                    from app.backend.jobs import ExternalPending, _execution_store

                    store = _execution_store.get()
                    if store:
                        store.defer(durable_id, external={"download": name})
                        raise ExternalPending()
                raise
            try:
                progress_callback = None
                if durable_id:
                    from app.backend.jobs import (
                        _acquisition_key,
                        _execution_store,
                        report_stage,
                    )

                    report_stage("downloading")
                    store = _execution_store.get()
                    acquisition = _acquisition_key.get()
                    if store:

                        def progress_callback(downloaded, total, rate):
                            try:
                                store.record_download_progress(
                                    durable_id, acquisition, downloaded, total, rate
                                )
                            except sqlite3.Error:
                                logger.warning(
                                    "Could not record download progress",
                                    extra={"event": "download_progress_unavailable"},
                                )

                        progress_callback(0, None, None)
                return super()._download_result(
                    url,
                    timeout=self.client.timeout,
                    verify=self.client.verify,
                    polling_interval=self.client.polling_interval,
                    progress_callback=progress_callback,
                )
            finally:
                db.rollback()


class RotiDownloader(_SimurgDownloader):
    """Загрузчик для карт индекса ROTI."""

    _method = "create_map"
    _args = {
        "coordinates": {"minlat": -90, "maxlat": 90, "minlon": -180, "maxlon": 180},
        "options": {
            "product_type": "roti",
            "format": "hdf5",
            "subsolar": False,
            "mageq": False,
            "cutoff": 10,
            "timestep": 30,
        },
        "flags": {"create_plots": False, "create_movie": False},
    }

    def _make_time_range(
        self, date_str: str, end_date: Optional[str] = None
    ) -> tuple[str, str]:
        """Формирует диапазон ``target ± 1 день`` для выгрузки ROTI.

        При передаче одной даты (``YYYY-MM-DD``) на SIMURG отправляется интервал
        от 00:00 предыдущего дня до 00:00 следующего за целевым днём.
        В результате имя файла на стороне SIMURG начинается с DOY предыдущего дня.
        """
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        start_date = target_date - timedelta(days=1)
        end_dt = target_date + timedelta(days=1, hours=23, minutes=59)
        return _SimurgDownloader._to_simurg_date(
            start_date
        ), _SimurgDownloader._to_simurg_date(end_dt)


class AdjustedTecDownloader(_SimurgDownloader):
    """Загрузчик для «adjusted TEC» (откалиброванный TEC)."""

    _method = "create_map"
    _args = {
        "coordinates": {"minlat": -90, "maxlat": 90, "minlon": -180, "maxlon": 180},
        "options": {
            "product_type": "tec_adjusted",
            "format": "hdf5",
            "subsolar": False,
            "mageq": False,
            "cutoff": 10,
            "timestep": 30,
        },
        "flags": {"create_plots": False, "create_movie": False},
    }

    def _make_time_range(
        self, date_str: str, end_date: Optional[str] = None
    ) -> tuple[str, str]:
        """Build the SIMuRG three-day window used by adjusted TEC files.

        SIMuRG names these files by the first day of the window.  For a
        requested day (for example 2026-01-20), the corresponding file starts
        on the previous day at 23:55 and covers the requested day plus the
        following day.  Using a one-day request here makes the API create a
        different query even when the three-day result already exists.
        """
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        start_dt = target_date - timedelta(days=1)
        start_dt = start_dt.replace(hour=23, minute=55)
        end_dt = target_date + timedelta(days=1)
        end_dt = end_dt.replace(hour=23, minute=55)
        return _SimurgDownloader._to_simurg_date(
            start_dt
        ), _SimurgDownloader._to_simurg_date(end_dt)
