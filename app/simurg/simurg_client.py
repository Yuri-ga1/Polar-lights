from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from app.backend.errors import BackendError
from app.configuration import current
from app.logging_config import get_logger
from app.storage.atomic import publish

logger = get_logger(__name__)


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if (
        len(value) > 254
        or not re.fullmatch(
            r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}",
            value,
        )
        or ".." in value
    ):
        raise BackendError("INVALID_EMAIL", "Enter a valid SIMuRG email address", 422)
    return value


class SimurgClient:
    """Базовый клиент для работы с SIMuRG API."""

    def __init__(
        self,
        email: str,
        base_url: str = "https://simurg.iszf.irk.ru",
        polling_interval: int | None = None,
        timeout: int | None = None,
        verify: bool = True,
    ) -> None:
        self.api_url = f"{base_url.rstrip('/')}/api"
        self.download_url = f"{base_url.rstrip('/')}/ufiles"
        settings = current()["downloads"]
        self.timeout = settings["simurg_timeout"] if timeout is None else timeout
        self.polling_interval = (
            settings["simurg_polling_interval"]
            if polling_interval is None
            else polling_interval
        )
        self.verify = verify
        self.email = normalize_email(email)
        self.before_create = None
        self._locked = False
        self.query_ids: set[str] = set()

    def create_query(
        self,
        start_time: str,
        end_time: str,
        method: str,
        args_params: Dict[str, Any],
    ) -> List[str]:
        """Создаёт запрос к SIMuRG и возвращает список новых query_id."""
        if not self._locked:
            with self.account_lock():
                return self.create_query(start_time, end_time, method, args_params)
        logger.info("Create new request", extra={"event": "download_status"})
        url = f"{self.api_url}"
        queries = self.checking_by_mail()
        known_ids = self._to_id_set(queries)
        intent = self._intent_path
        if intent.exists():
            try:
                previous_ids = set(json.loads(intent.read_text())["known_ids"])
            except (OSError, ValueError, KeyError) as exc:
                raise BackendError(
                    "REMOTE_SUBMISSION_UNCERTAIN",
                    "An account submission needs operator reconciliation",
                    409,
                ) from exc
            if not known_ids - previous_ids:
                raise BackendError(
                    "REMOTE_SUBMISSION_UNCERTAIN",
                    "A previous account submission is not yet visible; inspect SIMuRG before retrying",
                    409,
                )
            intent.unlink()
        if len(queries) >= 10:
            raise BackendError(
                "SIMURG_LIMIT_REACHED",
                "SIMuRG allows 10 existing requests per email, including completed requests. Manually delete unnecessary requests and check again.",
                409,
            )
        known_ids = self._to_id_set(queries)
        payload: Dict[str, Any] = {
            "method": method,
            "args": {
                "email": self.email,
                "begin": start_time,
                "end": end_time,
            },
        }
        payload["args"].update(args_params)
        payload["args"]["email"] = self.email

        if self.before_create:
            self.before_create()
        # Persist intent separately from the account-lock transaction. A crash
        # or delayed API visibility must not let another worker assume capacity.
        temporary = intent.with_suffix(".tmp")
        with temporary.open("w") as handle:
            json.dump({"known_ids": sorted(known_ids)}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        publish(temporary, intent)
        try:
            resp = requests.post(
                url, json=payload, timeout=self.timeout, verify=self.verify
            )
        except Exception as exc:
            raise RuntimeError(f"Ошибка соединения с {url}: {exc}") from exc

        if resp.status_code != 200:
            raise RuntimeError(
                f"Сервер вернул код {resp.status_code} при создании запроса. "
                f"Ответ: {resp.text}. Url: {url}"
            )

        query_ids = self._new_ids_since(known_ids)
        if not query_ids:
            raise RuntimeError("Не удалось получить идентификатор запроса из ответа")

        intent.unlink(missing_ok=True)
        self.query_ids.update(query_ids)
        return query_ids

    @staticmethod
    def _to_id_set(queries: Iterable[Dict[str, Any]]) -> set[str]:
        return {
            str(query_id)
            for query in queries
            if (query_id := query.get("id")) is not None
        }

    def _new_ids_since(self, known_ids: set[str]) -> List[str]:
        queries = self.checking_by_mail()
        new_ids = sorted(self._to_id_set(queries) - known_ids)
        return new_ids

    def checking_by_mail(self) -> List[Dict[str, Any]]:
        """Возвращает список всех запросов по email (method=check)."""
        url = f"{self.api_url}"
        try:
            resp = requests.post(
                url,
                verify=self.verify,
                timeout=self.timeout,
                json={"method": "check", "args": {"email": self.email}},
            )
        except Exception as exc:
            raise RuntimeError(f"Ошибка соединения с {url}: {exc}") from exc

        if resp.status_code != 200:
            raise RuntimeError(
                f"Сервер вернул код {resp.status_code} при check. Ответ: {resp.text}. Url: {url}"
            )

        data = resp.json()
        if not isinstance(data, list) or any(
            not isinstance(q, dict) or q.get("id") is None for q in data
        ):
            raise BackendError(
                "SIMURG_UNAVAILABLE", "Cannot inspect SIMuRG request capacity", 502
            )

        return data

    def check_status(self, query_id: str) -> Dict[str, Any]:
        """Проверяет статус запроса по его id (через method=check по email)."""
        url = f"{self.api_url}"
        try:
            resp = requests.post(
                url,
                timeout=self.timeout,
                verify=self.verify,
                json={"method": "check", "args": {"email": self.email}},
            )
        except Exception as exc:
            raise RuntimeError(f"Ошибка запроса статуса {url}: {exc}") from exc

        if resp.status_code != 200:
            raise RuntimeError(
                f"Сервер вернул код {resp.status_code} при запросе статуса. Ответ: {resp.text}"
            )

        queries = resp.json()
        query = next((q for q in queries if q.get("id") == query_id), None)
        if query is None:
            return {"status": "not_found"}

        return query

    def check_statuses(self, query_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """Проверяет статусы сразу для множества id."""
        query_id_set = {str(query_id) for query_id in query_ids}
        if not query_id_set:
            return {}

        statuses = {query_id: {"status": "not_found"} for query_id in query_id_set}
        for query in self.checking_by_mail():
            query_id = query.get("id")
            if query_id is None:
                continue
            query_id = str(query_id)
            if query_id in query_id_set:
                statuses[query_id] = query
        return statuses

    def remove_query_ids(self, query_ids: Iterable[str]) -> None:
        """Удаляет id из локального набора отслеживаемых запросов."""
        self.query_ids.difference_update(str(query_id) for query_id in query_ids)

    @staticmethod
    def status_has_keyword(status: Any, keyword: str) -> bool:
        """Проверяет, содержит ли статус ключевое слово (например, 'Done (2)')."""
        return str(keyword).lower() in str(status or "").lower()

    # -----------------------------
    # Reuse/create helper
    # -----------------------------

    @staticmethod
    def _norm_dt(s: Optional[str]) -> Optional[str]:
        """Normalize datetime string to 'YYYY-MM-DD HH:MM' for matching."""
        if s is None:
            return None

        try:
            value = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
            if value.tzinfo:
                value = value.astimezone(timezone.utc)
            return value.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    @classmethod
    def _payload_match(
        cls,
        server_query: Dict[str, Any],
        payload_method: str,
        payload_args: Dict[str, Any],
    ) -> bool:
        """Check if server query equals our payload (method + args subset)."""

        server_type = str(server_query.get("type") or "").lower()
        payload_type = str(payload_method).lower()
        if (
            not (server_type == "map" and payload_type == "create_map")
            and server_type != payload_type
        ):
            return False

        if cls._norm_dt(server_query.get("begin")) != cls._norm_dt(payload_args.get("begin")):
            return False
        if cls._norm_dt(server_query.get("end")) != cls._norm_dt(payload_args.get("end")):
            return False
        if any(
            cls.status_has_keyword(server_query.get("status"), word)
            for word in ("error", "failed")
        ):
            return False

        # coordinates: compare keys we send
        pcoords = payload_args.get("coordinates")
        if pcoords is not None:
            scoords = server_query.get("coordinates")
            if not isinstance(pcoords, dict) or not isinstance(scoords, dict):
                return False
            for k, v in pcoords.items():
                if scoords.get(k) != v:
                    return False

        # options: compare keys we send
        popt = payload_args.get("options")
        if popt is not None:
            sopt = server_query.get("options")
            if not isinstance(popt, dict) or not isinstance(sopt, dict):
                return False
            for k, v in popt.items():
                if sopt.get(k) != v:
                    return False

        for key, value in payload_args.items():
            if (
                key not in {"email", "begin", "end", "coordinates", "options"}
                and server_query.get(key) != value
            ):
                return False
        return True

    def create_or_reuse_query_id(
        self, start_time: str, end_time: str, method: str, args_params: Dict[str, Any]
    ) -> str:
        """
        1) Ищет уже созданный запрос с теми же параметрами (payload).
           - Если нашёл (done/не done) -> возвращает его id.
        2) Если не нашёл -> создаёт новый и возвращает новый id.
        """
        return self.create_or_reuse_query_ids(
            start_time, end_time, method, args_params
        )[-1]

    def create_or_reuse_query_ids(
        self,
        start_time: str,
        end_time: str,
        method: str,
        args_params: Dict[str, Any],
    ) -> List[str]:
        """Возвращает все подходящие id запроса для дальнейшей проверки готовности."""
        if not self._locked:
            with self.account_lock():
                return self.create_or_reuse_query_ids(
                    start_time, end_time, method, args_params
                )
        payload_args: Dict[str, Any] = {
            "email": self.email,
            "begin": start_time,
            "end": end_time,
        }
        payload_args.update(args_params or {})

        queries = self.checking_by_mail()
        matched = [
            q
            for q in queries
            if q.get("id") is not None and self._payload_match(q, method, payload_args)
        ]
        if matched:
            completed = [
                q for q in matched if self.status_has_keyword(q.get("status"), "done")
            ]
            chosen = (
                completed[0]
                if completed
                else max(matched, key=lambda q: str(q.get("created") or ""))
            )
            ids = [str(chosen["id"])]
            self.query_ids.update(ids)
            return ids

        return self.create_query(start_time, end_time, method, payload_args)

    @contextmanager
    def account_lock(self):
        """Serialize count + creation across local processes, never remote waiting."""
        root = getattr(
            self,
            "lock_root",
            Path(current()["backend"]["root"]) / "jobs" / "simurg-locks",
        )
        root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256((self.api_url + self.email).encode()).hexdigest()
        self._intent_path = root / f"{digest}.intent.json"
        # A separate SQLite lock per account also works in notebook-only
        # installations, without requiring the optional backend dependencies.
        with closing(
            sqlite3.connect(root / f"{digest}.sqlite3", timeout=self.timeout * 4)
        ) as db:
            db.execute("BEGIN IMMEDIATE")
            self._locked = True
            try:
                yield
            finally:
                self._locked = False
                db.rollback()
