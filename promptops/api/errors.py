"""API error envelope and exception handlers.

Every error response has the shape ``{"error": {"code", "message", "details"}}``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def bad_request(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(400, "bad_request", message, details)


def not_found(message: str = "Resource not found") -> ApiError:
    return ApiError(404, "not_found", message)


def conflict(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(409, "conflict", message, details)


def forbidden(message: str) -> ApiError:
    return ApiError(403, "forbidden", message)


def validation_error(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(422, "validation_error", message, details)


def opencode_error(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(502, "opencode_error", message, details)


def _envelope(status: int, code: str, message: str, details: dict[str, Any] | None) -> JSONResponse:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status, content=payload)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _envelope(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details: dict[str, str] = {}
        for error in exc.errors():
            location = [
                str(part) for part in error.get("loc", []) if part not in ("body", "query", "path")
            ]
            field = ".".join(location) or "body"
            message = str(error.get("msg", "invalid value"))
            if field == "prompt" and message.startswith("Value error"):
                message = "Prompt cannot be empty"
            details[field] = message
        return _envelope(422, "validation_error", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "bad_request",
            409: "conflict",
        }.get(exc.status_code, "http_error")
        message = str(exc.detail) if exc.detail else "Request failed"
        return _envelope(exc.status_code, code, message, None)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled API error: %s", type(exc).__name__)
        return _envelope(500, "internal_error", "Internal server error", None)
