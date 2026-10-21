"""Web server: JSON API, web UI and the periodic scan."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dustbunny import __version__
from dustbunny.config import Settings
from dustbunny.i18n import LOCALES_DIR, available_languages, load_locale
from dustbunny.service import ScanService
from dustbunny.skins import SkinCache
from dustbunny.state import State

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
}


class IgnoreRequest(BaseModel):
    path: str
    ignored: bool = True


# After an incomplete scan (e.g. the socket proxy wasn't up yet) try again soon.
RETRY_INCOMPLETE = timedelta(minutes=2)


class Scheduler:
    """Runs a scan at start and then every ``interval`` (0 = only on request).
    ``trigger`` must be called from the event loop (async endpoints)."""

    def __init__(self, service: ScanService, interval: timedelta):
        self.service = service
        self.interval = interval
        self.next_scan_at: datetime | None = None
        self.pending = False  # a scan was requested and hasn't finished yet
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    def trigger(self) -> None:
        self.pending = True
        self._wake.set()

    async def _run(self) -> None:
        while True:
            self._wake.clear()
            if self.service.ready:
                with suppress(Exception):  # logged by the service, the loop goes on
                    await asyncio.to_thread(self.service.scan)
            self.pending = self._wake.is_set()
            interval = self.interval
            report = self.service.report
            failed = self.service.last_error is not None or (report and not report.complete)
            if interval.total_seconds() > 0 and failed:
                interval = min(interval, RETRY_INCOMPLETE)
            seconds = interval.total_seconds()
            self.next_scan_at = (
                datetime.now(UTC) + interval if seconds > 0 and self.service.ready else None
            )
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=seconds if seconds > 0 else None)


def create_app(settings: Settings, service: ScanService | None = None) -> FastAPI:
    if service is None:
        service = ScanService(settings, State(settings.data_dir / "dustbunny.sqlite3"))
    if service.config_error:
        log.error("configuration error: %s", service.config_error)
    skins = SkinCache(custom_dir=settings.custom_skins_dir)
    skins.get()  # read once at start: problems show up in the log right away
    scheduler = Scheduler(service, settings.scan_interval)
    template = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        scheduler.start()
        yield
        await scheduler.stop()

    app = FastAPI(
        title="Dustbunny", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.state.service = service
    app.state.scheduler = scheduler

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        protected = settings.auth_enabled and request.url.path != "/healthz"
        if protected and not _authorized(request, settings):
            response = Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Dustbunny", charset="UTF-8"'},
            )
        elif request.method == "POST" and not request.headers.get("content-type", "").startswith(
            "application/json"
        ):
            # Browsers can't send JSON to another site without asking first (CORS),
            # so this keeps other web pages from triggering scans with your login.
            response = JSONResponse({"detail": "expected application/json"}, status_code=415)
        else:
            response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/status")
    def status() -> dict[str, object]:
        return {
            "version": __version__,
            "scanning": service.scanning or scheduler.pending,
            "last_scan_at": service.last_scan_at,
            "next_scan_at": scheduler.next_scan_at,
            "scan_interval_seconds": int(settings.scan_interval.total_seconds()),
            "roots": service.roots,
            "config_error": service.config_error,
            "last_error": service.last_error,
        }

    @app.get("/api/report")
    def report() -> Response:
        if service.report is None:
            raise HTTPException(status_code=404, detail="no report yet")
        return Response(service.report.model_dump_json(), media_type="application/json")

    @app.post("/api/scan", status_code=202)
    async def scan() -> dict[str, bool]:
        if not service.ready:
            raise HTTPException(status_code=409, detail=service.config_error)
        started = not service.scanning
        scheduler.trigger()
        return {"started": started}

    @app.post("/api/ignore")
    def ignore(body: IgnoreRequest) -> Response:
        try:
            result = service.set_ignored(body.path, body.ignored)
        except KeyError:
            raise HTTPException(status_code=404, detail="unknown folder") from None
        assert result is not None
        return Response(result.model_dump_json(), media_type="application/json")

    @app.get("/api/skins")
    def skin_list() -> JSONResponse:
        current = skins.get()
        return JSONResponse({"css": current.css, **current.as_list()})

    @app.get("/api/languages")
    def languages() -> list[dict[str, str]]:
        return available_languages()

    @app.get("/locales/{code}.json")
    def locale(code: str) -> JSONResponse:
        try:
            return JSONResponse(load_locale(code), headers={"Cache-Control": "no-cache"})
        except KeyError:
            raise HTTPException(status_code=404) from None

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        boot = json.dumps({"version": __version__, "languages": available_languages()}).replace(
            "<", "\\u003c"
        )
        page = template.replace("<!--skins-->", skins.get().html()).replace(
            "<!--boot-->", f'<script type="application/json" id="boot">{boot}</script>'
        )
        return HTMLResponse(page, headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    assert LOCALES_DIR.is_dir()
    return app


def _authorized(request: Request, settings: Settings) -> bool:
    header = request.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        user, _, password = base64.b64decode(encoded).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    assert settings.auth_user is not None and settings.auth_password is not None
    user_ok = secrets.compare_digest(user.encode(), settings.auth_user.encode())
    password_ok = secrets.compare_digest(
        password.encode(), settings.auth_password.get_secret_value().encode()
    )
    return user_ok and password_ok


def serve(settings: Settings) -> None:
    import os

    import uvicorn

    # Files in DATA_DIR stay writable for the group, so the same volume works whether the
    # container runs as uid 1000 or as root without capabilities (see Dockerfile).
    os.umask(0o002)

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        access_log=settings.log_level == "debug",
        proxy_headers=False,
    )
