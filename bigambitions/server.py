"""Serveur web local : API JSON, événements temps réel (SSE) et interface (web/dist).

La surveillance des sauvegardes tourne dans un thread de l'Ingestor ; les tâches longues
(sync, ré-extraction du référentiel, contrôle biggerambitions) tournent dans des threads et
publient leur avancement sur /api/events.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db as database
from . import market, queries, segmentation
from .ingest import DEFAULT_DB, Ingestor
from .save import SAVE_ROOT

PROJECT_DIR = Path(__file__).resolve().parent.parent
WEB_DIST = PROJECT_DIR / "web" / "dist"


# Corps de requête (au niveau du module : FastAPI résout les annotations dans les globales du module).
class SyncRequest(BaseModel):
    force: bool = False


class CheckRequest(BaseModel):
    refresh: bool = False


class WatchRequest(BaseModel):
    enabled: bool


class DismissRequest(BaseModel):
    key: str
    dismissed: bool = True


class EventBus:
    """Diffuse les événements (émis depuis n'importe quel thread) à tous les clients SSE."""

    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.recent: list[dict[str, Any]] = []

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, kind: str, payload: dict[str, Any]) -> None:
        event = {"type": kind, **payload}
        self.recent = (self.recent + [event])[-50:]
        if self._loop is None:
            return
        for queue in list(self._subscribers):
            self._loop.call_soon_threadsafe(queue.put_nowait, event)

    async def stream(self):
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            self._subscribers.discard(queue)


class Jobs:
    """Une tâche longue de chaque type à la fois, exécutée dans un thread."""

    def __init__(self, bus: EventBus):
        self.bus = bus
        self.running: dict[str, str] = {}
        self._lock = threading.Lock()

    def start(self, name: str, target, *args) -> bool:
        with self._lock:
            if name in self.running:
                return False
            self.running[name] = datetime.now().isoformat(timespec="seconds")

        def run():
            self.bus.publish("job_started", {"job": name})
            try:
                result = target(*args)
                self.bus.publish("job_done", {"job": name, "result": result})
            except Exception as e:
                self.bus.publish("job_failed", {"job": name, "error": f"{type(e).__name__}: {e}"})
            finally:
                with self._lock:
                    self.running.pop(name, None)

        threading.Thread(target=run, name=f"job-{name}", daemon=True).start()
        return True


def create_app(db_path: Path = DEFAULT_DB, root: Path = SAVE_ROOT, watch: bool = True) -> FastAPI:
    bus = EventBus()
    jobs = Jobs(bus)
    ingestor = Ingestor(db_path, root, on_event=bus.publish)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bus.bind(asyncio.get_running_loop())
        if watch:
            ingestor.start_watch()
        yield
        ingestor.stop_watch()

    app = FastAPI(title="Big Ambitions Analytics", lifespan=lifespan)

    def read(fn, *args):
        if not Path(db_path).exists():
            raise HTTPException(503, "database not created yet")
        db = queries.connect_readonly(db_path)
        try:
            return fn(db, *args)
        finally:
            db.close()

    # --- état et pilotage ---------------------------------------------------

    @app.get("/api/status")
    def status():
        ref = ingestor.reference()
        return {
            **read(queries.status),
            "saveRoot": str(root),
            "watching": ingestor.watching,
            "busy": ingestor.busy,
            "pending": ingestor.pending,
            "lastImport": ingestor.last_import,
            "lastError": ingestor.last_error,
            "jobs": jobs.running,
            "reference": {
                "available": ref is not None,
                "stale": ref.is_stale() if ref else None,
                "version": ref.version if ref else None,
            },
            "recentEvents": bus.recent[-10:],
        }

    @app.post("/api/sync", status_code=202)
    def sync(request: SyncRequest):
        if not jobs.start("sync", ingestor.sync, request.force):
            raise HTTPException(409, "a sync is already running")
        return {"accepted": True}

    def refresh_gamedata() -> dict[str, Any]:
        """Ré-extrait le référentiel (nécessite UnityPy dans l'interpréteur courant) puis ré-importe."""
        result = subprocess.run([sys.executable, str(PROJECT_DIR / "extract_gamedata.py")], cwd=PROJECT_DIR,
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip().splitlines()[-1])
        return {"extract": result.stdout.strip().splitlines()[-1], "sync": ingestor.sync(force=True)}

    @app.post("/api/gamedata/refresh", status_code=202)
    def gamedata_refresh():
        if not jobs.start("gamedata", refresh_gamedata):
            raise HTTPException(409, "an extraction is already running")
        return {"accepted": True}

    def check_biggerambitions(refresh: bool) -> dict[str, Any]:
        from collections import Counter

        from .biggerambitions import BiggerAmbitions, compare
        rows = compare(BiggerAmbitions(), ingestor.reference(), refresh=refresh)
        db = database.connect(db_path)
        try:
            database.replace_table(db, "check_biggerambitions", rows)
        finally:
            db.close()
        return dict(Counter(r["status"] for r in rows))

    @app.post("/api/checks/biggerambitions", status_code=202)
    def checks(request: CheckRequest):
        if ingestor.reference() is None:
            raise HTTPException(409, "game reference data missing: refresh game data first")
        if not jobs.start("check", check_biggerambitions, request.refresh):
            raise HTTPException(409, "a check is already running")
        return {"accepted": True}

    @app.post("/api/watch")
    def set_watch(request: WatchRequest):
        if request.enabled:
            ingestor.start_watch()
        else:
            threading.Thread(target=ingestor.stop_watch, daemon=True).start()
        return {"watching": request.enabled}

    @app.get("/api/events")
    async def events():
        return StreamingResponse(bus.stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # --- données ------------------------------------------------------------

    def clamp(window: int) -> int:
        return max(1, min(window, 60))

    @app.get("/api/dashboard")
    def dashboard(window: int = 7):
        return read(queries.dashboard, clamp(window))

    @app.get("/api/pnl")
    def pnl_statement(granularity: str = "week", periods: int = 8, scope: str = "group", allocate: bool = True):
        try:
            return read(queries.pnl_statement, granularity, max(1, min(periods, 120)), scope, allocate)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/pnl/businesses")
    def pnl_businesses(firstDay: int | None = None, lastDay: int | None = None, window: int = 7):
        return read(queries.pnl_by_business, firstDay, lastDay, clamp(window))

    @app.get("/api/businesses")
    def businesses(window: int = 7):
        return read(queries.business_list, clamp(window))

    @app.get("/api/businesses/{address}")
    def business(address: str, window: int = 7):
        detail = read(queries.business_detail, address, clamp(window))
        if detail is None:
            raise HTTPException(404, f"unknown business {address}")
        return detail

    @app.get("/api/recommendations")
    def recommendation_list(window: int = 7):
        return read(queries.recommendation_list, clamp(window))

    @app.post("/api/recommendations/dismiss")
    def dismiss(request: DismissRequest):
        db = database.connect(db_path)
        try:
            database.set_dismissed(db, request.key, request.dismissed)
        finally:
            db.close()
        return {"key": request.key, "dismissed": request.dismissed}

    @app.get("/api/segmentation")
    def segments(window: int = 14):
        return read(segmentation.analyse, max(7, clamp(window)))

    @app.get("/api/recruitment")
    def recruitment():
        return read(queries.recruitment)

    @app.get("/api/customers")
    def customers(days: int = 60):
        return read(queries.customers, max(7, min(days, 365)))

    @app.get("/api/insights")
    def insight_list(window: int = 7):
        return read(queries.insight_list, clamp(window))

    @app.get("/api/prices")
    def prices(window: int = 7):
        return read(market.prices_overview, clamp(window))

    @app.get("/api/prices/history")
    def price_history(address: str, item: str):
        return read(market.price_history, address, item)

    @app.get("/api/market")
    def market_table(neighborhood: str | None = None):
        return read(market.market_table, neighborhood)

    @app.get("/api/suppliers")
    def suppliers(item: str | None = None):
        return read(market.suppliers, item)

    @app.get("/api/market/opportunities")
    def opportunities():
        return read(market.opportunities)

    @app.get("/api/market/activity")
    def activity(days: int = 30):
        return read(market.rival_activity, max(1, min(days, 120)))

    # --- interface ----------------------------------------------------------

    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = WEB_DIST / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")

    return app
