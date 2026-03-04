from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import requests


class SimurgClient:
    """Базовый клиент для работы с SIMuRG API."""

    def __init__(
        self,
        email: str,
        base_url: str = "https://simurg.iszf.irk.ru",
        polling_interval: int = 60,
        timeout: int = 30,
        verify: bool = True
    ) -> None:
        self.api_url = f'{base_url.rstrip("/")}/api'
        self.download_url = f'{base_url.rstrip("/")}/ufiles'
        self.timeout = timeout
        self.polling_interval = polling_interval
        self.verify = verify
        self.email = email
        self.query_ids: set[str] = set()

    def create_query(
        self,
        start_time: str,
        end_time: str,
        method: str,
        args_params: Dict[str, Any],
    ) -> List[str]:
        """Создаёт запрос к SIMuRG и возвращает список новых query_id."""
        print('Create new request')
        url = f"{self.api_url}"
        known_ids = self._to_id_set(self.checking_by_mail())
        payload: Dict[str, Any] = {
            "method": method,
            "args": {
                "email": self.email,
                "begin": start_time,
                "end": end_time,
            },
        }
        payload["args"].update(args_params)

        try:
            resp = requests.post(url, json=payload, timeout=self.timeout, verify=self.verify)
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
        if not isinstance(data, list):
            raise RuntimeError(f"Ожидался список запросов, пришло: {data}")

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
        s = str(s).strip().replace("T", " ")
        return s[:16] if len(s) >= 16 else s

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
        if not (server_type == 'map' and payload_type == 'create_map') and server_type != payload_type:
            return False

        if cls._norm_dt(server_query.get("begin")) != cls._norm_dt(payload_args.get("begin")):
            return False
        if cls._norm_dt(server_query.get("end")) != cls._norm_dt(payload_args.get("end")):
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

        return True

    def create_or_reuse_query_id(
        self,
        start_time: str,
        end_time: str,
        method: str,
        args_params: Dict[str, Any]
    ) -> str:
        """
        1) Ищет уже созданный запрос с теми же параметрами (payload).
           - Если нашёл (done/не done) -> возвращает его id.
        2) Если не нашёл -> создаёт новый и возвращает новый id.
        """
        payload_args: Dict[str, Any] = {
            "email": self.email,
            "begin": start_time,
            "end": end_time,
        }
        payload_args.update(args_params or {})

        # Find existing
        queries = self.checking_by_mail()
        matched = [q for q in queries if self._payload_match(q, method, payload_args)]
        print(f'Found {len(matched)} requests with same params')

        if matched:
            # Prefer done, else newest by created
            done = [q for q in matched if self.status_has_keyword(q.get("status"), "done")]
            chosen = done[0] if done else sorted(
                matched, key=lambda q: str(q.get("created") or ""), reverse=True
            )[0]
            req_iq = str(chosen.get("id"))
            self.query_ids.add(req_iq)
            print(f'Found created request with id: {req_iq}')
            return req_iq

        created_query_ids = self.create_query(start_time, end_time, method, payload_args)
        return created_query_ids[-1]

    def create_or_reuse_query_ids(
        self,
        start_time: str,
        end_time: str,
        method: str,
        args_params: Dict[str, Any],
    ) -> List[str]:
        """Возвращает все подходящие id запроса для дальнейшей проверки готовности."""
        payload_args: Dict[str, Any] = {
            "email": self.email,
            "begin": start_time,
            "end": end_time,
        }
        payload_args.update(args_params or {})

        queries = self.checking_by_mail()
        matched_ids = [
            str(q.get("id"))
            for q in queries
            if q.get("id") is not None and self._payload_match(q, method, payload_args)
        ]
        if matched_ids:
            self.query_ids.update(matched_ids)
            return sorted(set(matched_ids))

        return self.create_query(start_time, end_time, method, payload_args)
