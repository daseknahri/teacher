from pathlib import Path
import logging
import re
import time
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import ALERT_ON_5XX, ALERT_ON_EXCEPTION, ALERT_SLOW_MS, EXPORTS_DIR, LOGS_DIR, STORAGE_DIR, UPLOADS_DIR
from .database import Base, engine, ensure_schema_compatibility
from .routers import audit, auth, classes, exams, ops, reports, sessions, workflow
from .services.alerts import send_request_alert
from .services.logging_setup import configure_logging
from .services.rate_limit import reset_rate_limits


def create_app() -> FastAPI:
    configure_logging()
    logger = logging.getLogger("teacher_progress")
    app = FastAPI(title="Teacher Progress API", version="0.1.0")
    app.state.started_at = datetime.now(UTC).replace(tzinfo=None)

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    reset_rate_limits()
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility()
    logger.info("startup.complete", extra={"storage_dir": str(STORAGE_DIR), "logs_dir": str(LOGS_DIR)})

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.middleware("http")
    async def request_logging_middleware(request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "request.error",
                extra={"method": request.method, "path": request.url.path},
            )
            if ALERT_ON_EXCEPTION and request.url.path != "/health":
                await send_request_alert(
                    kind="exception",
                    method=request.method,
                    path=request.url.path,
                    status_code=500,
                    duration_ms=duration_ms,
                    error=str(exc),
                )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "request.complete",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        if request.url.path != "/health":
            if ALERT_ON_5XX and response.status_code >= 500:
                await send_request_alert(
                    kind="http_5xx",
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                )
            elif ALERT_SLOW_MS > 0 and duration_ms >= float(ALERT_SLOW_MS):
                await send_request_alert(
                    kind="slow_request",
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                )
        return response

    app.include_router(auth.router)
    app.include_router(classes.router)
    app.include_router(sessions.router)
    app.include_router(exams.router)
    app.include_router(reports.router)
    app.include_router(audit.router)
    app.include_router(ops.router)
    app.include_router(workflow.router)

    def _dist_bundle_is_valid(dist_dir: Path) -> bool:
        index_path = dist_dir / "index.html"
        assets_dir = dist_dir / "assets"
        if not index_path.exists() or not assets_dir.exists():
            return False
        try:
            html = index_path.read_text(encoding="utf-8")
        except OSError:
            return False
        asset_refs = re.findall(r"""(?:src|href)=["'](/assets/[^"']+)["']""", html)
        if not asset_refs:
            return False
        for ref in asset_refs:
            rel = ref.removeprefix("/assets/")
            if not (assets_dir / rel).exists():
                return False
        return True

    base = Path(__file__).resolve()
    frontend_candidates = [
        base.parents[2] / "frontend",  # local repo layout
        base.parents[1] / "frontend",  # container layout when frontend copied under /app/frontend
    ]
    frontend_root = next((path for path in frontend_candidates if path.exists()), None)
    frontend_dir = None
    if frontend_root is not None:
        dist_dir = frontend_root / "dist"
        frontend_dir = dist_dir if _dist_bundle_is_valid(dist_dir) else frontend_root

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        if frontend_root is None and frontend_dir is None:
            return Response(status_code=204)
        ico_path = (frontend_root / "favicon.ico") if frontend_root is not None else (frontend_dir / "favicon.ico")
        if ico_path.exists() and ico_path.is_file():
            return FileResponse(path=str(ico_path))
        svg_path = (frontend_root / "favicon.svg") if frontend_root is not None else (frontend_dir / "favicon.svg")
        if svg_path.exists() and svg_path.is_file():
            return FileResponse(path=str(svg_path), media_type="image/svg+xml")
        return Response(status_code=204)

    if frontend_dir is not None:
        # Serve frontend shell under /app.
        app.mount("/app", StaticFiles(directory=str(frontend_dir), html=True), name="app-ui")
        # Dist index files may reference absolute /assets/* paths; expose them at root.
        assets_dir = frontend_dir / "assets"
        if assets_dir.exists() and assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="app-assets")
    return app


app = create_app()
