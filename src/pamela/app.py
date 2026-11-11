"""FastAPI application factory."""

from __future__ import annotations

import os
import signal
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import BackgroundTasks, FastAPI, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, db
from .api import router
from .config import ConfigError, ConfigStore, Settings, ensure_config_file

STATIC_DIR = resources.files("pamela") / "static"

# Set by ``pamela.web`` when it runs under the auto-reloader: the reloader only
# restarts its worker on file changes, so stopping must signal the reloader itself.
SUPERVISOR_PID_ENV = "PAMELA_SUPERVISOR_PID"


def request_exit() -> None:
    """Ask uvicorn to stop, the same way Ctrl+C does: open requests finish first,
    then the lifespan shutdown runs."""
    pid = int(os.environ.get(SUPERVISOR_PID_ENV) or os.getpid())
    os.kill(pid, signal.SIGINT)


def prepare(settings: Settings, config_store: ConfigStore) -> None:
    """Create the config file, migrate the database and run the one-time imports."""
    ensure_config_file(settings.config_path)
    db.migrate(settings.db_path)
    try:
        legacy = config_store.get()
    except ConfigError:
        return  # retried on the next start; the banner shows the problem meanwhile
    with db.session(settings.db_path) as conn:
        db.import_config_activity_types(conn, legacy.activity_types)
        db.import_config_targets(conn, legacy.targets.model_dump())


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    config_store = ConfigStore(settings.config_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        prepare(settings, config_store)
        yield
        # Every change is already committed; this only folds the WAL back into the
        # database file, so local/ holds one self-contained file after closing.
        db.checkpoint(settings.db_path)

    app = FastAPI(title="Pamela", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.config_store = config_store
    app.state.request_exit = request_exit

    @app.exception_handler(ConfigError)
    async def _config_error(request: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=500)

    @app.middleware("http")
    async def _revalidate_static(request: Request, call_next):
        # Without an explicit policy Firefox caches heuristically and can serve a
        # stale app.js after an update; "no-cache" still allows cheap 304s.
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.include_router(router)

    @app.post("/api/shutdown", status_code=status.HTTP_202_ACCEPTED, tags=["app"])
    def shutdown(background: BackgroundTasks) -> dict:
        """Save & close: stop the server once this response has been sent."""
        background.add_task(app.state.request_exit)
        return {"detail": "Pamela is closing"}

    static_dir = str(STATIC_DIR)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        # no-cache: always revalidate, so a new frontend shows up on reload.
        return FileResponse(f"{static_dir}/index.html", headers={"Cache-Control": "no-cache"})

    return app
