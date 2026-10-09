"""Single-host queue coordinator: python -m app.backend.worker."""

import signal
import threading

from app.configuration import manager
from app.logging_config import configure_logging

from .config import LiveSettings
from .jobs import JobRunner, JobStore


def main():
    config = manager()
    config.start()
    configure_logging()
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    runner = JobRunner(JobStore(LiveSettings(config)))
    runner.start()
    try:
        stopped.wait()
    finally:
        runner.close()
        config.close()


if __name__ == "__main__":
    main()
