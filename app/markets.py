"""What moves each market: calendar rules, headline matching and the rule-based brief.

The directions here are the usual textbook reaction, not a forecast. The dashboard says so.
"""
import hashlib
import re
import time

MARKETS = {
    "US30": {"name": "داوجونز", "currencies": ["USD"], "aliases": ["US30", "DJ30", "DJI", "DOW", "WS30", "WALLST"],
             "news": ["dow jones", "dow ", "wall street", "stocks", "s&p 500", "s&p500", "earnings", "treasury yield", "fed "]},
    "NAS100": {"name": "نزدک", "currencies": ["USD"], "aliases": ["NAS", "US100", "USTEC", "NDX"],
               "news": ["nasdaq", "wall street", "tech stocks", "s&p 500", "treasury yield", "fed "]},
    "XAUUSD": {"name": "طلا", "currencies": ["USD"], "aliases": ["XAU", "GOLD"],
               "news": ["gold", "bullion", "xau", "safe haven", "safe-haven", "real yield", "treasury yield", "fed ", "federal reserve", "dollar"]},
    "EURUSD": {"name": "یورو/دلار", "currencies": ["EUR", "USD"], "aliases": ["EURUSD"],
               "news": ["euro", "ecb", "eurozone", "lagarde", "dollar", "fed ", "federal reserve"]},
    "GBPUSD": {"name": "پوند/دلار", "currencies": ["GBP", "USD"], "aliases": ["GBPUSD"],
               "news": ["pound", "sterling", "bank of england", "boe", "dollar", "fed ", "federal reserve"]},
    "USOIL": {"name": "نفت", "currencies": ["USD"], "aliases": ["USOIL", "WTI", "XTI", "OIL", "BRENT"],
              "news": ["oil", "crude", "opec", "brent", "wti"]},
}

UP, DOWN, MIXED = "up", "down", "mixed"
# Reaction when a figure comes in above forecast, per kind of event.
KINDS = [
    ("inflation", r"cpi|ppi|pce|inflation|consumer.price|producer.price|average.hourly|wage",
     {"USD": UP, "US30": DOWN, "NAS100": DOWN, "XAUUSD": DOWN}),
    ("rates", r"federal.funds|fed.interest|fomc|interest.rate|rate.decision",
     {"USD": UP, "US30": DOWN, "NAS100": DOWN, "XAUUSD": DOWN}),
    ("jobs_bad", r"unemployment|jobless|initial.claims|continuing.claims",
     {"USD": DOWN, "US30": MIXED, "NAS100": MIXED, "XAUUSD": UP}),
    ("growth", r"non.?farm|payroll|adp|gdp|retail.sales|ism|pmi|durable|consumer.confidence|consumer.sentiment|industrial",
     {"USD": UP, "US30": UP, "NAS100": UP, "XAUUSD": DOWN}),
]
KIND_LABEL = {"inflation": "تورم", "rates": "نرخ بهره", "jobs_bad": "بازار کار", "growth": "رشد و اشتغال"}
FAR = {"up": "صعودی", "down": "نزولی", "mixed": "نامشخص"}


def classify(title: str, code: str = "") -> tuple:
    text = f"{title} {code}".lower()
    for kind, pattern, effects in KINDS:
        if re.search(pattern, text):
            return kind, effects
    return None, {}


def parse_figure(text):
    """'0.3%' -> 0.3, '175K' -> 175000, '1.2B' -> 1.2e9, '' -> None"""
    if text is None:
        return None
    match = re.fullmatch(r"\s*([<>]?)(-?[\d,]*\.?\d+)\s*([KMBT%]?)\s*", str(text), re.I)
    if not match:
        return None
    scale = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(match.group(3).upper(), 1)
    return float(match.group(2).replace(",", "")) * scale


def surprise(row: dict):
    actual, forecast = parse_figure(row.get("actual")), parse_figure(row.get("forecast"))
    if actual is None or forecast is None:
        return None
    return "above" if actual > forecast else "below" if actual < forecast else "inline"


def event_effect(row: dict, market: str):
    """Usual direction for a market after this release, or None when it cannot be told."""
    kind, effects = classify(row["title"], row.get("code", ""))
    side = surprise(row)
    if row["currency"] != "USD" or side in (None, "inline"):
        return None
    effect = effects.get("USD" if market not in effects else market)
    if effect is None or effect == MIXED:
        return MIXED if effect else None
    if market in ("EURUSD", "GBPUSD") and market not in effects:
        effect = DOWN if effect == UP else UP  # USD is the quote currency here
    if side == "above":
        return effect
    return DOWN if effect == UP else UP


def currencies_for_symbol(symbol: str) -> list:
    upper = symbol.upper()
    for spec in MARKETS.values():
        if any(alias in upper for alias in spec["aliases"]):
            return spec["currencies"]
    letters = re.sub(r"[^A-Z]", "", upper)
    return [letters[:3], letters[3:6]] if len(letters) >= 6 else []


def tag_headline(title: str) -> list:
    text = f" {title.lower()} "
    return [key for key, spec in MARKETS.items() if any(word in text for word in spec["news"])]


def visible_events(rows: list) -> list:
    """Prefers the MT5 calendar, which has actual figures, over the weekly feed for the same span."""
    mt5 = [r for r in rows if r["source"] == "mt5"]
    if not mt5:
        return rows
    lo, hi = min(r["time_utc"] for r in mt5), max(r["time_utc"] for r in mt5)
    covered = {r["currency"] for r in mt5}
    others = [r for r in rows if r["source"] != "mt5"
              and not (r["currency"] in covered and lo <= r["time_utc"] <= hi)]
    return sorted(mt5 + others, key=lambda r: r["time_utc"])


def load_events(conn, start: int, end: int, impacts=("high", "medium")) -> list:
    marks = ",".join("?" * len(impacts))
    rows = conn.execute(
        f"SELECT * FROM cal_events WHERE time_utc BETWEEN ? AND ? AND impact IN ({marks}) ORDER BY time_utc",
        (start, end, *impacts)).fetchall()
    return visible_events([dict(r) for r in rows])


def flag_news_trades(trades: list, events: list, window: int = 900) -> None:
    high = [e for e in events if e["impact"] == "high"]
    for trade in trades:
        currencies = currencies_for_symbol(trade["symbol"])
        if any(e["currency"] in currencies and abs(e["time_utc"] - trade["open_time"]) <= window for e in high):
            trade["flags"].append("news_trade")


def events_during(trade: dict, events: list) -> list:
    currencies = currencies_for_symbol(trade["symbol"])
    start, end = trade["open_time"] - 900, (trade["close_time"] or int(time.time())) + 900
    return [e for e in events if e["currency"] in currencies and start <= e["time_utc"] <= end]


def describe_event(row: dict, market: str) -> dict:
    kind, _ = classify(row["title"], row.get("code", ""))
    effect = event_effect(row, market)
    return {**row, "kind": KIND_LABEL.get(kind, ""), "surprise": surprise(row), "effect": effect}


def rule_brief(conn, market: str, now=None) -> dict:
    now = int(time.time()) if now is None else now
    spec = MARKETS[market]
    events = [e for e in load_events(conn, now - 7 * 86400, now + 7 * 86400) if e["currency"] in spec["currencies"]]
    released = [describe_event(e, market) for e in events if e["time_utc"] <= now]
    upcoming = [describe_event(e, market) for e in events if e["time_utc"] > now]
    scored = [e for e in released if e["effect"] in (UP, DOWN)]
    ups, downs = sum(e["effect"] == UP for e in scored), sum(e["effect"] == DOWN for e in scored)
    if not scored:
        lean = "هنوز داده کافی نیست"
    elif abs(ups - downs) <= 1:
        lean = "متعادل"
    else:
        lean = "متمایل به صعود" if ups > downs else "متمایل به نزول"
    news = [dict(r) for r in conn.execute(
        "SELECT * FROM news_items WHERE (','||markets||',') LIKE ? AND published_utc>=? "
        "ORDER BY published_utc DESC LIMIT 40", (f"%,{market},%", now - 3 * 86400))]
    return {
        "market": market, "name": spec["name"], "lean": lean, "ups": ups, "downs": downs,
        "released": list(reversed(released))[:15], "upcoming": upcoming[:15], "news": news,
    }


def news_alerts(conn, rules: dict, markets: list, now: int) -> list:
    minutes = rules.get("news_alert_minutes", 0)
    if not minutes:
        return []
    wanted = {c for m in markets if m in MARKETS for c in MARKETS[m]["currencies"]}
    alerts = []
    for event in load_events(conn, now, now + minutes * 60, ("high",)):
        if event["currency"] in wanted:
            left = max((event["time_utc"] - now) // 60, 1)
            label = (event.get("code") or event["title"]).encode("ascii", "ignore").decode().replace("|", " ") or "event"
            key = hashlib.sha1(event["id"].encode()).hexdigest()[:12]
            alerts.append((f"news-{key}", "warn", f"High impact news in {left} min: {event['currency']} {label}"))
    return alerts
