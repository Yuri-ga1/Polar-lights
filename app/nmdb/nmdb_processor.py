from __future__ import annotations

import json
import os
import re
from typing import Optional, Tuple

import pandas as pd
import numpy as np
from app.base_classes.base_processor import BaseProcessor


class NmdbProcessor(BaseProcessor):
    """
    Локальный процессор NMDB-файлов, сохранённых NmdbDownloader.

    Возвращает:
    - pd.DataFrame, если файл найден и успешно распарсен
    - None, если файла нет / он пустой / не удалось распарсить

    Ожидаемый формат данных (после HTML) — ASCII блок из NMDB, где:
    - есть строка заголовков со станциями (колонки выровнены пробелами)
    - далее строки вида: "YYYY-MM-DD HH:MM:SS; v1; v2; ..."

    Значения 'null' конвертируются в NaN.
    """

    METADATA_FILENAME = "nmdb_station_metadata.json"

    def __init__(self, folder_path: str) -> None:
        super().__init__(folder_path)

    # ---------- helpers ----------

    def _build_filename(self, date_str: str) -> Tuple[str, str, str]:
        """
        Возвращает варианты имён файла, которые мог создать downloader:
        1) nmdb_all_YYYYMMDDHHMM-YYYYMMDDHHMM.txt   (если used all stations)
        2) nmdb_*_YYYYMMDDHHMM-YYYYMMDDHHMM.txt    (любой station_part)
        3) nmdb_*_YYYYMMDD-YYYYMMDD.txt            (на всякий случай)
        """
        d = self._parse_date(date_str)
        month_anchor = f"{d.strftime('%Y%m')}"
        day_anchor = f"{d.strftime('%Y%m%d')}"
        return (
            f"nmdb_*_{day_anchor}*.txt",
            f"nmdb_*_{month_anchor}*.txt",
            "nmdb_*.txt",
        )

    def _pick_existing_file(self, patterns: Tuple[str, str, str]) -> Optional[str]:
        """
        Возвращает путь к первому существующему и непустому файлу (в порядке приоритета),
        либо None.
        """
        import glob

        for pat in patterns:
            matches = sorted(glob.glob(self._full_path(pat)))
            for path in matches:
                if self._is_non_empty_file(path):
                    return path
        return None

    # ---------- cleaning / extraction ----------

    @staticmethod
    def _extract_ascii_block(raw: str) -> str:
        """
        NMDB часто возвращает HTML, внутри которого ASCII-данные лежат в:
        <pre><code> ... </code></pre>

        Если блок не найден — считаем, что файл уже plain text.
        """
        m = re.search(
            r"<pre>\s*<code>(.*?)</code>\s*</pre>",
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return m.group(1) if m else raw

    @staticmethod
    def _strip_html_tags(text: str) -> str:
        """
        На случай если в ASCII-блок всё же просочились теги/сущности.
        Делает “грубую” зачистку.
        """
        text = re.sub(r"<[^>]+>", "", text)
        text = (
            text.replace("&nbsp;", " ")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
        )
        return text

    @staticmethod
    def _keep_only_table(text: str) -> str:
        """
        Оставляет только “табличную” часть: от строки со станциями до конца таблицы.

        В примере NMDB:
        - есть строка со станциями (много пробелов + коды станций)
        - следующая строка начинается с 'YYYY-MM-DD ...;'
        """
        lines = [ln.rstrip("\n") for ln in text.splitlines()]

        data_idx = None
        for i, ln in enumerate(lines):
            if re.match(r"^\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s*;", ln):
                data_idx = i
                break
        if data_idx is None:
            raise ValueError("Не найдены строки данных вида 'YYYY-MM-DD HH:MM:SS; ...'")

        header_idx = None
        for j in range(data_idx - 1, -1, -1):
            ln = lines[j].strip()
            if not ln or ln.startswith("#"):
                continue

            tokens = re.findall(r"[A-Z0-9]{3,6}", ln)
            if ";" not in ln and len(tokens) >= 2:
                header_idx = j
                break

        if header_idx is None:
            raise ValueError("Не найдена строка заголовков со станциями.")

        table_lines = [lines[header_idx]] + lines[data_idx:]
        return "\n".join(table_lines).strip()
    
    @staticmethod
    def _to_amplitude(
        df: pd.DataFrame,
        baseline: str = "median",   # "mean" | "median" | "first"
        absolute: bool = False,     # True -> |A(t)|
    ) -> pd.DataFrame:
        """
        Превращает сырые значения станций в амплитуду вариаций по времени.

        Возвращает df:
        - datetime
        - станции: амплитуда в % относительно baseline

        baseline:
          - "mean": x0 = среднее по периоду
          - "median": x0 = медиана по периоду (устойчивее к выбросам)
          - "first": x0 = первое непустое значение
        absolute:
          - если True -> берём модуль амплитуды
        """
        if df is None or df.empty:
            return df

        out = df.copy()
        station_cols = [c for c in out.columns if c != "datetime"]

        for c in station_cols:
            out[c] = pd.to_numeric(out[c], errors="coerce").astype("float64")

        if baseline == "mean":
            x0 = out[station_cols].mean(skipna=True)
        elif baseline == "median":
            x0 = out[station_cols].median(skipna=True)
        elif baseline == "first":
            x0 = out[station_cols].apply(lambda s: s.dropna().iloc[0] if not s.dropna().empty else np.nan)
        else:
            raise ValueError("baseline must be one of: 'mean', 'median', 'first'")

        x0 = x0.replace({0.0: np.nan})

        amp = (out[station_cols].div(x0) - 1.0) * 100.0
        if absolute:
            amp = amp.abs()

        out[station_cols] = amp
        return out

    # ---------- parsing ----------

    @staticmethod
    def _parse_table(table_text: str) -> pd.DataFrame:
        """
        Парсит текст вида:

                           CHAC    ICRB   ...
        2025-11-01 00:00:00; null; 7.036; ...

        Возвращает DataFrame:
        - datetime (datetime64[ns])
        - далее колонки станций (float, NaN where null)
        """
        lines = [ln.rstrip() for ln in table_text.splitlines() if ln.strip()]
        if len(lines) < 2:
            raise ValueError("Таблица слишком короткая.")

        header_line = lines[0].strip()
        stations = re.findall(r"[A-Z0-9]{3,6}", header_line)
        if not stations:
            raise ValueError("Не удалось извлечь коды станций из заголовка.")

        records = []
        for ln in lines[1:]:
            if not re.match(r"^\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s*;", ln):
                continue

            parts = [p.strip() for p in ln.split(";")]
            if len(parts) < 2:
                continue

            ts = parts[0]
            values = parts[1:]

            if values and values[-1] == "":
                values = values[:-1]

            if len(values) < len(stations):
                continue

            row = {"datetime": pd.to_datetime(ts, errors="coerce")}
            for st, v in zip(stations, values[: len(stations)]):
                vv = v.strip().lower()
                if vv in ("null", "nan", ""):
                    row[st] = pd.NA
                else:
                    row[st] = pd.to_numeric(v, errors="coerce")
            records.append(row)

        df = pd.DataFrame.from_records(records)
        if df.empty:
            return df

        df = df.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
        return df
    
    def _load_station_metadata(self) -> dict[str, dict[str, float]]:
        path = self._full_path(self.METADATA_FILENAME)

        if not os.path.exists(path):
            return {}

        try:
            with open(path, "r", encoding="utf-8") as file:
                raw_metadata = json.load(file)
        except Exception:
            return {}

        metadata: dict[str, dict[str, float]] = {}

        for station, values in raw_metadata.items():
            try:
                metadata[station] = {
                    "lat": float(values["lat"]),
                    "lon": float(values["lon"]),
                    "alt": float(values["alt"]),
                }
            except Exception:
                continue

        return metadata

    # ---------- public ----------

    def load(self, date_str: str) -> Optional[pd.DataFrame]:
        """
        Ищет подходящий nmdb_*.txt в папке и возвращает DataFrame.
        date_str используется для подбора файла (как в OmniProcessor).
        """
        patterns = self._build_filename(date_str)
        path = self._pick_existing_file(patterns)
        if not self._is_non_empty_file(path):
            return None

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()

            text = self._extract_ascii_block(raw)

            text = self._strip_html_tags(text)

            table_text = self._keep_only_table(text)

            df = self._parse_table(table_text)
            
            if df.empty:
                return None

            df = self._to_amplitude(df, baseline="median", absolute=False)
            
            station_cols = [c for c in df.columns if c != "datetime"]
            station_metadata = self._load_station_metadata()

            df.attrs["station_metadata"] = {
                station: station_metadata[station]
                for station in station_cols
                if station in station_metadata
            }

            return df
        except Exception:
            return None
