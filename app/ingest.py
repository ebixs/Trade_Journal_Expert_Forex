"""Applies one sync message from the expert to the database."""
import re
import time
from typing import Optional

from pydantic import BaseModel, Field

FROM_TICKET = re.compile(r"from #(\d+)")
SNAPSHOT_EVERY = 300  # seconds between stored equity points


class AccountIn(BaseModel):
    login: str
    server: str
    broker: str = ""
    name: str = ""
    currency: str = ""
    leverage: int = 0
    platform: str = ""
    balance: float = 0
    equity: float = 0
    gmt_offset: Optional[int] = None


class DealIn(BaseModel):
    id: str
    position: str
    symbol: str = ""
    type: str  # buy | sell | balance
    entry: str = "in"  # in | out | inout | outby
    volume: float = 0
    price: float = 0
    sl: float = 0
    tp: float = 0
    profit: float = 0
    commission: float = 0
    swap: float = 0
    fee: float = 0
    time: int
    magic: int = 0
    comment: str = ""
    mfe: Optional[float] = None
    mae: Optional[float] = None


class PositionIn(BaseModel):
    id: str
    symbol: str
    side: str
    volume: float
    price: float
    time: int
    sl: float = 0
    tp: float = 0
    profit: float = 0
    swap: float = 0


class CalendarIn(BaseModel):
    id: str
    time: int
    currency: str
    title: str
    code: str = ""
    impact: str = "medium"
    forecast: Optional[float] = None
    previous: Optional[float] = None
    actual: Optional[float] = None


class SyncIn(BaseModel):
    account: AccountIn
    positions: list[PositionIn] = Field(default_factory=list)
    deals: list[DealIn] = Field(default_factory=list)
    calendar: list[CalendarIn] = Field(default_factory=list)


def nz(value: Optional[float]) -> Optional[float]:
    return value if value else None


def resolve_parent(conn, account_id: str, deal: DealIn) -> str:
    """MT4 gives the rest of a partly closed order a new ticket; keep it in one trade."""
    match = FROM_TICKET.search(deal.comment)
    if not match:
        return deal.position
    row = conn.execute(
        "SELECT position_id FROM deals WHERE account_id=? AND deal_id=?",
        (account_id, f"{match.group(1)}-in"),
    ).fetchone()
    return row["position_id"] if row else deal.position


def _store_account(conn, msg: SyncIn, now: int) -> tuple[str, int]:
    acc = msg.account
    account_id = f"{acc.server}:{acc.login}"
    row = conn.execute("SELECT gmt_offset FROM accounts WHERE id=?", (account_id,)).fetchone()
    if acc.gmt_offset is not None:
        offset = round(acc.gmt_offset / 900) * 900  # brokers sit on quarter-hour offsets
    else:
        offset = row["gmt_offset"] if row else 0
    conn.execute(
        """INSERT INTO accounts(id,login,server,broker,name,currency,leverage,platform,
             gmt_offset,balance,equity,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET broker=excluded.broker,name=excluded.name,
             currency=excluded.currency,leverage=excluded.leverage,platform=excluded.platform,
             gmt_offset=excluded.gmt_offset,balance=excluded.balance,equity=excluded.equity,
             last_seen=excluded.last_seen""",
        (account_id, acc.login, acc.server, acc.broker, acc.name, acc.currency, acc.leverage,
         acc.platform, offset, acc.balance, acc.equity, now),
    )
    return account_id, offset


def _store_deals(conn, msg: SyncIn, account_id: str, offset: int) -> None:
    for deal in msg.deals:
        conn.execute(
            """INSERT INTO deals(account_id,deal_id,position_id,symbol,type,entry,volume,price,
                 sl,tp,profit,commission,swap,fee,time_raw,time_utc,magic,comment,mfe_price,mae_price)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(account_id,deal_id) DO UPDATE SET
                 mfe_price=COALESCE(excluded.mfe_price,mfe_price),
                 mae_price=COALESCE(excluded.mae_price,mae_price)""",
            (account_id, deal.id, resolve_parent(conn, account_id, deal), deal.symbol, deal.type,
             deal.entry, deal.volume, deal.price, deal.sl, deal.tp, deal.profit, deal.commission,
             deal.swap, deal.fee, deal.time, deal.time - offset, deal.magic, deal.comment,
             nz(deal.mfe), nz(deal.mae)),
        )


def _store_positions(conn, msg: SyncIn, account_id: str, offset: int, now: int) -> None:
    known = {
        r["position_id"]: r
        for r in conn.execute("SELECT * FROM open_positions WHERE account_id=?", (account_id,))
    }
    conn.execute("DELETE FROM open_positions WHERE account_id=?", (account_id,))
    for pos in msg.positions:
        before = known.get(pos.id)
        changes = []
        if before is None:
            changes = [("first_sl", None, pos.sl), ("first_tp", None, pos.tp)]
        else:
            if before["sl"] != pos.sl:
                changes.append(("sl_change", before["sl"], pos.sl))
            if before["tp"] != pos.tp:
                changes.append(("tp_change", before["tp"], pos.tp))
        conn.executemany(
            "INSERT INTO events(account_id,position_id,time_utc,kind,old_value,new_value) "
            "VALUES(?,?,?,?,?,?)",
            [(account_id, pos.id, now, kind, old, new) for kind, old, new in changes],
        )
        conn.execute(
            """INSERT INTO open_positions(account_id,position_id,symbol,side,volume,open_price,
                 open_time_utc,sl,tp,profit,swap) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (account_id, pos.id, pos.symbol, pos.side, pos.volume, pos.price,
             pos.time - offset, pos.sl, pos.tp, pos.profit, pos.swap),
        )


def _store_equity(conn, msg: SyncIn, account_id: str, now: int) -> None:
    last = conn.execute(
        "SELECT MAX(time_utc) t FROM equity_snapshots WHERE account_id=?", (account_id,)
    ).fetchone()["t"]
    if last is None or now - last >= SNAPSHOT_EVERY:
        conn.execute(
            "INSERT OR IGNORE INTO equity_snapshots VALUES(?,?,?,?)",
            (account_id, now, msg.account.balance, msg.account.equity),
        )


def _text(value: Optional[float]) -> Optional[str]:
    return None if value is None else f"{value:g}"


def _store_calendar(conn, msg: SyncIn, offset: int, now: int) -> None:
    for row in msg.calendar:
        conn.execute(
            """INSERT INTO cal_events(id,source,time_utc,currency,title,code,impact,forecast,
                 previous,actual,updated_at) VALUES(?,'mt5',?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET time_utc=excluded.time_utc,forecast=excluded.forecast,
                 previous=excluded.previous,actual=excluded.actual,updated_at=excluded.updated_at""",
            (f"mt5:{row.id}", row.time - offset, row.currency, row.title, row.code, row.impact,
             _text(row.forecast), _text(row.previous), _text(row.actual), now),
        )
    if msg.calendar:
        conn.execute(
            """INSERT INTO source_status(name,last_try,last_ok,items,error) VALUES('تقویم متاتریدر ۵',?,?,?,NULL)
               ON CONFLICT(name) DO UPDATE SET last_try=excluded.last_try,last_ok=excluded.last_ok,
                 items=excluded.items,error=NULL""", (now, now, len(msg.calendar)))


def apply_sync(conn, msg: SyncIn, now: Optional[int] = None) -> tuple[str, int]:
    """Stores the message atomically. Returns the account id and the history cursor."""
    now = int(time.time()) if now is None else now
    with conn:
        account_id, offset = _store_account(conn, msg, now)
        _store_deals(conn, msg, account_id, offset)
        _store_positions(conn, msg, account_id, offset, now)
        _store_equity(conn, msg, account_id, now)
        _store_calendar(conn, msg, offset, now)
    cursor = conn.execute(
        "SELECT COALESCE(MAX(time_raw),0) c FROM deals WHERE account_id=?", (account_id,)
    ).fetchone()["c"]
    return account_id, cursor
