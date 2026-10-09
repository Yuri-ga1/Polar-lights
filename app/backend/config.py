import os
from dataclasses import dataclass, field
from pathlib import Path

from app.configuration import FIELDS, current


@dataclass(frozen=True, init=False)
class Settings:
    root: Path = field(
        default_factory=lambda: Path(current()["backend"]["root"])
    )
    max_samples: int = field(default_factory=lambda: current()["backend"]["max_samples"])
    max_cells: int = field(default_factory=lambda: current()["backend"]["max_cells"])
    max_points: int = field(default_factory=lambda: current()["backend"]["max_points"])
    max_response_bytes: int = field(default_factory=lambda: current()["backend"]["max_response_bytes"])
    max_days: int = field(default_factory=lambda: current()["backend"]["max_days"])
    job_timeout: int = field(default_factory=lambda: current()["backend"]["job_timeout"])
    job_workers: int = field(default_factory=lambda: current()["backend"]["job_workers"])
    max_jobs: int = field(default_factory=lambda: current()["backend"]["max_jobs"])
    simurg_email: str = field(default_factory=lambda: os.getenv("SIMURG_EMAIL", ""))
    api_key: str = field(default_factory=lambda: os.getenv("POLAR_API_KEY", ""))
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(current()["backend"]["cors_origins"])
    )
    render_assets: Path = field(
        default_factory=lambda: Path(current()["backend"]["render_assets"])
    )

    long_job_timeout: int = field(default_factory=lambda: current()["backend"]["long_job_timeout"])
    job_max_attempts: int = field(default_factory=lambda: current()["backend"]["job_max_attempts"])
    external_wait_timeout: int = field(default_factory=lambda: current()["backend"]["external_wait_timeout"])

    def __init__(self, *args, _snapshot=None, **kwargs):
        names = tuple(self.__dataclass_fields__)
        if len(args) > len(names):
            raise TypeError("Too many positional Settings arguments")
        if set(kwargs) - set(names):
            raise TypeError(f"Unknown Settings arguments: {sorted(set(kwargs) - set(names))}")
        if any(name in kwargs for name in names[:len(args)]):
            raise TypeError("Settings argument supplied twice")
        values = {key: spec[0] for key, spec in FIELDS["backend"].items()}
        values.update((_snapshot or current())["backend"])
        defaults = {
            **values,
            "root": Path(values["root"]),
            "render_assets": Path(values["render_assets"]),
            "cors_origins": tuple(values["cors_origins"]),
            "simurg_email": os.getenv("SIMURG_EMAIL", ""),
            "api_key": os.getenv("POLAR_API_KEY", ""),
        }
        defaults.update(zip(names, args))
        defaults.update(kwargs)
        for name in names:
            object.__setattr__(self, name, defaults[name])

    @classmethod
    def from_snapshot(cls, snapshot):
        values = snapshot["backend"]
        return cls(
            **{key: Path(value) if key in {"root", "render_assets"} else
               tuple(value) if key == "cors_origins" else value
               for key, value in values.items()},
            simurg_email=os.getenv("SIMURG_EMAIL", ""),
            api_key=os.getenv("POLAR_API_KEY", ""),
            _snapshot=snapshot,
        )


class LiveSettings:
    """Existing service API backed by a request-pinned manager snapshot."""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self._secrets = {"api_key": os.getenv("POLAR_API_KEY", ""),
                         "simurg_email": os.getenv("SIMURG_EMAIL", "")}

    def __getattr__(self, name):
        if name in self._secrets:
            return self._secrets[name]
        if name in Settings.__dataclass_fields__:
            return getattr(Settings.from_snapshot(current()), name)
        raise AttributeError(name)

    def snapshot(self):
        return Settings.from_snapshot(current())
