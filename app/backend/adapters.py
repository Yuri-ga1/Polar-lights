"""Thin adapters around the existing downloaders and scientific processors."""

import time
from pathlib import Path

import pandas as pd

from app.base_classes.base_processor import BaseProcessor
from app.storage.timeseries import TimeSeriesStorage

from .catalog import COLUMNS, column_spec
from .errors import BackendError
from .logging import get_logger

logger = get_logger(__name__)


class SourceAdapters:
    def __init__(self, root: Path):
        self.root = root

    def acquire(self, source, start, end, columns):
        begin = time.perf_counter()
        try:
            frame = getattr(self, source)(start, end, columns)
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(
                "DOWNLOAD_FAILED", f"Failed to acquire {source}", 502
            ) from exc
        logger.info(
            "source=%s acquisitionSeconds=%.3f", source, time.perf_counter() - begin
        )
        if frame is None or frame.empty:
            raise BackendError(
                "DATA_NOT_AVAILABLE", "Source returned no data", 404, source=source
            )
        frame = TimeSeriesStorage.normalize(frame)
        return frame.reindex(columns=columns).loc[start:end]

    def raw_dir(self, source):
        path = self.root / "raw" / source
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    @staticmethod
    def download(action, *args, **kwargs):
        begin = time.perf_counter()
        try:
            return action(*args, **kwargs)
        finally:
            logger.info(
                "Downloader=%s downloadSeconds=%.3f",
                action.__qualname__,
                time.perf_counter() - begin,
            )

    @staticmethod
    def process(action):
        pipeline_logger = get_logger("app.pipeline.adapters")
        pipeline_logger.info("Processing started", extra={"event": "processing_started", "context": {"operation": action.__qualname__}})
        begin = time.perf_counter()
        try:
            result = action()
            pipeline_logger.info("Processing completed", extra={"event": "processing_completed", "duration_ms": (time.perf_counter() - begin) * 1000, "context": {"operation": action.__qualname__, "records": len(result) if result is not None else 0}})
            return result
        except Exception as exc:
            raise BackendError(
                "PROCESSING_FAILED", "Source response could not be processed", 502
            ) from exc
        finally:
            logger.info(
                "Processor=%s processingSeconds=%.3f",
                action.__qualname__,
                time.perf_counter() - begin,
            )

    def omni(self, start, end, columns):
        from app.omni.omni_downloader import OmniDownloader
        from app.omni.omni_processor import OmniProcessor

        folder = self.raw_dir("omni")
        downloader = OmniDownloader(folder)
        path = self.download(
            downloader.download_range,
            start.to_pydatetime(),
            end.to_pydatetime(),
            columns,
        )
        processor = OmniProcessor(folder)

        def parse():
            pre = processor._extract_pre_block(Path(path).read_text(encoding="utf-8"))
            frame = processor._parse_table(
                pre, processor._parse_selected_parameters(pre)
            )
            return frame.rename(columns={s.raw_name: s.name for s in COLUMNS.values()})[
                ["datetime", *columns]
            ]

        return self.process(parse)

    def kp(self, start, end, columns):
        from app.gfz.gfz_downloader import GfzDownloader
        from app.gfz.gfz_processor import GfzProcessor

        path = self.download(
            GfzDownloader(self.raw_dir("kp")).download,
            start_date=str(start.date()),
            end_date=str(end.date()),
        )
        return self.process(
            lambda: GfzProcessor.to_processed_frame(GfzProcessor._load_kp_file(path))
        )

    def kyoto(self, start, end, columns):
        from app.kyoto.kyoto_dst_downloader import KyotoDstDownloader
        from app.kyoto.kyoto_dst_processor import KyotoProcessor

        folder = self.raw_dir("kyoto")
        frames = []
        # Kyoto publishes monthly files: fetch only months intersecting a gap.
        for month in pd.period_range(
            start.tz_localize(None), end.tz_localize(None), freq="M"
        ):
            path = self.download(
                KyotoDstDownloader(folder).download, str(month.start_time.date())
            )
            frame = self.process(
                lambda raw_path=path: KyotoProcessor(folder)._load_month_file(raw_path)
            )
            if not frame.empty:
                frames.append(
                    frame[["datetime", "dst"]].rename(columns={"dst": "kyoto_dst"})
                )
        return pd.concat(frames, ignore_index=True) if frames else None

    def nmdb(self, start, end, columns):
        """Read processed relative-amplitude series from nmdb.csv."""
        path = self.root / "processed" / "nmdb.csv"
        frame = BaseProcessor().read_processed(path)
        stations = {column_spec(c).raw_name: c for c in columns}
        available = [station for station in stations if station in frame]
        if not available:
            return pd.DataFrame()
        selected = BaseProcessor().select_processed(path, start, end)
        selected = selected.rename(
            columns={station: stations[station] for station in available}
        )
        return selected[[*BaseProcessor.time_columns, *[stations[s] for s in available]]]

    def nmdb_station_metadata(self):
        """Read station coordinates and altitude from the processed dimension file."""
        path = self.root / "processed" / "nmdb_stations.csv"
        if not path.is_file():
            return {}
        try:
            frame = pd.read_csv(path, usecols=["station", "lat", "lon", "alt"])
            frame["station"] = frame["station"].astype(str).str.upper()
            for column in ("lat", "lon", "alt"):
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            frame = frame.dropna(subset=["lat", "lon"]).drop_duplicates(
                "station", keep="last"
            )
            return {
                row.station: {
                    "latitude": float(row.lat),
                    "longitude": float(row.lon),
                    **({"altitudeMeters": float(row.alt)} if pd.notna(row.alt) else {}),
                }
                for row in frame.itertuples(index=False)
            }
        except (OSError, ValueError, pd.errors.ParserError):
            return {}

    def giro(self, start, end, columns):
        from app.ionosonde.ionosonde_downloader import IonosondeDownloader
        from app.ionosonde.ionosonde_processor import IonosondeProcessor

        folder = self.raw_dir("giro")
        frames = []
        for day in pd.date_range(start.normalize(), end.normalize(), freq="D"):
            report = self.download(
                IonosondeDownloader(folder).download,
                str(day.date()),
                station="AL945",
                days_range=0,
                filename=f"AL945_backend_{day:%Y%m%d}.txt",
            )
            path = report.output_path
            if not path:
                path = str(Path(folder) / f"AL945_backend_{day:%Y%m%d}.txt")

            def parse(raw_path=path):
                return IonosondeProcessor(folder)._parse_downloaded_text(
                    Path(raw_path).read_text(encoding="utf-8")
                )

            frames.append(
                self.process(parse).rename(
                    columns={"foF2": "giro_al945_fof2", "hmF2": "giro_al945_hmf2"}
                )
            )
        return pd.concat(frames, ignore_index=True) if frames else None

    def import_legacy(self, storage):
        """Non-destructive import. Old caches remain available to notebooks.

        NMDB is imported from the processed variation file and kept under an
        explicit amplitude-percent column name so it is never confused with counts.
        """
        for source in ("omni", "kp", "kyoto", "nmdb"):
            path = self.root / "processed" / f"{source}.csv"
            if not path.is_file():
                continue
            frame = BaseProcessor().read_processed(path)
            mapping = {
                s.raw_name: s.name for s in COLUMNS.values() if s.source == source
            }
            if source == "nmdb":
                mapping = {
                    column: f"nmdb_{column.lower()}_amplitude_percent"
                    for column in frame.columns
                    if column not in BaseProcessor.time_columns
                    and column.strip().lower() not in {"datetime", "date"}
                }
            frame = frame.rename(columns=mapping)
            columns = [c for c in mapping.values() if c in frame]
            if columns:
                storage.merge(
                    frame[[*BaseProcessor.time_columns, *columns]],
                    overwrite=(source == "nmdb"),
                )
