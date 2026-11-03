"""Turns raw deals into trades, statistics, behaviour flags, insights and chart alerts."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

EPS = 1e-9
MIN_SAMPLE = 10  # below this a group is shown but never turned into advice
SESSIONS = [(0, 7, "آسیا"), (7, 12, "لندن"), (12, 16, "هم‌پوشانی لندن و نیویورک"),
            (16, 21, "نیویورک"), (21, 24, "پایان روز")]
WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]
JALALI_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                 "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
FLAG_LABELS = {
    "no_sl": "بدون حد ضرر",
    "sl_widened": "حد ضرر دورتر شد",
    "revenge": "ورود سریع بعد از ضرر",
    "size_up": "حجم بیشتر بعد از ضرر",
    "overtrade": "بیش از سقف روزانه",
    "early_exit": "خروج زودهنگام",
    "news_trade": "ورود نزدیک خبر مهم",
}


def ltr(text) -> str:
    """Keeps signs and currency in order inside right-to-left Persian sentences."""
    return f"\u2066{text}\u2069"


def signed(value: float, currency: str = "") -> str:
    return ltr(f"{value:+.2f} {currency}".strip())


def to_jalali(y: int, m: int, d: int) -> tuple[int, int, int]:
    g_days = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = y + 1 if m > 2 else y
    days = (355666 + 365 * y + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
            + d + g_days[m - 1])
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        return jy, 1 + days // 31, 1 + days % 31
    return jy, 7 + (days - 186) // 30, 1 + (days - 186) % 30


def fmt_local(ts: int, tz: ZoneInfo) -> str:
    dt = datetime.fromtimestamp(ts, tz)
    jy, jm, jd = to_jalali(dt.year, dt.month, dt.day)
    return f"{jd} {JALALI_MONTHS[jm - 1]} {jy} ساعت {dt:%H:%M}"


def fmt_duration(seconds: int) -> str:
    minutes = seconds // 60
    if minutes < 1:
        return f"{seconds} ثانیه"
    if minutes < 60:
        return f"{minutes} دقیقه"
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} ساعت و {rest} دقیقه" if rest else f"{hours} ساعت"
    days, hours = divmod(hours, 24)
    return f"{days} روز و {hours} ساعت" if hours else f"{days} روز"


def fmt_price(value: float) -> str:
    return f"{value:.5f}".rstrip("0").rstrip(".")


def vwap(legs: list) -> float:
    volume = sum(d["volume"] for d in legs)
    return sum(d["price"] * d["volume"] for d in legs) / volume if volume > EPS else 0.0


def _first_positive(values):
    return next((v for v in values if v), None)


def build_trade(deals: list, events: list) -> dict:
    deals = sorted(deals, key=lambda d: (d["time_utc"], d["deal_id"]))
    events = sorted(events, key=lambda e: (e["time_utc"], e["id"]))
    entries = [d for d in deals if d["entry"] == "in"]
    exits = [d for d in deals if d["entry"] in ("out", "outby", "inout")]
    anchor = entries[0] if entries else deals[0]
    side = anchor["type"] if entries else ("sell" if anchor["type"] == "buy" else "buy")
    sign = 1 if side == "buy" else -1
    vol_in, vol_out = sum(d["volume"] for d in entries), sum(d["volume"] for d in exits)
    entry_price, exit_price = vwap(entries), vwap(exits)
    gross = sum(d["profit"] for d in deals)
    costs = sum(d["commission"] + d["swap"] + d["fee"] for d in deals)
    first_sl = _first_positive(e["new_value"] for e in events if e["kind"] == "first_sl")
    first_tp = _first_positive(e["new_value"] for e in events if e["kind"] == "first_tp")
    sl_moves = [e for e in events if e["kind"] == "sl_change"]
    sl_initial = _first_positive(d["sl"] for d in entries) or first_sl
    if sl_initial is None:
        sl_initial = _first_positive(e["new_value"] for e in sl_moves)
    tp_initial = _first_positive(d["tp"] for d in entries) or first_tp
    sl_final = _first_positive(d["sl"] for d in reversed(exits)) or (
        sl_moves[-1]["new_value"] if sl_moves else sl_initial)
    closed = bool(entries) and bool(exits) and vol_out >= vol_in - 1e-6
    mfes = [d["mfe_price"] for d in exits if d["mfe_price"]]
    maes = [d["mae_price"] for d in exits if d["mae_price"]]
    mfe = (max(mfes) if sign > 0 else min(mfes)) if mfes else None
    mae = (min(maes) if sign > 0 else max(maes)) if maes else None

    # Money per unit of price comes from the trade itself, so no tick value is needed.
    move = abs(exit_price - entry_price) * (vol_out / vol_in if vol_in > EPS else 1)
    per_price = abs(gross) / move if closed and move > EPS and gross else None
    risk = r_multiple = mfe_r = capture = None
    if per_price and sl_initial and (entry_price - sl_initial) * sign > 0:
        risk = abs(entry_price - sl_initial) * per_price
        r_multiple = (gross + costs) / risk
        if mfe is not None:
            mfe_r = max((mfe - entry_price) * sign, 0) * per_price / risk
    if per_price and mfe is not None and gross > 0:
        best = max((mfe - entry_price) * sign, 0) * per_price
        capture = min(gross / best, 1.0) if best > EPS else None

    flags = []
    if not sl_initial and not sl_final:
        flags.append("no_sl")
    if any(e["old_value"] and e["new_value"] is not None
           and (not e["new_value"] or (e["new_value"] - e["old_value"]) * sign < 0)
           and not _moved_to_profit(e, entry_price, sign) for e in sl_moves):
        flags.append("sl_widened")
    if capture is not None and capture < 0.4:
        flags.append("early_exit")

    open_time = entries[0]["time_utc"] if entries else deals[0]["time_utc"]
    close_time = exits[-1]["time_utc"] if closed else None
    return {
        "account_id": anchor["account_id"], "position_id": anchor["position_id"],
        "symbol": anchor["symbol"], "side": side, "volume": round(vol_in, 2),
        "closed_volume": round(vol_out, 2), "entry_price": entry_price,
        "exit_price": exit_price or None, "open_time": open_time, "close_time": close_time,
        "duration": close_time - open_time if close_time else None, "gross": round(gross, 2),
        "costs": round(costs, 2), "net": round(gross + costs, 2), "closed": closed,
        "sl_initial": sl_initial, "tp_initial": tp_initial, "sl_final": sl_final,
        "exit_count": len(exits), "entry_count": len(entries), "mfe_price": mfe, "mae_price": mae,
        "risk_money": round(risk, 2) if risk else None,
        "r_multiple": round(r_multiple, 2) if r_multiple is not None else None,
        "mfe_r": round(mfe_r, 2) if mfe_r is not None else None,
        "capture": round(capture, 3) if capture is not None else None, "flags": flags,
    }


def _moved_to_profit(event: dict, entry: float, sign: int) -> bool:
    return bool(event["new_value"]) and (event["new_value"] - entry) * sign >= 0


def apply_sequence_flags(trades: list, rules: dict, tz: ZoneInfo) -> None:
    """Flags that depend on what happened just before a trade, per account."""
    by_account = defaultdict(list)
    for trade in trades:
        by_account[trade["account_id"]].append(trade)
    cooldown = rules.get("cooldown_minutes", 0) * 60
    limit = rules.get("max_trades_per_day", 0)
    for group in by_account.values():
        group.sort(key=lambda t: t["open_time"])
        per_day = defaultdict(int)
        for i, trade in enumerate(group):
            day = datetime.fromtimestamp(trade["open_time"], tz).date()
            per_day[day] += 1
            if limit and per_day[day] > limit:
                trade["flags"].append("overtrade")
            prior = [t for t in group[:i]
                     if t["closed"] and t["close_time"] <= trade["open_time"]]
            if not prior:
                continue
            last = max(prior, key=lambda t: t["close_time"])
            if last["net"] >= 0:
                continue
            if cooldown and trade["open_time"] - last["close_time"] < cooldown:
                trade["flags"].append("revenge")
            if trade["volume"] >= last["volume"] * 1.5:
                trade["flags"].append("size_up")


def build_trades(deals: list, events: list, rules: dict, tz: ZoneInfo) -> list:
    grouped, event_map = defaultdict(list), defaultdict(list)
    for deal in deals:
        if deal["type"] in ("buy", "sell"):
            grouped[(deal["account_id"], deal["position_id"])].append(deal)
    for event in events:
        event_map[(event["account_id"], event["position_id"])].append(event)
    trades = [build_trade(legs, event_map[key]) for key, legs in grouped.items()]
    apply_sequence_flags(trades, rules, tz)
    trades.sort(key=lambda t: t["close_time"] or t["open_time"], reverse=True)
    return trades


def timeline(deals: list, events: list, trade: dict, tz: ZoneInfo) -> list:
    rows = []
    for d in deals:
        if d["entry"] == "in":
            text = f"ورود {'خرید' if d['type'] == 'buy' else 'فروش'} {d['volume']:g} لات روی {fmt_price(d['price'])}"
        else:
            text = f"خروج {d['volume']:g} لات روی {fmt_price(d['price'])} با نتیجه {signed(d['profit'])}"
        rows.append((d["time_utc"], text))
    names = {"sl_change": "حد ضرر", "tp_change": "حد سود"}
    for e in events:
        if e["kind"] in names:
            old = fmt_price(e["old_value"]) if e["old_value"] else "خالی"
            new = fmt_price(e["new_value"]) if e["new_value"] else "حذف شد"
            rows.append((e["time_utc"], f"{names[e['kind']]} از {old} به {new} تغییر کرد"))
    return [{"time": t, "label": fmt_local(t, tz), "text": x} for t, x in sorted(rows, key=lambda r: r[0])]


def narrate(trade: dict, tz: ZoneInfo, currency: str = "") -> str:
    side = "خرید" if trade["side"] == "buy" else "فروش"
    parts = [f"{fmt_local(trade['open_time'], tz)} وارد {side} {trade['symbol']} با حجم "
             f"{trade['volume']:g} لات روی قیمت {fmt_price(trade['entry_price'])} شدی."]
    if trade["sl_initial"]:
        plan = f"حد ضررت را روی {fmt_price(trade['sl_initial'])} گذاشتی"
        if trade["risk_money"]:
            plan += f" و ریسک این معامله {ltr(f"{trade['risk_money']:.2f} {currency}")} بود"
        parts.append(plan + ".")
    else:
        parts.append("هنگام ورود حد ضرر ثبت نشد.")
    if trade["closed"]:
        result = "سود" if trade["net"] >= 0 else "ضرر"
        text = (f"معامله بعد از {fmt_duration(trade['duration'])} روی "
                f"{fmt_price(trade['exit_price'])} بسته شد و خالص "
                f"{ltr(f"{abs(trade['net']):.2f} {currency}")} {result} داد")
        if trade["r_multiple"] is not None:
            text += f" ({ltr(f"{trade['r_multiple']:+.2f}R")})"
        parts.append(text + ".")
    else:
        parts.append("این معامله هنوز کامل بسته نشده است.")
    if trade["capture"] is not None:
        parts.append(f"از بهترین حرکت قیمت به سمت معامله، {trade['capture'] * 100:.0f}٪ را گرفتی.")
    labels = [FLAG_LABELS[f] for f in trade["flags"]]
    if labels:
        parts.append("نکته‌های رفتاری: " + "، ".join(labels) + ".")
    return " ".join(parts)


def _group_stats(trades: list) -> dict:
    wins = [t for t in trades if t["net"] > 0]
    losses = [t for t in trades if t["net"] < 0]
    gross_win = sum(t["net"] for t in wins)
    gross_loss = -sum(t["net"] for t in losses)
    rs = [t["r_multiple"] for t in trades if t["r_multiple"] is not None]
    n = len(trades)
    return {
        "count": n, "wins": len(wins), "losses": len(losses),
        "net": round(gross_win - gross_loss, 2),
        "win_rate": round(len(wins) / n * 100, 1) if n else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "expectancy": round((gross_win - gross_loss) / n, 2) if n else None,
        "avg_win": round(gross_win / len(wins), 2) if wins else None,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else None,
        "avg_r": round(sum(rs) / len(rs), 2) if rs else None, "r_count": len(rs),
    }


def session_of(ts: int) -> str:
    hour = datetime.fromtimestamp(ts, timezone.utc).hour
    return next(name for lo, hi, name in SESSIONS if lo <= hour < hi)


def _breakdown(trades: list, key, order=None) -> list:
    groups = defaultdict(list)
    for trade in trades:
        groups[key(trade)].append(trade)
    names = order or sorted(groups, key=lambda k: -len(groups[k]))
    return [{"name": n, **_group_stats(groups[n])} for n in names if n in groups]


def equity_curve(closed: list) -> tuple[list, float]:
    points, running, peak, max_dd = [], 0.0, 0.0, 0.0
    for trade in sorted(closed, key=lambda t: t["close_time"]):
        running += trade["net"]
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)
        points.append({"t": trade["close_time"], "v": round(running, 2), "symbol": trade["symbol"],
                       "net": trade["net"]})
    return points, round(max_dd, 2)


def streaks(closed: list) -> tuple[int, int]:
    best_win = best_loss = win = loss = 0
    for trade in sorted(closed, key=lambda t: t["close_time"]):
        win = win + 1 if trade["net"] > 0 else 0
        loss = loss + 1 if trade["net"] < 0 else 0
        best_win, best_loss = max(best_win, win), max(best_loss, loss)
    return best_win, best_loss


def _insight(level, title, evidence, advice):
    return {"level": level, "title": title, "evidence": evidence, "advice": advice}


def _best_worst(rows: list, what: str, currency: str) -> list:
    ranked = sorted((r for r in rows if r["count"] >= MIN_SAMPLE), key=lambda r: r["expectancy"])
    if len(ranked) < 2:
        return []
    worst, best = ranked[0], ranked[-1]
    if worst["expectancy"] >= 0 or best["expectancy"] <= 0:
        return []
    return [_insight(
        "warn", f"{what}: {worst['name']} ضعیف‌ترین و {best['name']} قوی‌ترین است",
        f"{worst['name']}: {worst['count']} معامله، میانگین {signed(worst['expectancy'], currency)}. "
        f"{best['name']}: {best['count']} معامله، میانگین {signed(best['expectancy'], currency)}.",
        f"این تفاوت را با معامله‌های بعدی بسنج. اگر ماندگار بود، در {worst['name']} حجم را کم کن.")]


def _behaviour_insights(closed: list, currency: str) -> list:
    out = []
    advice = {
        "revenge": "بعد از هر معامله ضررده تا پایان زمان استراحت معامله جدید باز نکن.",
        "size_up": "حجم را از قبل با درصد ریسک ثابت کن، نه با نتیجه معامله قبلی.",
        "no_sl": "پیش از ورود جای حد ضرر را مشخص کن و همان لحظه ثبتش کن.",
        "sl_widened": "حد ضرر را فقط به سمت سود جابه‌جا کن.",
        "overtrade": "به سقف روزانه که رسیدی، چارت را ببند و معامله‌های آن روز را مرور کن.",
        "news_trade": "چند دقیقه قبل و بعد از خبر مهم وارد نشو، مگر این‌که برای خبر استراتژی جدا داری.",
    }
    for flag, tip in advice.items():
        marked = [t for t in closed if flag in t["flags"]]
        rest = [t for t in closed if flag not in t["flags"]]
        if len(marked) < 3:
            continue
        s, other = _group_stats(marked), _group_stats(rest)
        if s["net"] >= 0 and (other["expectancy"] or 0) <= (s["expectancy"] or 0):
            continue
        evidence = (f"{s['count']} معامله با جمع {signed(s['net'], currency)} و برد {s['win_rate']:.0f}٪")
        if other["count"]:
            evidence += f". بقیه معامله‌ها برد {other['win_rate']:.0f}٪ داشتند"
        out.append((s["net"], _insight("bad", FLAG_LABELS[flag], evidence + ".", tip)))
    return [item for _, item in sorted(out, key=lambda x: x[0])]


def build_insights(closed: list, summary: dict, tables: dict, currency: str) -> list:
    if len(closed) < 10:
        return [_insight("info", "هنوز نمونه کافی نیست",
                         f"تا الان {len(closed)} معامله بسته شده.",
                         "از ۱۰ معامله به بعد الگوها و پیشنهادها اینجا نمایش داده می‌شوند.")]
    items = _behaviour_insights(closed, currency)
    wins = [t["duration"] for t in closed if t["net"] > 0]
    losses = [t["duration"] for t in closed if t["net"] < 0]
    if len(wins) >= MIN_SAMPLE and len(losses) >= MIN_SAMPLE:
        avg_w, avg_l = sum(wins) / len(wins), sum(losses) / len(losses)
        if avg_l > avg_w * 1.5:
            items.append(_insight(
                "warn", "ضررها را بیشتر از سودها نگه می‌داری",
                f"میانگین نگهداری ضرر {fmt_duration(int(avg_l))} و سود {fmt_duration(int(avg_w))} است.",
                "برای هر معامله از قبل زمان یا شرط ابطال تعیین کن و ضرر را امیدوارانه نگه ندار."))
    if summary["avg_win"] and summary["avg_loss"]:
        ratio = summary["avg_win"] / abs(summary["avg_loss"])
        breakeven = 100 / (1 + ratio)
        ahead = summary["win_rate"] > breakeven
        items.append(_insight(
            "good" if ahead else "warn", "نسبت سود به ضرر",
            f"میانگین سود {ratio:.2f} برابر میانگین ضرر است، پس برای سر به سر شدن "
            f"برد {breakeven:.0f}٪ لازم داری و برد فعلی {summary['win_rate']:.0f}٪ است.",
            "فاصله تو از نقطه سر به سر را نگه دار و با کاهش خطاهای رفتاری بیشترش کن." if ahead
            else "یا کیفیت ورود را بالا ببر، یا فاصله هدف را نسبت به حد ضرر بیشتر کن."))
    captures = [t["capture"] for t in closed if t["capture"] is not None]
    if len(captures) >= MIN_SAMPLE:
        avg = sum(captures) / len(captures)
        if avg < 0.5:
            items.append(_insight(
                "warn", "بخش زیادی از حرکت را جا می‌گذاری",
                f"در معامله‌های سودده به‌طور میانگین {avg * 100:.0f}٪ از بهترین حرکت را گرفته‌ای.",
                "روی چند معامله خروج پله‌ای یا هدف دورتر را آزمایش کن و نتیجه را اینجا مقایسه کن."))
    items += _best_worst(tables["symbols"], "نماد", currency)
    items += _best_worst(tables["sessions"], "سشن", currency)
    items += _best_worst(tables["weekdays"], "روز هفته", currency)
    return items[:8]


def strategy_profile(closed: list) -> dict | None:
    if len(closed) < 10:
        return None
    avg = sum(t["duration"] for t in closed) / len(closed)
    if avg < 15 * 60:
        style, text = "اسکالپر", "بیشتر معامله‌هایت زیر ۱۵ دقیقه‌اند"
    elif avg < 8 * 3600:
        style, text = "روزمعامله‌گر", "معامله‌هایت را معمولاً داخل همان روز می‌بندی"
    else:
        style, text = "سوئینگ", "معامله‌هایت را بیشتر از یک سشن نگه می‌داری"
    return {"style": style, "text": text, "avg_duration": fmt_duration(int(avg))}


def build_overview(trades: list, tz: ZoneInfo, currency: str) -> dict:
    closed = [t for t in trades if t["closed"]]
    summary = _group_stats(closed)
    curve, max_dd = equity_curve(closed)
    win_streak, loss_streak = streaks(closed)
    summary.update({
        "max_drawdown": max_dd, "best": max((t["net"] for t in closed), default=None),
        "worst": min((t["net"] for t in closed), default=None), "win_streak": win_streak,
        "loss_streak": loss_streak, "costs": round(sum(t["costs"] for t in closed), 2),
    })
    local = lambda t: datetime.fromtimestamp(t["open_time"], tz)
    tables = {
        "symbols": _breakdown(closed, lambda t: t["symbol"]),
        "sessions": _breakdown(closed, lambda t: session_of(t["open_time"]),
                               [name for _, _, name in SESSIONS]),
        "weekdays": _breakdown(closed, lambda t: WEEKDAYS[local(t).weekday()],
                               [WEEKDAYS[i] for i in (5, 6, 0, 1, 2, 3, 4)]),
        "sides": _breakdown(closed, lambda t: "خرید" if t["side"] == "buy" else "فروش"),
    }
    daily = defaultdict(lambda: {"net": 0.0, "count": 0})
    for trade in closed:
        day = datetime.fromtimestamp(trade["close_time"], tz).date()
        daily[day]["net"] += trade["net"]
        daily[day]["count"] += 1
    flags = [{"flag": k, "label": v, "count": sum(k in t["flags"] for t in closed),
              "net": round(sum(t["net"] for t in closed if k in t["flags"]), 2)}
             for k, v in FLAG_LABELS.items()]
    return {
        "summary": summary, "equity": curve, "tables": tables,
        "daily": [{"date": d.isoformat(), "net": round(v["net"], 2), "count": v["count"]}
                  for d, v in sorted(daily.items())],
        "flags": [f for f in flags if f["count"]],
        "insights": build_insights(closed, summary, tables, currency),
        "profile": strategy_profile(closed),
    }


def build_alerts(trades: list, positions: list, rules: dict, tz: ZoneInfo, now: int) -> list:
    """Returns (id, level, English text). Chart labels cannot shape Persian reliably."""
    today = datetime.fromtimestamp(now, tz).date()
    start = int(datetime.combine(today, datetime.min.time(), tz).timestamp())
    day_closed = sorted((t for t in trades if t["closed"] and t["close_time"] >= start),
                        key=lambda t: t["close_time"])
    opened = [t for t in trades if t["open_time"] >= start]
    pnl = sum(t["net"] for t in day_closed)
    alerts, tag = [], today.isoformat()
    limit = rules.get("daily_loss_limit", 0)
    if limit and pnl <= -limit:
        alerts.append((f"daily-loss-{tag}", "stop", f"Daily loss limit hit: {pnl:.2f}. Stop trading today."))
    max_trades = rules.get("max_trades_per_day", 0)
    if max_trades and len(opened) >= max_trades:
        alerts.append((f"max-trades-{tag}", "warn", f"{len(opened)} trades today. Your limit is {max_trades}."))
    losses = 0
    for trade in reversed(day_closed):
        if trade["net"] >= 0:
            break
        losses += 1
    max_losses = rules.get("max_consecutive_losses", 0)
    if max_losses and losses >= max_losses:
        alerts.append((f"loss-streak-{tag}-{losses}", "stop", f"{losses} losses in a row. Take a break."))
    cooldown = rules.get("cooldown_minutes", 0) * 60
    if cooldown and day_closed and day_closed[-1]["net"] < 0:
        left = day_closed[-1]["close_time"] + cooldown - now
        if left > 0:
            alerts.append((f"cooldown-{day_closed[-1]['position_id']}", "warn",
                           f"Cooldown after loss: {max(left // 60, 1)} min left."))
    if rules.get("require_sl"):
        for pos in positions:
            if not pos["sl"]:
                alerts.append((f"no-sl-{pos['position_id']}", "warn",
                               f"{pos['symbol']} #{pos['position_id']} has no stop loss."))
    return alerts
