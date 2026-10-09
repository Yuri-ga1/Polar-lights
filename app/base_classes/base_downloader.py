from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import requests

from app.logging_config import get_logger, logged_stage
from app.progress_bar import ProgressBar
from app.storage.atomic import publish

logger = get_logger(__name__)


class BaseDownloader:
    """Базовый класс для загрузчиков."""

    def __init__(self, out_dir: str = ".") -> None:
        self.out_dir = out_dir
        os.makedirs(self.out_dir, exist_ok=True)

    def _write_text_file(self, filename: str, content: str) -> str:
        file_path = os.path.join(self.out_dir, filename)
        with open(file_path + ".tmp", "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        publish(file_path + ".tmp", file_path)
        return file_path

    def _get_existing_file(self, filename: str, min_size_bytes: int = 1) -> Optional[str]:
        """Возвращает путь к уже скачанному файлу, если он существует и не пустой."""
        file_path = os.path.join(self.out_dir, filename)
        if os.path.exists(file_path) and os.path.getsize(file_path) >= min_size_bytes:
            if filename.endswith((".h5", ".hdf5")):
                import h5py
                try:
                    with h5py.File(file_path, "r") as handle:
                        if not len(handle):
                            return None
                except (OSError, ValueError):
                    return None
            return file_path
        return None

    @logged_stage("download", entry=False)
    def _download_result(
        self,
        url: str,
        filename: str = None,
        timeout: float = 60,
        verify: bool = True,
        polling_interval: float = 5,
        chunk_size: int = 1024 * 1024,
        show_progress: bool = True,
    ) -> str:
        """Скачивает файл с докачкой до полного получения."""
        filename = os.path.basename(url) if filename is None else filename
        file_path = os.path.join(self.out_dir, filename)
        
        existing_file = self._get_existing_file(filename)
        if existing_file:
            logger.info(f"Using cached file: {existing_file}", extra={"event": "cache_hit"})
            return existing_file
        
        logger.info(f"Downloading results from {url}", extra={"event": "download_status"})

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

        final_path = file_path
        file_path += ".part"
        validator_path = Path(file_path + ".json")
        for attempt in range(5):
            offset = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            try:
                validator = json.loads(validator_path.read_text())
            except (OSError, ValueError):
                validator = None
            if not validator:
                offset = 0
            headers = {"Range": f"bytes={offset}-", "If-Range": validator} if offset else {}

            try:
                resp = requests.get(
                    url,
                    timeout=timeout,
                    verify=verify,
                    headers=headers,
                    stream=True,
                )
            except requests.RequestException as exc:
                logger.warning("Download interrupted; retrying", extra={"event": "download_retry", "error": {"type": type(exc).__name__, "message": str(exc)}, "context": {"delay_seconds": polling_interval}})
                time.sleep(polling_interval)
                continue

            if resp.status_code == 416:
                resp.close()
                validator_path.unlink(missing_ok=True)
                continue
            if resp.status_code not in (200, 206):
                raise RuntimeError(f"Не удалось скачать по result_url {url}: {resp.status_code}")

            if resp.status_code == 206 and not resp.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                resp.close()
                raise RuntimeError("Invalid download Content-Range")
            received_validator = resp.headers.get("ETag") or resp.headers.get("Last-Modified")
            if resp.status_code == 206 and validator and received_validator != validator:
                resp.close()
                validator_path.unlink(missing_ok=True)
                continue
            validator = received_validator
            validator_path.write_text(json.dumps(validator))
            if resp.status_code == 200 and offset:
                offset = 0
                mode = "wb"
            else:
                mode = "ab" if offset else "wb"

            total_size = _extract_total_size(resp, offset)
            progress = (
                ProgressBar(
                    total=total_size,
                    current=offset,
                    description=filename,
                )
                if show_progress and total_size is not None
                else None
            )
            try:
                with open(file_path, mode) as f:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            f.flush()
                            if progress is not None:
                                progress.update(min(total_size, f.tell()))
                    f.flush()
                    os.fsync(f.fileno())
            except requests.RequestException as exc:
                logger.warning("Download interrupted; retrying", extra={"event": "download_retry", "error": {"type": type(exc).__name__, "message": str(exc)}, "context": {"delay_seconds": polling_interval}})
                time.sleep(polling_interval)
                continue

            finally:
                resp.close()
            final_size = os.path.getsize(file_path)
            if final_size and (total_size is None or final_size == total_size):
                if final_path.endswith((".h5", ".hdf5")):
                    import h5py
                    with h5py.File(file_path, "r") as handle:
                        if not len(handle):
                            raise ValueError("Empty HDF5 download")
                publish(file_path, final_path)
                validator_path.unlink(missing_ok=True)
                return final_path
        raise RuntimeError("Download retry limit reached; partial file retained")
