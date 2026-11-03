"""Downloads the calendar and headlines. A failing source never stops the others."""
import hashlib
import json
import logging
import ssl
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

from . import db
from .markets import tag_headline

log = logging.getLogger("journal.feeds")
AGENT = "Mozilla/5.0 (personal trade journal)"
MAX_BYTES = 3_000_000
CALENDAR_EVERY = 3600   # the weekly file changes slowly and its host limits downloads
NEWS_EVERY = 600
KEEP_NEWS = 30 * 86400
FF_FILES = {"Forex Factory این هفته": "https://nfs.faireconomy.media/ff_calendar_thisweek.json"}
IMPACT = {"high": "high", "medium": "medium", "low": "low", "holiday": "holiday"}


def _google(query: str) -> str:
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})


RSS_FEEDS = {
    "فدرال رزرو": "https://www.federalreserve.gov/feeds/press_all.xml",
    "سخنرانی‌های فدرال رزرو": "https://www.federalreserve.gov/feeds/speeches.xml",
    "CNN Business": _google('when:2d site:cnn.com "CNN Business" -site:transcripts.cnn.com'),
    "داوجونز": _google('when:1d "Dow Jones" OR "Wall Street" stocks'),
    "طلا": _google('when:1d "gold price" OR "gold prices" OR bullion'),
    "دلار و فدرال رزرو": _google('when:1d "US dollar" OR "Federal Reserve" OR "Treasury yields"'),
    "Dukascopy": "https://www.dukascopy.com/fxspider/en/rss/news_sector/forex",
}


def build_opener(proxy: str = ""):
    """Uses certifi because Python from python.org on macOS ships without root certificates."""
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    handlers = [urllib.request.HTTPSHandler(context=context)]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def fetch(url: str, proxy: str = "") -> bytes:
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("only http and https addresses are allowed")
    opener = build_opener(proxy)
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with opener.open(request, timeout=20) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("response too large")
    return data


def parse_forex_factory(raw: bytes) -> list:
    rows = []
    for item in json.loads(raw):
        when = datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
        impact = IMPACT.get(str(item.get("impact", "")).lower())
        title = str(item.get("title", "")).strip()
        currency = str(item.get("country", "")).upper()
        if not impact or not title or len(currency) != 3:
            continue
        stamp = int(when.timestamp())
        rows.append({"id": f"ff:{currency}:{stamp}:{title}"[:200], "time_utc": stamp, "currency": currency,
                     "title": title, "impact": impact, "forecast": item.get("forecast") or None,
                     "previous": item.get("previous") or None})
    return rows


def _when(text: str, now: int) -> int:
    if not text:
        return now
    try:
        parsed = parsedate_to_datetime(text.strip())
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        except ValueError:
            return now
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return min(int(parsed.timestamp()), now)


def parse_rss(raw: bytes, now: int) -> list:
    if b"<!DOCTYPE" in raw[:2000].upper() or b"<!ENTITY" in raw[:2000].upper():
        raise ValueError("feed contains a document type declaration")
    root = ElementTree.fromstring(raw)
    rows = []
    for node in root.iter():
        name = node.tag.rsplit("}", 1)[-1]
        if name not in ("item", "entry"):
            continue
        fields = {child.tag.rsplit("}", 1)[-1]: child for child in node}
        title = (fields["title"].text or "").strip() if "title" in fields else ""
        link_node = fields.get("link")
        link = ""
        if link_node is not None:
            link = (link_node.text or link_node.get("href") or "").strip()
        if not title or not link.startswith(("http://", "https://")):
            continue
        date = fields.get("pubDate") if "pubDate" in fields else fields.get("updated", fields.get("published"))
        rows.append({"title": title[:400], "link": link, "published": _when(getattr(date, "text", ""), now)})
    return rows


def _mark(conn, name, now, items=None, error=None):
    conn.execute(
        """INSERT INTO source_status(name,last_try,last_ok,items,error) VALUES(?,?,?,?,?)
           ON CONFLICT(name) DO UPDATE SET last_try=excluded.last_try,
             last_ok=COALESCE(excluded.last_ok,last_ok),items=COALESCE(excluded.items,items),
             error=excluded.error""",
        (name, now, now if error is None else None, items, error))
    conn.commit()


def store_calendar(conn, rows: list, now: int) -> None:
    with conn:
        for r in rows:
            conn.execute(
                """INSERT INTO cal_events(id,source,time_utc,currency,title,impact,forecast,previous,updated_at)
                   VALUES(?,'ff',?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET impact=excluded.impact,
                   forecast=excluded.forecast,previous=excluded.previous,updated_at=excluded.updated_at""",
                (r["id"], r["time_utc"], r["currency"], r["title"], r["impact"], r["forecast"], r["previous"], now))


def store_news(conn, source: str, rows: list, now: int) -> None:
    with conn:
        for r in rows:
            key = hashlib.sha1(r["link"].encode()).hexdigest()
            markets = ",".join(tag_headline(r["title"]))
            conn.execute(
                "INSERT OR IGNORE INTO news_items(id,source,title,link,published_utc,markets,fetched_at) VALUES(?,?,?,?,?,?,?)",
                (key, source, r["title"], r["link"], r["published"], markets, now))
        conn.execute("DELETE FROM news_items WHERE published_utc<?", (now - KEEP_NEWS,))


def refresh_calendar(conn, fetcher=fetch, now=None) -> None:
    now = int(time.time()) if now is None else now
    proxy = db.get_settings(conn).get("proxy", "")
    for name, url in FF_FILES.items():
        try:
            rows = parse_forex_factory(fetcher(url, proxy))
            store_calendar(conn, rows, now)
            _mark(conn, name, now, len(rows))
        except Exception as error:
            log.warning("%s failed: %s", name, error)
            _mark(conn, name, now, error=str(error)[:200])


def refresh_news(conn, fetcher=fetch, now=None) -> None:
    now = int(time.time()) if now is None else now
    settings = db.get_settings(conn)
    sources = dict(RSS_FEEDS)
    for url in settings.get("feeds", []):
        sources[urllib.parse.urlsplit(url).netloc or url] = url
    for name, url in sources.items():
        try:
            rows = parse_rss(fetcher(url, settings.get("proxy", "")), now)
            store_news(conn, name, rows, now)
            _mark(conn, name, now, len(rows))
        except Exception as error:
            log.warning("%s failed: %s", name, error)
            _mark(conn, name, now, error=str(error)[:200])


class Worker(threading.Thread):
    """Refreshes sources in the background; `tick` runs other periodic jobs."""

    def __init__(self, conn_factory, tick=None):
        super().__init__(daemon=True)
        self.conn_factory, self.tick = conn_factory, tick
        self.stop_event, self.wake = threading.Event(), threading.Event()

    def run(self):
        conn = self.conn_factory()
        next_calendar = next_news = 0
        while not self.stop_event.is_set():
            now = time.time()
            if self.wake.is_set():
                self.wake.clear()
                next_calendar = next_news = 0
            if now >= next_calendar:
                refresh_calendar(conn)
                next_calendar = now + CALENDAR_EVERY
            if now >= next_news:
                refresh_news(conn)
                next_news = now + NEWS_EVERY
                if self.tick:
                    try:
                        self.tick(conn)
                    except Exception as error:
                        log.warning("periodic job failed: %s", error)
            self.wake.wait(30)
