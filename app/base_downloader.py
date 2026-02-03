from __future__ import annotations

import os
import time
from typing import Optional

import requests


class BaseDownloader:
    """Базовый класс для загрузчиков."""

    def __init__(self, out_dir: str = ".") -> None:
        self.out_dir = out_dir
        os.makedirs(self.out_dir, exist_ok=True)

    def _write_text_file(self, filename: str, content: str) -> str:
        file_path = os.path.join(self.out_dir, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return file_path

    def _download_result(
        self,
        url: str,
        *,
        timeout: float = 60,
        verify: bool = True,
        polling_interval: float = 5,
        chunk_size: int = 1024 * 1024,
    ) -> str:
        """Скачивает файл с докачкой до полного получения."""
        print(f"Downloading results from {url}")
        filename = os.path.basename(url)
        file_path = os.path.join(self.out_dir, filename)

        def _extract_total_size(resp: requests.Response, offset: int) -> Optional[int]:
            content_range = resp.headers.get("Content-Range")
            if content_range and "/" in content_range:
                total_str = content_range.split("/")[-1]
                if total_str.isdigit():
                    return int(total_str)
            content_length = resp.headers.get("Content-Length")
            if content_length and content_length.isdigit():
                length = int(content_length)
                if resp.status_code == 206:
                    return offset + length
                return length
            return None

        while True:
            offset = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}

            try:
                resp = requests.get(
                    url,
                    timeout=timeout,
                    verify=verify,
                    headers=headers,
                    stream=True,
                )
            except requests.RequestException:
                time.sleep(polling_interval)
                continue

            if resp.status_code not in (200, 206):
                raise RuntimeError(f"Не удалось скачать по result_url {url}: {resp.status_code}")

            if resp.status_code == 200 and offset:
                offset = 0
                mode = "wb"
            else:
                mode = "ab" if offset else "wb"

            total_size = _extract_total_size(resp, offset)
            try:
                with open(file_path, mode) as f:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
            except requests.RequestException:
                time.sleep(polling_interval)
                continue

            final_size = os.path.getsize(file_path)
            if total_size is None or final_size >= total_size:
                return file_path
