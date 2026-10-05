"""ASGI entrypoint: uvicorn app.backend.api:create_app --factory."""

import hmac
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from filelock import Timeout
from starlette.exceptions import HTTPException

from .catalog import PRODUCTS
from .config import Settings
from .errors import BackendError
from .jobs import JobRunner, JobStore
from .logging import get_logger
from .logging import request_id as request_context_id
from .models import (
    AuroraGeomagneticLinesRequest,
    AuroraGeomagneticLinesResponse,
    AuroraMapResponse,
    AvailabilityResponse,
    CatalogResponse,
    DataRequest,
    ErrorResponse,
    JobAccepted,
    JobStatus,
    KeogramResponse,
    MapJsonResponse,
    MapRenderSpec,
    RenderFiles,
    SeriesResponse,
)
from .render import asset_manifest
from .service import DataService

logger = get_logger(__name__)
ERRORS = {
    code: {"model": ErrorResponse}
    for code in (400, 401, 404, 409, 413, 422, 429, 500, 502, 503, 504)
}


def create_app(settings=None, service=None, *, start_jobs=True):
    settings = settings or Settings()
    service = service or DataService(settings)
    jobs = JobStore(settings)
    runner = JobRunner(jobs)

    @asynccontextmanager
    async def lifespan(app):
        service.initialize()
        if start_jobs:
            runner.start()
        try:
            yield
        finally:
            runner.close()

    app = FastAPI(
        title="Polar Lights API", version="1.0.0", lifespan=lifespan, responses=ERRORS
    )
    app.state.service, app.state.jobs = service, jobs
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", "X-API-Key", "Prefer"],
            expose_headers=["X-Request-ID", "Location"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = uuid.uuid4().hex
        request_context_id.set(request_id)
        began = time.perf_counter()
        if settings.api_key and not hmac.compare_digest(
            request.headers.get("X-API-Key", ""), settings.api_key
        ):
            return JSONResponse(
                BackendError("UNAUTHORIZED", "Invalid API key", 401).body(),
                status_code=401,
            )
        if request.method == "POST":
            # Bound even chunked bodies, before JSON/Pydantic parsing.
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 64 * 1024:
                    return JSONResponse(
                        BackendError(
                            "INVALID_REQUEST", "Request body exceeds 64 KiB", 413
                        ).body(),
                        status_code=413,
                    )
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "requestId=%s method=%s path=%s status=%s durationSeconds=%.3f responseBytes=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            time.perf_counter() - began,
            response.headers.get("content-length", "stream"),
        )
        return response

    @app.exception_handler(BackendError)
    async def backend_error(request, exc):
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        if (
            isinstance(exc.body, dict)
            and exc.body.get("productId")
            and exc.body["productId"] not in PRODUCTS
        ):
            return JSONResponse(
                BackendError("PRODUCT_NOT_FOUND", "Unknown product", 404).body(),
                status_code=404,
            )
        details = [
            {"location": list(e["loc"]), "message": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            BackendError(
                "INVALID_REQUEST", "Request validation failed", 422, errors=details
            ).body(),
            status_code=422,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            BackendError("INVALID_REQUEST", str(exc.detail), exc.status_code).body(),
            status_code=exc.status_code,
        )

    @app.exception_handler(Timeout)
    async def lock_timeout(request, exc):
        return JSONResponse(
            BackendError("STORAGE_BUSY", "Storage is busy; retry later", 503).body(),
            status_code=503,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.error("request failed path=%s", request.url.path, exc_info=exc)
        code = (
            "STORAGE_ERROR"
            if isinstance(exc, (OSError, ValueError))
            else "PROCESSING_FAILED"
        )
        return JSONResponse(
            BackendError(code, "The request could not be completed", 500).body(),
            status_code=500,
        )

    @app.get("/api/v1/health")
    def health() -> dict:
        return {"status": "ok", "apiVersion": "1.0.0"}

    @app.post(
        "/api/v1/aurora-map/geomagnetic-lines",
        response_model=AuroraGeomagneticLinesResponse,
    )
    def aurora_geomagnetic_lines(body: AuroraGeomagneticLinesRequest) -> dict:
        return service.aurora_geomagnetic_lines(body.timestamp, body.latitudes)

    @app.get(
        "/api/v1/catalog",
        response_model=CatalogResponse,
        response_model_exclude_none=True,
    )
    def get_catalog() -> dict:
        return service.catalog()

    @app.get(
        "/api/v1/products/{productId}/availability", response_model=AvailabilityResponse
    )
    def availability(
        productId: str,
        start: datetime | None = None,
        end: datetime | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(1000, ge=1, le=5000),
    ) -> dict:
        return service.availability(productId, start, end, offset, limit)

    @app.post(
        "/api/v1/data",
        response_model=SeriesResponse
        | MapJsonResponse
        | KeogramResponse
        | AuroraMapResponse,
        responses={
            200: {
                "content": {
                    "application/vnd.apache.arrow.stream": {
                        "schema": {"type": "string", "format": "binary"}
                    }
                }
            },
            202: {"model": JobAccepted},
        },
    )
    def data(body: DataRequest, prefer: str | None = Header(None)):
        service.validate(body)
        cached = service.cached(body)
        logger.info(
            "productId=%s parameters=%s cache=%s",
            body.productId,
            body.parameters.model_dump(mode="json"),
            "hit" if cached else "miss",
        )
        if not cached or prefer == "respond-async":
            job_id = jobs.submit("data", body.model_dump(mode="json"))
            result = JobAccepted(
                jobId=job_id,
                statusUrl=f"/api/v1/jobs/{job_id}",
                resultUrl=f"/api/v1/jobs/{job_id}/result",
            )
            return JSONResponse(
                result.model_dump(),
                status_code=202,
                headers={"Location": result.statusUrl},
            )
        payload, media = service.response(body)
        return Response(payload, media_type=media)

    @app.get(
        "/api/v1/jobs/{jobId}",
        response_model=JobStatus,
        response_model_exclude_none=True,
    )
    def get_job(jobId: str) -> dict:
        return jobs.public(jobId, "data")

    @app.delete(
        "/api/v1/jobs/{jobId}",
        response_model=JobStatus,
        response_model_exclude_none=True,
    )
    def cancel_job(jobId: str) -> dict:
        return jobs.cancel(jobId, "data")

    @app.get(
        "/api/v1/jobs/{jobId}/result",
        responses={
            200: {
                "content": {
                    "application/json": {},
                    "application/vnd.apache.arrow.stream": {
                        "schema": {"type": "string", "format": "binary"}
                    },
                }
            }
        },
    )
    def get_result(jobId: str):
        path, media = jobs.artifact(jobId, kind="data")
        return FileResponse(path, media_type=media)

    @app.get("/api/v1/render-assets")
    def render_assets() -> dict:
        return asset_manifest(settings.render_assets)

    @app.get("/api/v1/render-assets/{filename}")
    def render_asset(filename: str):
        manifest = asset_manifest(settings.render_assets)
        if filename not in manifest["files"]:
            raise BackendError("FILE_NOT_FOUND", "Unknown render asset", 404)
        return FileResponse(settings.render_assets / filename)

    @app.post(
        "/api/v1/map-render-jobs",
        status_code=202,
        response_model=JobStatus,
        response_model_exclude_none=True,
    )
    def submit_render(spec: MapRenderSpec) -> dict:
        manifest = asset_manifest(settings.render_assets)
        if spec.assetVersion != manifest["assetVersion"]:
            raise BackendError(
                "INVALID_REQUEST", "Render asset version does not match", 409
            )
        job_id = jobs.submit("render", spec.model_dump(mode="json"))
        return jobs.public(job_id, "render")

    @app.get(
        "/api/v1/map-render-jobs/{jobId}",
        response_model=JobStatus,
        response_model_exclude_none=True,
    )
    def render_job(jobId: str) -> dict:
        return jobs.public(jobId, "render")

    @app.get("/api/v1/map-render-jobs/{jobId}/files", response_model=RenderFiles)
    def render_files(jobId: str) -> dict:
        row = jobs.get(jobId, "render")
        return {
            "jobId": jobId,
            "status": row["status"],
            "files": [
                {
                    "name": filename,
                    "url": f"/api/v1/map-render-jobs/{jobId}/files/{filename}",
                }
                for filename in json.loads(row["files"] or "[]")
                if row["status"] == "completed"
            ],
        }

    @app.get("/api/v1/map-render-jobs/{jobId}/files/{filename}")
    def render_file(jobId: str, filename: str):
        path, _ = jobs.artifact(jobId, filename, kind="render")
        return FileResponse(
            path,
            media_type="application/json"
            if filename.endswith(".json")
            else "image/png",
        )

    @app.delete(
        "/api/v1/map-render-jobs/{jobId}",
        response_model=JobStatus,
        response_model_exclude_none=True,
    )
    def cancel_render(jobId: str) -> dict:
        return jobs.cancel(jobId, "render")

    return app
