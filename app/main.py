"""Local journal server: the expert posts here, the dashboard reads from here."""
import csv
import io
import os
import sys
import time
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, analytics, db, feeds, markets
from .ingest import SyncIn, apply_sync

STATIC = Path(__file__).parent / "static"
EA_ONLINE_SECONDS = 30


class NoteIn(BaseModel):
    setup: str = Field("", max_length=120)
    emotion: str = Field("", max_length=60)
    rating: Optional[int] = Field(None, ge=1, le=5)
    note: str = Field("", max_length=5000)


class ThemeIn(BaseModel):
    preset: str = Field("firoozeh", pattern="^[a-z]+$")
    accent: str = Field("", pattern="^(#[0-9a-fA-F]{6})?$")
    font_scale: int = Field(100, ge=85, le=125)
    density: str = Field("normal", pattern="^(compact|normal|comfortable)$")


class RulesIn(BaseModel):
    daily_loss_limit: float = Field(0, ge=0)
    max_trades_per_day: int = Field(6, ge=0, le=500)
    max_consecutive_losses: int = Field(3, ge=0, le=100)
    cooldown_minutes: int = Field(15, ge=0, le=1440)
    require_sl: bool = True
    news_alert_minutes: int = Field(30, ge=0, le=240)


class AiIn(BaseModel):
    format: str = Field("openai", pattern="^(openai|anthropic)$")
    base_url: str = Field("", max_length=300, pattern="^(https?://.*)?$")
    model: str = Field("", max_length=120)
    api_key: Optional[str] = Field(None, max_length=400)  # None keeps the saved key
    auto_every: int = Field(0, ge=0, le=1000)


class SettingsIn(BaseModel):
    timezone: Optional[str] = None
    theme: Optional[ThemeIn] = None
    rules: Optional[RulesIn] = None
    ai: Optional[AiIn] = None
    markets: Optional[list[str]] = None
    feeds: Optional[list[str]] = Field(None, max_length=30)
    proxy: Optional[str] = Field(None, max_length=200, pattern="^(https?://.*)?$")


def create_app(db_path=None, demo=False, background=False) -> FastAPI:
    path = db_path or os.environ.get("JOURNAL_DB") or Path.cwd() / "data" / "journal.db"
    conn = db.connect(path)
    token = db.get_token(conn)

    @asynccontextmanager
    async def lifespan(_app):
        worker = None
        if background and not demo:
            worker = feeds.Worker(lambda: db.connect(path), auto_coach)
            worker.start()
            _app.state.worker = worker
        yield
        if worker:
            worker.stop_event.set()
            worker.wake.set()

    app = FastAPI(title="Trade Journal", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.worker = None
    # Blocks DNS rebinding: a web page must not be able to read this local server.
    app.add_middleware(TrustedHostMiddleware,
                       allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    def zone() -> ZoneInfo:
        return ZoneInfo(db.get_settings(conn)["timezone"])

    def require_token(x_journal_token: str = Header("")):
        if x_journal_token != token:
            raise HTTPException(401, "invalid token")

    def require_json(request: Request):
        # Forces a CORS preflight, which this server never approves.
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise HTTPException(415, "application/json required")

    def load(account: str = "", symbol: str = "", start: Optional[int] = None,
             end: Optional[int] = None) -> list:
        settings = db.get_settings(conn)
        where, args = ("WHERE account_id=?", [account]) if account else ("", [])
        deals = [dict(r) for r in conn.execute(f"SELECT * FROM deals {where}", args)]
        events = [dict(r) for r in conn.execute(f"SELECT * FROM events {where}", args)]
        trades = analytics.build_trades(deals, events, settings["rules"],
                                        ZoneInfo(settings["timezone"]))
        calendar = markets.load_events(conn, 0, 2**40, ("high",))
        markets.flag_news_trades(trades, calendar)
        keep = lambda t: ((not symbol or t["symbol"] == symbol)
                          and (start is None or t["open_time"] >= start)
                          and (end is None or t["open_time"] < end))
        return [t for t in trades if keep(t)]

    def currency(account: str) -> str:
        rows = conn.execute("SELECT DISTINCT currency FROM accounts"
                            + (" WHERE id=?" if account else ""),
                            (account,) if account else ()).fetchall()
        return rows[0]["currency"] if len(rows) == 1 else ""

    @app.post("/api/ea/sync", response_class=PlainTextResponse,
              dependencies=[Depends(require_token)])
    def ea_sync(msg: SyncIn):
        now = int(time.time())
        account_id, cursor = apply_sync(conn, msg, now)
        settings = db.get_settings(conn)
        tz = ZoneInfo(settings["timezone"])
        deals = [dict(r) for r in conn.execute("SELECT * FROM deals WHERE account_id=?", (account_id,))]
        events = [dict(r) for r in conn.execute("SELECT * FROM events WHERE account_id=?", (account_id,))]
        trades = analytics.build_trades(deals, events, settings["rules"], tz)
        alerts = markets.news_alerts(conn, settings["rules"], settings["markets"], now)
        positions = conn.execute("SELECT * FROM open_positions WHERE account_id=?", (account_id,)).fetchall()
        lines = ["OK", f"CURSOR|{cursor}"]
        for alert_id, level, text in alerts + analytics.build_alerts(trades, positions, settings["rules"], tz, now):
            lines.append(f"ALERT|{alert_id}|{level}|{text}")
        return "\n".join(lines) + "\n"

    @app.get("/api/status")
    def status():
        now = int(time.time())
        rows = [dict(r) for r in conn.execute("SELECT * FROM accounts ORDER BY last_seen DESC")]
        for row in rows:
            row["online"] = (row["last_seen"] or 0) >= now - EA_ONLINE_SECONDS
            row["trade_count"] = conn.execute(
                "SELECT COUNT(DISTINCT position_id) c FROM deals WHERE account_id=? AND type IN('buy','sell')",
                (row["id"],)).fetchone()["c"]
        return {"accounts": rows, "demo": demo, "now": now}

    @app.get("/api/overview")
    def overview(account: str = "", symbol: str = "", start: Optional[int] = None,
                 end: Optional[int] = None):
        trades = load(account, symbol, start, end)
        where, args = ("WHERE account_id=?", (account,)) if account else ("", ())
        positions = [dict(r) for r in conn.execute(f"SELECT * FROM open_positions {where}", args)]
        data = analytics.build_overview(trades, zone(), currency(account))
        data.update(positions=positions, currency=currency(account),
                    symbols=sorted({t["symbol"] for t in load(account)}))
        return data

    @app.get("/api/trades")
    def trades(account: str = "", symbol: str = "", start: Optional[int] = None,
               end: Optional[int] = None, flag: str = "", limit: int = Query(300, le=5000)):
        rows = load(account, symbol, start, end)
        if flag:
            rows = [t for t in rows if flag in t["flags"]]
        return {"trades": rows[:limit], "total": len(rows), "labels": analytics.FLAG_LABELS}

    @app.get("/api/trades/{account_id}/{position_id}")
    def trade_detail(account_id: str, position_id: str):
        trade = next((t for t in load(account_id) if t["position_id"] == position_id), None)
        if trade is None:
            raise HTTPException(404, "trade not found")
        key = (account_id, position_id)
        deals = [dict(r) for r in conn.execute(
            "SELECT * FROM deals WHERE account_id=? AND position_id=?", key)]
        events = [dict(r) for r in conn.execute(
            "SELECT * FROM events WHERE account_id=? AND position_id=?", key)]
        note = conn.execute("SELECT * FROM notes WHERE account_id=? AND position_id=?", key).fetchone()
        tz = zone()
        return {
            "trade": trade, "story": analytics.narrate(trade, tz, currency(account_id)),
            "timeline": analytics.timeline(deals, events, trade, tz),
            "note": dict(note) if note else {"setup": "", "emotion": "", "rating": None, "note": ""},
            "labels": analytics.FLAG_LABELS, "currency": currency(account_id),
            "events": markets.events_during(trade, markets.load_events(conn, 0, 2**40)),
        }

    @app.put("/api/notes/{account_id}/{position_id}", dependencies=[Depends(require_json)])
    def save_note(account_id: str, position_id: str, note: NoteIn):
        with conn:
            conn.execute(
                """INSERT INTO notes(account_id,position_id,setup,emotion,rating,note,updated_at)
                   VALUES(?,?,?,?,?,?,?) ON CONFLICT(account_id,position_id) DO UPDATE SET
                   setup=excluded.setup,emotion=excluded.emotion,rating=excluded.rating,
                   note=excluded.note,updated_at=excluded.updated_at""",
                (account_id, position_id, note.setup, note.emotion, note.rating, note.note,
                 int(time.time())))
        return {"saved": True}

    @app.get("/api/settings")
    def get_settings():
        data = db.get_settings(conn)
        data.pop("token", None)
        has_key = bool(data["ai"].pop("api_key", ""))
        data["ai"]["has_key"] = has_key
        catalog = {k: v["name"] for k, v in markets.MARKETS.items()}
        return {**data, "token": token, "port": os.environ.get("JOURNAL_PORT", "8765"), "catalog": catalog,
                "platform": sys.platform}

    @app.put("/api/settings", dependencies=[Depends(require_json)])
    def put_settings(body: SettingsIn):
        if body.timezone:
            try:
                ZoneInfo(body.timezone)
            except Exception:
                raise HTTPException(422, "unknown timezone")
            db.put_setting(conn, "timezone", body.timezone)
        if body.theme:
            db.put_setting(conn, "theme", body.theme.model_dump())
        if body.rules:
            db.put_setting(conn, "rules", body.rules.model_dump())
        if body.ai:
            saved = body.ai.model_dump()
            if saved["api_key"] is None:
                saved["api_key"] = db.get_settings(conn)["ai"]["api_key"]
            db.put_setting(conn, "ai", saved)
        if body.markets is not None:
            db.put_setting(conn, "markets", [m for m in body.markets if m in markets.MARKETS])
        if body.feeds is not None:
            if any(not f.startswith(("http://", "https://")) for f in body.feeds):
                raise HTTPException(422, "feed address must start with http or https")
            db.put_setting(conn, "feeds", body.feeds)
        if body.proxy is not None:
            db.put_setting(conn, "proxy", body.proxy)
        return {"saved": True}

    def coach_inputs():
        trades_ = load()
        notes = {(r["account_id"], r["position_id"]): dict(r) for r in conn.execute("SELECT * FROM notes")}
        overview_ = analytics.build_overview(trades_, zone(), currency(""))
        overview_["currency"] = currency("")
        return overview_, trades_, notes

    def auto_coach(_worker_conn):
        every = db.get_settings(conn)["ai"]["auto_every"]
        if not every or not ai.configured(conn):
            return
        overview_, trades_, notes = coach_inputs()
        last = ai.latest(conn, "coach")
        done = last[0]["closed_trades"] if last else 0
        if overview_["summary"]["count"] - done >= every:
            ai.run_coach(conn, overview_, trades_, notes)

    @app.get("/api/news/{market}")
    def news(market: str):
        if market not in markets.MARKETS:
            raise HTTPException(404, "unknown market")
        brief = markets.rule_brief(conn, market)
        reports = ai.latest(conn, "brief", market)
        return {**brief, "ai": reports[0] if reports else None, "ai_ready": ai.configured(conn),
                "sources": [dict(r) for r in conn.execute("SELECT * FROM source_status ORDER BY name")]}

    @app.post("/api/news/refresh", dependencies=[Depends(require_json)])
    def news_refresh():
        if app.state.worker:
            app.state.worker.wake.set()
        return {"started": bool(app.state.worker)}

    @app.post("/api/news/{market}/brief", dependencies=[Depends(require_json)])
    def news_brief(market: str):
        if market not in markets.MARKETS:
            raise HTTPException(404, "unknown market")
        if not ai.configured(conn):
            raise HTTPException(409, "سرویس هوش مصنوعی هنوز تنظیم نشده است.")
        try:
            return ai.run_brief(conn, markets.rule_brief(conn, market))
        except ai.AiError as error:
            raise HTTPException(502, str(error))

    @app.get("/api/coach")
    def coach_list():
        return {"reports": ai.latest(conn, "coach", limit=20), "ready": ai.configured(conn)}

    @app.post("/api/coach", dependencies=[Depends(require_json)])
    def coach_run():
        if not ai.configured(conn):
            raise HTTPException(409, "سرویس هوش مصنوعی هنوز تنظیم نشده است.")
        try:
            return ai.run_coach(conn, *coach_inputs())
        except ai.AiError as error:
            raise HTTPException(502, str(error))

    @app.get("/api/export.csv")
    def export(account: str = "", symbol: str = "", start: Optional[int] = None,
               end: Optional[int] = None):
        columns = ["position_id", "symbol", "side", "volume", "entry_price", "exit_price",
                   "open_time", "close_time", "sl_initial", "tp_initial", "gross", "costs", "net",
                   "r_multiple", "capture", "flags"]
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(columns)
        for trade in load(account, symbol, start, end):
            writer.writerow([" ".join(trade[c]) if c == "flags" else trade[c] for c in columns])
        return Response("﻿" + out.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": "attachment; filename=journal.csv"})

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
