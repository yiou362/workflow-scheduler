"""FastAPI application factory and lifespan."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from promptops import __version__
from promptops.api.errors import install_error_handlers
from promptops.api.routes_dashboard import router as dashboard_router
from promptops.api.routes_endpoints import router as endpoints_router
from promptops.api.routes_meta import router as meta_router
from promptops.api.routes_runs import router as runs_router
from promptops.api.routes_tasks import router as tasks_router
from promptops.config import Settings, get_settings
from promptops.db import (
    build_engine,
    build_session_factory,
    check_sqlite_version,
    dispose_engine,
    run_migrations_async,
)
from promptops.ids import new_id
from promptops.logging import configure_logging
from promptops.models import Endpoint
from promptops.repositories import endpoints as endpoint_repo
from promptops.runtime import Runtime
from promptops.security import get_secret_box
from promptops.services.endpoint_service import normalize_base_url
from promptops.timeutil import Clock, SystemClock
from promptops.web.spa import install_spa

logger = logging.getLogger(__name__)


async def _seed_default_endpoint(runtime: Runtime, settings: Settings) -> None:
    if not settings.default_endpoint_url:
        return
    async with runtime.session_factory() as session:
        if await endpoint_repo.count(session) > 0:
            return
        try:
            base_url = normalize_base_url(settings.default_endpoint_url)
        except Exception:  # noqa: BLE001 - invalid seed must not stop the app
            logger.error("ignoring invalid PROMPTOPS_DEFAULT_ENDPOINT_URL")
            return
        now = runtime.clock.now_ms()
        password = settings.default_endpoint_password
        endpoint = Endpoint(
            id=new_id("endpoint"),
            name=(settings.default_endpoint_name or "Local OpenCode").strip() or "Local OpenCode",
            description="Seeded from environment",
            base_url=base_url,
            auth_type="basic" if password else "none",
            auth_username=settings.default_endpoint_username if password else None,
            secret_ciphertext=runtime.secret_box.encrypt(password) if password else None,
            is_default=True,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        session.add(endpoint)
        await session.commit()
        logger.info("seeded default endpoint id=%s", endpoint.id)


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    start_background: bool = True,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_directories()
        configure_logging(settings)
        engine = build_engine(settings)
        try:
            await check_sqlite_version(engine)
            if settings.auto_migrate:
                await run_migrations_async(settings)
            session_factory = build_session_factory(engine)
            box = get_secret_box(settings)
            runtime = Runtime(
                settings=settings,
                engine=engine,
                session_factory=session_factory,
                secret_box=box,
                clock=clock or SystemClock(),
            )
            app.state.runtime = runtime
            await _seed_default_endpoint(runtime, settings)
            await runtime.start(run_background=start_background)
            logger.info("PromptOps Console started port=%s", settings.port)
            try:
                yield
            finally:
                await runtime.stop()
        finally:
            await dispose_engine(engine)

    app = FastAPI(
        title="PromptOps Console",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    install_error_handlers(app)

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def _static_cache_headers(request, call_next):  # noqa: ANN001, ANN202
        response = await call_next(request)
        if request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    app.include_router(meta_router)
    app.include_router(dashboard_router)
    app.include_router(endpoints_router)
    app.include_router(tasks_router)
    app.include_router(runs_router)

    @app.get("/api/v1", include_in_schema=False)
    async def api_root() -> JSONResponse:
        return JSONResponse({"name": "PromptOps Console", "version": __version__})

    install_spa(app, settings)

    return app


app = create_app()
