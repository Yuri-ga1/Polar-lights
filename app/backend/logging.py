"""Request/job context without modifying the application's global logging setup."""

import logging
from contextvars import ContextVar

request_id = ContextVar("polar_request_id", default="-")
job_id = ContextVar("polar_job_id", default="-")


class ContextLogger(logging.LoggerAdapter):
    def process(self, message, kwargs):
        return f"requestId={request_id.get()} jobId={job_id.get()} {message}", kwargs


def get_logger(name):
    return ContextLogger(logging.getLogger(name), {})
