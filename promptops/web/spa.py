"""Serve the built React SPA from FastAPI with a client-route fallback."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from promptops.config import Settings


def install_spa(app: FastAPI, settings: Settings) -> None:
    dist = settings.frontend_dist.resolve()
    index = dist / "index.html"
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):  # noqa: ANN202
        if full_path == "healthz" or full_path.startswith(("api/", "healthz/")):
            raise HTTPException(status_code=404, detail="Not Found")
        if not index.exists():
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "frontend_not_built",
                        "message": "Frontend is not built yet; run pnpm install && pnpm build in the frontend/ directory",
                    }
                },
            )
        if full_path:
            candidate = (dist / full_path).resolve()
            try:
                candidate.relative_to(dist)
            except ValueError:
                raise HTTPException(status_code=404, detail="Not Found")
            if candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
