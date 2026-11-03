"""Daily copies of the journal, kept outside the project folder and free of the API key."""
import json
import sqlite3
import time
from pathlib import Path

KEEP = 30
DUE_AFTER = 20 * 3600


def default_folder() -> Path:
    """iCloud keeps a copy off this computer when it is available."""
    cloud = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    base = cloud if cloud.exists() else Path.home() / "Documents"
    return base / "TradeJournalBackups"


def folder(settings: dict) -> Path:
    chosen = settings.get("backup_dir", "")
    return Path(chosen).expanduser() if chosen else default_folder()


def copies(target: Path) -> list:
    return sorted(target.glob("journal-*.db")) if target.exists() else []


def status(settings: dict) -> dict:
    target = folder(settings)
    found = copies(target)
    return {"folder": str(target), "count": len(found),
            "latest": int(found[-1].stat().st_mtime) if found else None}


def _remove_api_key(path: Path) -> None:
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT value FROM settings WHERE key='ai'").fetchone()
    if row:
        data = json.loads(row[0])
        data["api_key"] = ""
        conn.execute("UPDATE settings SET value=? WHERE key='ai'", (json.dumps(data, ensure_ascii=False),))
        conn.commit()
    conn.execute("VACUUM")  # the old value must not remain in free pages
    conn.close()


def create(database, settings: dict, now=None) -> Path:
    now = time.time() if now is None else now
    target = folder(settings)
    target.mkdir(parents=True, exist_ok=True)
    final = target / f"journal-{time.strftime('%Y-%m-%d', time.localtime(now))}.db"
    partial = final.with_suffix(".part")
    partial.unlink(missing_ok=True)
    destination = sqlite3.connect(partial)
    database.connection.backup(destination)
    destination.close()
    _remove_api_key(partial)
    partial.replace(final)
    for old in copies(target)[:-KEEP]:
        old.unlink()
    return final


def run_if_due(database, settings: dict, now=None) -> bool:
    now = time.time() if now is None else now
    found = copies(folder(settings))
    if found and now - found[-1].stat().st_mtime < DUE_AFTER:
        return False
    create(database, settings, now)
    return True
