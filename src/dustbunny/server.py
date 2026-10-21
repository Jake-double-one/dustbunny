"""Web server: JSON API, web UI and the periodic scan."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.types import Scope

from dustbunny import __version__
from dustbunny.config import Settings
from dustbunny.i18n import LOCALES_DIR, available_languages, load_locale
from dustbunny.mcp_server import McpServer, origin_allowed, token_matches
from dustbunny.schedule import Cron
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


class RevalidatedFiles(StaticFiles):
    """Static files the browser has to check (ETag) before it reuses them."""

    def file_response(
        self, full_path: str, stat_result: os.stat_result, scope: Scope, status_code: int = 200
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = "no-cache"
        return response


class IgnoreRequest(BaseModel):
    path: str
    ignored: bool = True


# After an incomplete scan (e.g. the socket proxy wasn't up yet) try again soon - but
# only a few times: a setup that stays broken must not walk all folders every 2 minutes.
RETRY_INCOMPLETE = timedelta(minutes=2)
MAX_RETRIES = 2


class Scheduler:
    """Runs a scan at start and then every ``interval`` (0 = only on request) or,
    with ``cron``, at its times in ``tz`` - then at start only if there is no report
    yet. ``trigger`` must be called from the event loop (async endpoints)."""

    def __init__(
        self,
        service: ScanService,
        interval: timedelta,
        cron: Cron | None = None,
        tz: tzinfo = UTC,
    ):
        self.service = service
        self.interval = interval
        self.cron = cron
        self.tz = tz
        self.next_scan_at: datetime | None = None
        self.pending = False  # a scan was requested and hasn't finished yet
        self.retries = 0
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self.cron is not None:
            log.info("scans at %r (%s)", self.cron.expression, self.tz)
        elif self.interval.total_seconds() > 0:
            log.info("scans at start and every %s", self.interval)
        else:
            log.info("scans at start and on request only")
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    def trigger(self) -> None:
        self.pending = True
        self._wake.set()

    def next_after(self, now: datetime) -> datetime | None:
        """When the schedule wants the next scan (None: only on request)."""
        if self.cron is not None:
            return self.cron.next_after(now.astimezone(self.tz))
        if self.interval.total_seconds() > 0:
            return now + self.interval
        return None

    async def _run(self) -> None:
        scan = self.cron is None or self.service.report is None
        while True:
            self._wake.clear()
            if scan and self.service.ready:
                with suppress(Exception):  # logged by the service, the loop goes on
                    await asyncio.to_thread(self.service.scan)
            scan = True
            self.pending = self._wake.is_set()
            now = datetime.now(UTC)
            next_at = self.next_after(now)
            report = self.service.report
            failed = self.service.last_error is not None or (report and not report.complete)
            if not failed:
                self.retries = 0
            elif next_at is not None and self.retries < MAX_RETRIES:
                self.retries += 1
                next_at = min(next_at, now + RETRY_INCOMPLETE)
            self.next_scan_at = next_at if self.service.ready else None
            timeout = None
            if self.next_scan_at is not None:
                timeout = max((self.next_scan_at - datetime.now(UTC)).total_seconds(), 0)
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=timeout)


def create_app(settings: Settings, service: ScanService | None = None) -> FastAPI:
    if service is None:
        service = ScanService(settings, State(settings.data_dir / "dustbunny.sqlite3"))
    if service.config_error:
        log.error("configuration error: %s", service.config_error)
    skins = SkinCache(custom_dir=settings.custom_skins_dir)
    skins.get()  # read once at start: problems show up in the log right away
    scheduler = Scheduler(
        service, settings.scan_interval, cron=settings.cron, tz=settings.time_zone
    )
    # CSS and JS under a path with the version in it: after an update, no browser
    # combines the new page with files it cached from the old version
    assets = "static/" + re.sub(r"[^A-Za-z0-9.-]", "-", __version__)
    template = (
        (WEB_DIR / "index.html")
        .read_text(encoding="utf-8")
        .replace('href="static/', f'href="{assets}/')
        .replace('src="static/', f'src="{assets}/')
    )

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
        path = request.url.path
        # MCP has its own key (MCP_TOKEN): agents can't do Basic Auth
        is_mcp = settings.mcp_enabled and (path == "/mcp" or path.startswith("/mcp/"))
        protected = settings.auth_enabled and path != "/healthz" and not is_mcp
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

    if settings.mcp_enabled:
        _add_mcp_routes(app, settings, service, scheduler)

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
            "scan_schedule": settings.scan_schedule,
            "time_zone": str(settings.time_zone),
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

    static = RevalidatedFiles(directory=WEB_DIR / "static")
    app.mount(f"/{assets}", static)
    app.mount("/static", static, name="static")
    assert LOCALES_DIR.is_dir()
    return app


def _add_mcp_routes(
    app: FastAPI, settings: Settings, service: ScanService, scheduler: Scheduler
) -> None:
    assert settings.mcp_token is not None
    token = settings.mcp_token.get_secret_value()

    def trigger() -> bool:  # runs on the event loop (async endpoint)
        started = not (service.scanning or scheduler.pending)
        scheduler.trigger()
        return started

    server = McpServer(service, trigger, allow_changes=settings.mcp_allow_changes)

    async def answer(request: Request, authorized: bool) -> Response:
        if not authorized:
            return JSONResponse({"detail": "not found"}, status_code=404)
        if not origin_allowed(request.headers.get("origin"), request.headers.get("host")):
            return JSONResponse({"detail": "origin not allowed"}, status_code=403)
        if request.method != "POST":
            # stateless: no event stream to open, no session to end
            return Response(status_code=405, headers={"Allow": "POST"})
        message = server.handle(await request.body())
        if message is None:
            return Response(status_code=202)
        return JSONResponse(message, headers={"Cache-Control": "no-store"})

    methods = ["GET", "POST", "DELETE"]

    # Agents with a connector UI (Claude, ChatGPT, Grok) only take an address: the key is in it.
    @app.api_route("/mcp/{key}", methods=methods, include_in_schema=False)
    async def mcp_with_key(key: str, request: Request) -> Response:
        return await answer(request, token_matches(key, token))

    # Clients that can send a header (Claude Code, scripts): Authorization: Bearer <key>
    @app.api_route("/mcp", methods=methods, include_in_schema=False)
    async def mcp_with_header(request: Request) -> Response:
        scheme, _, given = request.headers.get("authorization", "").partition(" ")
        return await answer(request, scheme.lower() == "bearer" and token_matches(given, token))


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
    commit = os.environ.get("DUSTBUNNY_COMMIT", "")[:7]
    log.info("Dustbunny %s%s", __version__, f" (commit {commit})" if commit else "")
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        access_log=settings.log_level == "debug",
        proxy_headers=False,
    )
