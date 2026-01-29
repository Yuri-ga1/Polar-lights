from __future__ import annotations

from typing import Any, Dict, List, Optional

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
        self.download_url = f"{base_url.rstrip("/")}/ufiles"
        self.timeout = timeout
        self.polling_interval = polling_interval
        self.verify = verify
        self.email = email

    def create_query(
        self,
        start_time: str,
        end_time: str,
        method: str,
        args_params: Dict[str, Any],
    ) -> str:
        """Создаёт запрос к SIMuRG для получения данных и возвращает query_id."""
        print('Create new request')
        url = f"{self.api_url}"
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

        query_id = self.get_query_id()
        if not query_id:
            raise RuntimeError(f"Не удалось получить идентификатор запроса из ответа")
        
        print(f'id of new request is {query_id}')
        return query_id
    
    def get_query_id(self):
        req = self.checking_by_mail()
        data = req[-1]
        query_id = data.get("id")
        return str(query_id)

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
            print(cls._norm_dt(server_query.get("end")), cls._norm_dt(payload_args.get("end")))
            return False

        # coordinates: compare keys we send
        pcoords = payload_args.get("coordinates")
        if pcoords is not None:
            scoords = server_query.get("coordinates")
            if not isinstance(pcoords, dict) or not isinstance(scoords, dict):
                print('2')
                return False
            for k, v in pcoords.items():
                if scoords.get(k) != v:
                    print('3')
                    return False

        # options: compare keys we send
        popt = payload_args.get("options")
        if popt is not None:
            sopt = server_query.get("options")
            if not isinstance(popt, dict) or not isinstance(sopt, dict):
                print('4')
                return False
            for k, v in popt.items():
                if sopt.get(k) != v:
                    print('5')
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
            done = [q for q in matched if q.get("status") == "done"]
            chosen = done[0] if done else sorted(
                matched, key=lambda q: str(q.get("created") or ""), reverse=True
            )[0]
            req_iq = str(chosen.get("id"))
            print(f'Found created request with id: {req_iq}')
            return req_iq

        return self.create_query(start_time, end_time, method, payload_args)
