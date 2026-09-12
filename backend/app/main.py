import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.api.errors import ApiError
from app.api.routes import datasets, jobs, organizations, resources, workers
from app.auth.jwt import JWKSVerifier
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import database_ready, engine

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.jwks_verifier = JWKSVerifier(settings)
    yield
    await engine.dispose()


app = FastAPI(
    title="BladeForge AI API",
    version="1.0.0",
    description="Authenticated orchestration API for leading-edge erosion dataset generation.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Worker-Secret"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    clear_contextvars()
    bind_contextvars(request_id=request_id, method=request.method, path=request.url.path)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        await logger.ainfo("request_complete", elapsed_ms=elapsed_ms)
    response.headers["X-Request-ID"] = request_id
    return response


def error_payload(
    request: Request, code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, object]:
    return {
        "error": {
            "request_id": getattr(request.state, "request_id", "unknown"),
            "code": code,
            "message": message,
            "details": details,
        }
    }


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return ORJSONResponse(
        status_code=exc.status_code,
        content=error_payload(request, exc.code, exc.message, exc.details),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    details = {"fields": exc.errors()}
    return ORJSONResponse(
        status_code=422,
        content=error_payload(request, "validation_error", "Request validation failed.", details),
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    await logger.awarning("database_integrity_error", error_type=type(exc.orig).__name__)
    return ORJSONResponse(
        status_code=409,
        content=error_payload(
            request, "resource_conflict", "The request conflicts with an existing resource."
        ),
    )


@app.exception_handler(DBAPIError)
async def database_error_handler(request: Request, exc: DBAPIError):
    await logger.aerror(
        "database_error",
        error_type=type(exc.orig).__name__,
        detail=str(exc.orig)[:500],
    )
    return ORJSONResponse(
        status_code=503,
        content=error_payload(request, "database_unavailable", "The database is unavailable."),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    await logger.aexception("unhandled_error", error_type=type(exc).__name__)
    return ORJSONResponse(
        status_code=500,
        content=error_payload(request, "internal_error", "An unexpected error occurred."),
    )


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def ready():
    if not await database_ready():
        return ORJSONResponse(status_code=503, content={"status": "not_ready"})
    return {"status": "ready"}


app.include_router(organizations.router, prefix="/v1")
app.include_router(jobs.router, prefix="/v1")
app.include_router(jobs.external_router, prefix="/v1")
app.include_router(datasets.router, prefix="/v1")
app.include_router(datasets.external_router, prefix="/v1")
app.include_router(resources.router, prefix="/v1")
app.include_router(workers.router, prefix="/v1")
