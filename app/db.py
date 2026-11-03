"""SQLite storage. Trades are never stored: they are rebuilt from raw deals."""
import json
import secrets
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts(
  id TEXT PRIMARY KEY, login TEXT NOT NULL, server TEXT NOT NULL, broker TEXT, name TEXT,
  currency TEXT, leverage INTEGER, platform TEXT, gmt_offset INTEGER NOT NULL DEFAULT 0,
  balance REAL, equity REAL, last_seen INTEGER);
CREATE TABLE IF NOT EXISTS deals(
  account_id TEXT NOT NULL REFERENCES accounts(id), deal_id TEXT NOT NULL,
  position_id TEXT NOT NULL, symbol TEXT NOT NULL DEFAULT '', type TEXT NOT NULL,
  entry TEXT NOT NULL, volume REAL NOT NULL DEFAULT 0, price REAL NOT NULL DEFAULT 0,
  sl REAL NOT NULL DEFAULT 0, tp REAL NOT NULL DEFAULT 0, profit REAL NOT NULL DEFAULT 0,
  commission REAL NOT NULL DEFAULT 0, swap REAL NOT NULL DEFAULT 0, fee REAL NOT NULL DEFAULT 0,
  time_raw INTEGER NOT NULL, time_utc INTEGER NOT NULL, magic INTEGER NOT NULL DEFAULT 0,
  comment TEXT NOT NULL DEFAULT '', mfe_price REAL, mae_price REAL,
  PRIMARY KEY(account_id, deal_id));
CREATE INDEX IF NOT EXISTS deals_position ON deals(account_id, position_id);
CREATE INDEX IF NOT EXISTS deals_time ON deals(account_id, time_utc);
CREATE TABLE IF NOT EXISTS open_positions(
  account_id TEXT NOT NULL REFERENCES accounts(id), position_id TEXT NOT NULL,
  symbol TEXT NOT NULL, side TEXT NOT NULL, volume REAL NOT NULL, open_price REAL NOT NULL,
  open_time_utc INTEGER NOT NULL, sl REAL NOT NULL DEFAULT 0, tp REAL NOT NULL DEFAULT 0,
  profit REAL NOT NULL DEFAULT 0, swap REAL NOT NULL DEFAULT 0,
  PRIMARY KEY(account_id, position_id));
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
  position_id TEXT NOT NULL, time_utc INTEGER NOT NULL, kind TEXT NOT NULL,
  old_value REAL, new_value REAL);
CREATE INDEX IF NOT EXISTS events_position ON events(account_id, position_id);
CREATE TABLE IF NOT EXISTS notes(
  account_id TEXT NOT NULL, position_id TEXT NOT NULL, setup TEXT NOT NULL DEFAULT '',
  emotion TEXT NOT NULL DEFAULT '', rating INTEGER, note TEXT NOT NULL DEFAULT '',
  updated_at INTEGER, PRIMARY KEY(account_id, position_id));
CREATE TABLE IF NOT EXISTS equity_snapshots(
  account_id TEXT NOT NULL REFERENCES accounts(id), time_utc INTEGER NOT NULL,
  balance REAL, equity REAL, PRIMARY KEY(account_id, time_utc));
CREATE TABLE IF NOT EXISTS cal_events(
  id TEXT PRIMARY KEY, source TEXT NOT NULL, time_utc INTEGER NOT NULL, currency TEXT NOT NULL,
  title TEXT NOT NULL, code TEXT NOT NULL DEFAULT '', impact TEXT NOT NULL, forecast TEXT,
  previous TEXT, actual TEXT, updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS cal_time ON cal_events(time_utc);
CREATE TABLE IF NOT EXISTS news_items(
  id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL, link TEXT NOT NULL,
  published_utc INTEGER NOT NULL, markets TEXT NOT NULL DEFAULT '', fetched_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS news_time ON news_items(published_utc);
CREATE TABLE IF NOT EXISTS source_status(
  name TEXT PRIMARY KEY, last_try INTEGER, last_ok INTEGER, items INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS ai_reports(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, scope TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL, closed_trades INTEGER, model TEXT, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ai_kind ON ai_reports(kind, scope, created_at);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

DEFAULT_SETTINGS = {
    "timezone": "Asia/Tehran",
    "theme": {"preset": "firoozeh", "accent": "", "font_scale": 100, "density": "normal"},
    "rules": {
        "daily_loss_limit": 0,      # account currency; 0 turns the rule off
        "max_trades_per_day": 6,
        "max_consecutive_losses": 3,
        "cooldown_minutes": 15,
        "require_sl": True,
        "news_alert_minutes": 30,
    },
    "markets": ["US30", "XAUUSD"],
    "feeds": [],      # extra RSS addresses added by the user
    "proxy": "",      # e.g. http://127.0.0.1:10809
    "backup_dir": "", # empty uses the default folder
    "ai": {
        "format": "openai",   # openai | anthropic
        "base_url": "",
        "model": "",
        "api_key": "",
        "auto_every": 0,      # new closed trades between automatic coach reports; 0 is off
    },
}


class Database:
    """One SQLite connection per thread; sharing one across server threads corrupts cursors."""

    def __init__(self, path):
        self.path = str(path)
        self.local = threading.local()

    @property
    def connection(self) -> sqlite3.Connection:
        conn = getattr(self.local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            self.local.conn = conn
        return conn

    def execute(self, *args):
        return self.connection.execute(*args)

    def executemany(self, *args):
        return self.connection.executemany(*args)

    def executescript(self, script):
        return self.connection.executescript(script)

    def commit(self):
        self.connection.commit()

    def close(self):
        conn = getattr(self.local, "conn", None)
        if conn is not None:
            conn.close()
            self.local.conn = None

    def __enter__(self):
        return self.connection.__enter__()

    def __exit__(self, *exc):
        return self.connection.__exit__(*exc)


def connect(path) -> Database:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.execute("PRAGMA journal_mode=WAL")
    database.executescript(SCHEMA)
    return database


def get_settings(conn) -> dict:
    stored = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT * FROM settings")}
    merged = json.loads(json.dumps(DEFAULT_SETTINGS))
    for key, value in stored.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def put_setting(conn, key: str, value) -> None:
    conn.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )
    conn.commit()


def get_token(conn) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key='token'").fetchone()
    if row:
        return json.loads(row["value"])
    token = secrets.token_hex(16)
    put_setting(conn, "token", token)
    return token
