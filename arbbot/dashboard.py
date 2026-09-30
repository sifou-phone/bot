"""Local web dashboard (FastAPI + Jinja2) at http://127.0.0.1:8000.

No login, so it must stay local. Protections:
  * binds to 127.0.0.1 by default;
  * rejects requests whose Host header is not an allowed local host (DNS rebinding);
  * control endpoints need a custom header, which a foreign web page cannot send
    without a CORS preflight that this app never grants (CSRF);
  * WebSocket connections from other origins are refused;
  * API secrets never leave the server: only "configured: yes/no" is exposed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .bot import ArbBot, ModeError

log = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))
ACTION_HEADER = "x-arbbot-action"


class ModeRequest(BaseModel):
    mode: str
    confirm: bool = False
    phrase: str = ""


class KillRequest(BaseModel):
    reason: str = ""


def clean(value: Any) -> Any:
    """JSON-safe copy for the browser: NaN / infinity become null."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _allowed_hosts(bot: ArbBot) -> set[str]:
    hosts = {"127.0.0.1", "localhost", "::1", "[::1]"}
    extra = os.environ.get("DASHBOARD_ALLOWED_HOSTS", "")
    hosts.update(h.strip().lower() for h in extra.split(",") if h.strip())
    if bot.settings.host not in ("0.0.0.0", "::"):
        hosts.add(bot.settings.host.lower())
    return hosts


def _hostname(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):  # [::1]:8000
        return value.split("]")[0] + "]"
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def create_app(bot: ArbBot, auto_start: bool = True) -> FastAPI:
    hosts = _allowed_hosts(bot)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if auto_start:
            await bot.start_monitoring()
        yield
        await bot.shutdown()

    app = FastAPI(title="ArbBot", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def origin_ok(origin: str) -> bool:
        return _hostname(urlparse(origin).netloc) in hosts

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if _hostname(request.headers.get("host", "")) not in hosts:
            return JSONResponse({"detail": "host not allowed"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get(ACTION_HEADER) != "1":
                return JSONResponse({"detail": "missing action header"}, status_code=403)
            origin = request.headers.get("origin")
            if origin is not None and not origin_ok(origin):
                return JSONResponse({"detail": "origin not allowed"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return TEMPLATES.TemplateResponse(request, "index.html", {"settings": bot.settings.public_dict()})

    @app.get("/api/state")
    async def state() -> JSONResponse:
        return JSONResponse(clean(bot.snapshot()))

    @app.post("/api/monitor/start")
    async def monitor_start() -> dict[str, Any]:
        await bot.start_monitoring()
        return {"ok": True, "monitoring": bot.monitoring}

    @app.post("/api/monitor/stop")
    async def monitor_stop() -> dict[str, Any]:
        await bot.stop_monitoring()
        return {"ok": True, "monitoring": bot.monitoring}

    @app.post("/api/mode")
    async def set_mode(body: ModeRequest) -> dict[str, Any]:
        try:
            await bot.set_mode(body.mode, body.confirm, body.phrase)
        except ModeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "mode": bot.mode}

    @app.post("/api/kill")
    async def kill(body: KillRequest | None = None) -> dict[str, Any]:
        bot.kill((body.reason if body and body.reason else "") or "manual kill switch from dashboard")
        return {"ok": True, "killed": True}

    @app.post("/api/kill/reset")
    async def kill_reset() -> dict[str, Any]:
        bot.reset_kill()
        return {"ok": True, "killed": False}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if _hostname(websocket.headers.get("host", "")) not in hosts or (origin and not origin_ok(origin)):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                await websocket.send_text(json.dumps(clean(bot.snapshot()), default=str))
                await asyncio.sleep(1.0)
        except (WebSocketDisconnect, RuntimeError):
            return

    return app
