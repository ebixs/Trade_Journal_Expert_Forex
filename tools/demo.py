"""Creates a sample database so the dashboard can be explored before connecting MetaTrader."""
import random
import time
from pathlib import Path

from app import db
from app.ingest import AccountIn, DealIn, PositionIn, SyncIn, apply_sync

OFFSET = 7200
ACCOUNT = AccountIn(login="1000001", server="Demo-Server", broker="نمونه", name="حساب نمونه",
                    currency="USD", leverage=100, platform="MT5", balance=11840, equity=11905,
                    gmt_offset=OFFSET)
SYMBOLS = {"XAUUSD": (2650.0, 100, 4.5), "US30": (42800.0, 1, 90.0), "EURUSD": (1.0850, 100000, 0.0018)}


def _trade(rng, ticket, opened, volume, symbol, win_bias, with_sl=True):
    base, contract, span = SYMBOLS[symbol]
    side = rng.choice(["buy", "sell"])
    sign = 1 if side == "buy" else -1
    entry = base + rng.uniform(-30, 30) * span / 4
    stop = span * rng.uniform(0.7, 1.2)
    won = rng.random() < win_bias
    move = stop * rng.uniform(0.6, 2.0) if won else -stop * rng.uniform(0.6, 1.05)
    exit_price = entry + sign * move
    held = int(rng.uniform(5, 60) * 60 if won else rng.uniform(15, 150) * 60)
    best = max(move, 0) + stop * rng.uniform(0.2, 1.4)
    worst = min(move, 0) - stop * rng.uniform(0.05, 0.4)
    mfe, mae = entry + sign * best, entry + sign * worst
    sl = entry - sign * stop if with_sl else 0
    tp = entry + sign * stop * 2 if with_sl else 0
    profit = round(move * volume * contract, 2)
    stamp = opened + OFFSET
    return [
        DealIn(id=f"{ticket}1", position=str(ticket), symbol=symbol, type=side, entry="in", volume=volume,
               price=entry, sl=sl, tp=tp, commission=-3.5 * volume, time=stamp),
        DealIn(id=f"{ticket}2", position=str(ticket), symbol=symbol, type="sell" if side == "buy" else "buy",
               entry="out", volume=volume, price=exit_price, sl=sl, tp=tp, profit=profit,
               commission=-3.5 * volume, time=stamp + held, mfe=mfe, mae=mae),
    ], opened + held, profit


def _seed_news(conn, now):
    """Invented sample rows so the news page can be explored offline."""
    hour = 3600
    rows = [("CPI m/m", -30 * hour, "high", "0.3%", "0.2%", "0.4%"), ("Core Retail Sales m/m", -28 * hour, "medium", "0.4%", "0.3%", "0.2%"),
            ("Unemployment Claims", -5 * hour, "medium", "220K", "218K", "231K"), ("ISM Services PMI", 20 * 60, "high", "52.5", "52.1", None),
            ("FOMC Member Speaks", 6 * hour, "medium", None, None, None), ("Non-Farm Employment Change", 40 * hour, "high", "150K", "142K", None)]
    for title, shift, impact, forecast, previous, actual in rows:
        conn.execute("INSERT INTO cal_events VALUES(?, 'mt5', ?, 'USD', ?, '', ?, ?, ?, ?, ?)",
                     (f"demo:{title}", now + shift, title, impact, forecast, previous, actual, now))
    news = [("نمونه", "Sample: gold holds gains as Treasury yields slip", "XAUUSD,US30"), ("نمونه", "Sample: Wall Street opens mixed before Fed speakers", "US30,NAS100"),
            ("نمونه", "Sample: Federal Reserve officials signal patience on rates", "US30,XAUUSD,EURUSD,GBPUSD,NAS100"),
            ("نمونه", "Sample: Dow Jones slips as earnings season continues", "US30")]
    for i, (source, title, tags) in enumerate(news):
        conn.execute("INSERT INTO news_items VALUES(?,?,?,?,?,?,?)", (f"demo{i}", source, title, "https://example.com/sample", now - (i + 1) * 2400, tags, now))
    conn.execute("INSERT INTO source_status VALUES('داده نمونه', ?, ?, 4, NULL)", (now, now))
    conn.commit()


def seed(path):
    Path(path).unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    conn = db.connect(path)
    rng = random.Random(14)
    now = int(time.time())
    deals, ticket, cursor = [], 500000, now - 75 * 86400
    last_loss = False
    while cursor < now - 6 * 3600 and len(deals) < 460:
        cursor += int(rng.uniform(1.5, 9) * 3600)
        if time.gmtime(cursor).tm_wday >= 5:
            continue
        ticket += 1
        symbol = rng.choices(list(SYMBOLS), [6, 3, 2])[0]
        hour = time.gmtime(cursor).tm_hour
        bias = 0.62 if 12 <= hour < 16 else 0.38 if hour < 7 else 0.5
        if symbol == "EURUSD":
            bias -= 0.14
        volume = rng.choice([0.05, 0.1, 0.1, 0.2])
        opened = cursor
        if last_loss and rng.random() < 0.3:
            opened, volume, bias = last_close + int(rng.uniform(2, 9) * 60), volume * 2, bias - 0.22
        legs, last_close, profit = _trade(rng, ticket, opened, volume, symbol, bias, rng.random() > 0.08)
        deals += legs
        cursor = max(cursor, last_close)
        last_loss = profit < 0
    apply_sync(conn, SyncIn(account=ACCOUNT, deals=deals), now - 60)
    positions = [PositionIn(id="900001", symbol="XAUUSD", side="buy", volume=0.1, price=2652.4,
                            time=now - 2400 + OFFSET, sl=2644.0, tp=2668.0, profit=65.0)]
    apply_sync(conn, SyncIn(account=ACCOUNT, positions=positions), now)
    _seed_news(conn, now)
    conn.close()
