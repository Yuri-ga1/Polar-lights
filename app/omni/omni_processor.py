from __future__ import annotations

import re
from typing import Optional, Dict, List, Tuple

import pandas as pd
from app.base_classes.base_processor import BaseProcessor


class OmniProcessor(BaseProcessor):
    """
    Локальный процессор OMNI-файлов, сохранённых OmniDownloader.

    Возвращает:
    - pd.DataFrame, если файл найден и успешно распарсен
    - None, если файла нет / он пустой / не удалось распарсить
    """

    def __init__(self, folder_path: str) -> None:
        super().__init__(folder_path)

    def _build_filename(self, date_str: str) -> Tuple[str, str]:
        """
        Возвращает два варианта имени файла:
        1) omni_YYYYMMDD.txt
        2) omni_YYYYMM.txt
        """
        d = self._parse_date(date_str)
        with_day = f"omni_{d.strftime('%Y%m%d')}.txt"
        without_day = f"omni_{d.strftime('%Y%m')}.txt"
        return with_day, without_day


    def _pick_existing_file(self, filenames: Tuple[str, str]) -> Optional[str]:
        """
        Возвращает путь к первому существующему и непустому файлу (в порядке приоритета),
        либо None.
        """
        for name in filenames:
            path = self._full_path(name)
            if self._is_non_empty_file(path):
                return path
        return None

    # ---------- parsing ----------

    @staticmethod
    def _extract_pre_block(text: str) -> str:
        """
        В OMNI-файле данные обычно находятся внутри <pre>...</pre>.
        Если <pre> не найден — считаем, что файл уже plain text.
        """
        m = re.search(r"<pre>(.*?)</pre>", text, flags=re.IGNORECASE | re.DOTALL)
        return m.group(1) if m else text

    @staticmethod
    def _parse_selected_parameters(pre_text: str) -> Dict[int, str]:
        """
        Парсит блок:
        Selected parameters:
         1 BX, nT (GSE, GSM)
         2 BY, nT (GSE)
         ...
        """
        m = re.search(
            r"Selected parameters:\s*(.*?)\n\s*YYYY\s+DOY\s+HR\s+MN",
            pre_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not m:
            raise ValueError("Не найден блок Selected parameters или заголовок таблицы.")

        block = m.group(1)
        mapping: Dict[int, str] = {}

        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            mm = re.match(r"^(\d+)\s+(.*)$", line)
            if not mm:
                continue
            mapping[int(mm.group(1))] = mm.group(2).strip()

        if not mapping:
            raise ValueError("Не удалось распарсить список параметров OMNI.")
        return mapping
    
    @staticmethod
    def _normalize_column_name(name: str) -> str:
        name = name.lower()
        name = name.split(",")[0]
        name = name.split("-")[0]
        name = name.replace("/", "")
        name = re.sub(r"\s+", " ", name)
        return name.strip()


    @staticmethod
    def _parse_table(pre_text: str, param_map: Dict[int, str]) -> pd.DataFrame:
        header_match = re.search(
            r"^\s*YYYY\s+DOY\s+HR\s+MN.*?$",
            pre_text,
            flags=re.MULTILINE,
        )
        if not header_match:
            raise ValueError("Не найдена строка заголовка таблицы.")

        table_text = pre_text[header_match.start():].strip()
        lines = table_text.splitlines()
        if len(lines) < 2:
            raise ValueError("Таблица слишком короткая.")

        header_tokens = lines[0].split()
        base_cols = ["year", "doy", "hr", "mn"]

        param_indices: List[int] = [
            int(t) for t in header_tokens[4:] if t.isdigit()
        ]
        if not param_indices:
            raise ValueError("Не удалось извлечь индексы параметров.")

        temp_cols = [f"p{idx}" for idx in param_indices]
        cols = base_cols + temp_cols

        df = pd.read_csv(
            pd.io.common.StringIO("\n".join(lines[1:])),
            sep=r"\s+",
            header=None,
            names=cols,
            engine="python",
            on_bad_lines="skip",
        )

        if df.empty:
            return df

        # типы
        df[base_cols] = df[base_cols].astype(int)

        # fill values → NaN
        for c in temp_cols:
            s = df[c].astype(str).str.strip()
            mask = s.str.match(r"^9+(\.9+)?$")

            df.loc[mask, c] = pd.NA
            df[c] = pd.to_numeric(df[c], errors="coerce")


        # DateTime
        dt = (
            pd.to_datetime(df["year"].astype(str), format="%Y")
            + pd.to_timedelta(df["doy"] - 1, unit="D")
            + pd.to_timedelta(df["hr"], unit="h")
            + pd.to_timedelta(df["mn"], unit="m")
        )
        df.insert(0, "DateTime", dt)

        # переименование колонок
        rename_map = {
            f"p{idx}": re.sub(r"\s+", " ", param_map.get(idx, f"param_{idx}")).strip()
            for idx in param_indices
        }
        df = df.rename(columns=rename_map)
        df = df.rename(columns=OmniProcessor._normalize_column_name)

        return df

    def load(self, date_str: str) -> Optional[pd.DataFrame]:
        filenames = self._build_filename(date_str)
        path = self._pick_existing_file(filenames)

        if not self._is_non_empty_file(path):
            return None

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()

            pre = self._extract_pre_block(raw)
            param_map = self._parse_selected_parameters(pre)
            df = self._parse_table(pre, param_map)

            return None if df.empty else df
        except Exception:
            return None
