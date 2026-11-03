import json
import time
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import analytics, db
from app.ingest import AccountIn, DealIn, PositionIn, SyncIn, apply_sync
from app.main import create_app

UTC = ZoneInfo("UTC")
ACC = AccountIn(login="1", server="S", currency="USD", gmt_offset=7200, platform="MT5")
AID = "S:1"
RULES = db.DEFAULT_SETTINGS["rules"]


def deal(i, pos, kind, entry, vol, price, t, **kw):
    return DealIn(id=str(i), position=str(pos), symbol="XAUUSD", type=kind, entry=entry,
                  volume=vol, price=price, time=t, **kw)


def trades_of(conn):
    deals = [dict(r) for r in conn.execute("SELECT * FROM deals")]
    events = [dict(r) for r in conn.execute("SELECT * FROM events")]
    return analytics.build_trades(deals, events, RULES, UTC)


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "t.db")


def test_broker_time_is_converted_to_utc(conn):
    apply_sync(conn, SyncIn(account=ACC, deals=[deal(1, 1, "buy", "in", 1, 100, 10_000)]))
    assert conn.execute("SELECT time_utc FROM deals").fetchone()[0] == 2800


def test_resending_a_deal_changes_nothing_but_adds_mfe(conn):
    d = deal(2, 1, "sell", "out", 1, 110, 10_000, profit=1000)
    apply_sync(conn, SyncIn(account=ACC, deals=[d, d]))
    apply_sync(conn, SyncIn(account=ACC, deals=[d.model_copy(update={"mfe": 120.0})]))
    rows = conn.execute("SELECT * FROM deals").fetchall()
    assert len(rows) == 1 and rows[0]["mfe_price"] == 120 and rows[0]["profit"] == 1000


def test_long_trade_with_partial_exit_uses_weighted_prices_and_all_costs(conn):
    apply_sync(conn, SyncIn(account=ACC, deals=[
        deal(1, 7, "buy", "in", 1.0, 100, 1000, sl=90, commission=-5),
        deal(2, 7, "sell", "out", 0.5, 110, 2000, profit=500, commission=-2),
        deal(3, 7, "sell", "out", 0.5, 120, 3000, profit=1000, commission=-2, swap=-1, mfe=130),
    ]))
    t = trades_of(conn)[0]
    assert t["closed"] and t["side"] == "buy"
    assert t["exit_price"] == pytest.approx(115)
    assert t["net"] == 1490 and t["costs"] == -10
    assert t["risk_money"] == pytest.approx(1000)
    assert t["r_multiple"] == pytest.approx(1.49)
    assert t["capture"] == pytest.approx(0.5)


def test_partly_closed_trade_is_not_counted_as_closed(conn):
    apply_sync(conn, SyncIn(account=ACC, deals=[
        deal(1, 7, "buy", "in", 1, 100, 1000), deal(2, 7, "sell", "out", 0.4, 110, 2000, profit=400)]))
    t = trades_of(conn)[0]
    assert not t["closed"]
    assert analytics.build_overview([t], UTC, "USD")["summary"]["count"] == 0


def test_short_trade_sl_above_entry_gives_negative_r(conn):
    apply_sync(conn, SyncIn(account=ACC, deals=[
        deal(1, 8, "sell", "in", 1, 100, 1000, sl=110),
        deal(2, 8, "buy", "out", 1, 110, 2000, profit=-1000)]))
    t = trades_of(conn)[0]
    assert t["side"] == "sell" and t["r_multiple"] == -1


def test_balance_operations_are_not_trades(conn):
    apply_sync(conn, SyncIn(account=ACC, deals=[
        DealIn(id="9", position="9", type="balance", entry="in", profit=5000, time=1000)]))
    assert trades_of(conn) == []


def test_mt4_partial_close_joins_the_parent_trade(conn):
    apply_sync(conn, SyncIn(account=ACC, deals=[
        deal("100-in", 100, "buy", "in", 0.5, 100, 1000), deal("100-out", 100, "sell", "out", 0.5, 110, 2000, profit=500),
        deal("101-in", 101, "buy", "in", 0.5, 100, 1000, comment="from #100"),
        deal("101-out", 101, "sell", "out", 0.5, 120, 3000, profit=1000, comment="from #100")]))
    rows = trades_of(conn)
    assert len(rows) == 1 and rows[0]["volume"] == 1 and rows[0]["net"] == 1500


def test_stop_moves_are_logged_and_widening_is_flagged(conn):
    pos = lambda sl: PositionIn(id="5", symbol="XAUUSD", side="buy", volume=1, price=100, time=1000, sl=sl)
    apply_sync(conn, SyncIn(account=ACC, positions=[pos(90)]), 100)
    apply_sync(conn, SyncIn(account=ACC, positions=[pos(90)]), 110)
    apply_sync(conn, SyncIn(account=ACC, positions=[pos(80)]), 120)
    apply_sync(conn, SyncIn(account=ACC, deals=[
        deal(1, 5, "buy", "in", 1, 100, 1000), deal(2, 5, "sell", "out", 1, 80, 2000, profit=-2000)]), 130)
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM events ORDER BY id")]
    assert kinds == ["first_sl", "first_tp", "sl_change"]
    assert conn.execute("SELECT COUNT(*) FROM open_positions").fetchone()[0] == 0
    t = trades_of(conn)[0]
    assert t["sl_initial"] == 90 and "sl_widened" in t["flags"]


def test_moving_stop_to_profit_is_not_flagged(conn):
    pos = lambda sl: PositionIn(id="5", symbol="XAUUSD", side="buy", volume=1, price=100, time=1000, sl=sl)
    apply_sync(conn, SyncIn(account=ACC, positions=[pos(90)]), 100)
    apply_sync(conn, SyncIn(account=ACC, positions=[pos(105)]), 110)
    apply_sync(conn, SyncIn(account=ACC, deals=[
        deal(1, 5, "buy", "in", 1, 100, 1000), deal(2, 5, "sell", "out", 1, 105, 2000, profit=500)]), 130)
    assert "sl_widened" not in trades_of(conn)[0]["flags"]


def test_revenge_and_size_up_after_a_loss(conn):
    apply_sync(conn, SyncIn(account=ACC, deals=[
        deal(1, 1, "buy", "in", 0.1, 100, 10000, sl=90), deal(2, 1, "sell", "out", 0.1, 95, 11000, profit=-50),
        deal(3, 2, "buy", "in", 0.2, 96, 11120, sl=90), deal(4, 2, "sell", "out", 0.2, 100, 12000, profit=80)]))
    second = next(t for t in trades_of(conn) if t["position_id"] == "2")
    assert {"revenge", "size_up"} <= set(second["flags"])


def test_jalali_conversion():
    assert analytics.to_jalali(2026, 11, 3) == (1405, 8, 12)
    assert analytics.to_jalali(2025, 3, 21) == (1404, 1, 1)


def test_alerts_for_daily_limit_streak_cooldown_and_missing_stop(conn):
    now = int(time.time())
    base = now - 600 + 7200
    legs = []
    for i in range(3):
        legs += [deal(10 * i + 1, i + 1, "buy", "in", 1, 100, base - 300 + i, sl=90),
                 deal(10 * i + 2, i + 1, "sell", "out", 1, 95, base + i, profit=-100)]
    p = PositionIn(id="9", symbol="US30", side="buy", volume=1, price=1, time=base)
    apply_sync(conn, SyncIn(account=ACC, deals=legs, positions=[p]))
    rules = {**RULES, "daily_loss_limit": 250, "max_trades_per_day": 3}
    positions = conn.execute("SELECT * FROM open_positions").fetchall()
    tz = ZoneInfo("Asia/Tehran")
    ids = [a[0].split("-2")[0] for a in analytics.build_alerts(trades_of(conn), positions, rules, tz, now)]
    assert {"daily-loss", "max-trades", "loss-streak", "no-sl-9"} <= set(ids)
    assert any(i.startswith("cooldown") for i in ids)


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "a.db"))


def body(**kw):
    return {"account": {"login": "1", "server": "S", "currency": "USD", "gmt_offset": 0}, **kw}


def test_expert_needs_the_token(client):
    assert client.post("/api/ea/sync", json=body()).status_code == 401
    token = client.get("/api/settings").json()["token"]
    res = client.post("/api/ea/sync", json=body(), headers={"X-Journal-Token": token})
    assert res.status_code == 200 and res.text.startswith("OK\nCURSOR|0")


def test_foreign_host_is_rejected(client):
    assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 400


def test_settings_reject_non_json_and_bad_input(client):
    assert client.put("/api/settings", content="{}", headers={"content-type": "text/plain"}).status_code == 415
    assert client.put("/api/settings", json={"theme": {"accent": "red"}}).status_code == 422
    assert client.put("/api/settings", json={"timezone": "Mars/Base"}).status_code == 422
    assert client.put("/api/settings", json={"theme": {"preset": "shab", "accent": "#112233"}}).status_code == 200
    assert client.get("/api/settings").json()["theme"]["accent"] == "#112233"


def test_full_flow_through_the_api(client):
    token = client.get("/api/settings").json()["token"]
    deals = [{"id": "1", "position": "7", "symbol": "XAUUSD", "type": "buy", "entry": "in", "volume": 1, "price": 100, "sl": 90, "time": 1000},
             {"id": "2", "position": "7", "symbol": "XAUUSD", "type": "sell", "entry": "out", "volume": 1, "price": 110, "profit": 1000, "time": 2000}]
    client.post("/api/ea/sync", json=body(deals=deals), headers={"X-Journal-Token": token})
    assert client.get("/api/overview").json()["summary"]["net"] == 1000
    detail = client.get("/api/trades/S:1/7").json()
    assert "XAUUSD" in detail["story"] and len(detail["timeline"]) == 2
    assert client.put("/api/notes/S:1/7", json={"note": "خوب", "rating": 5}).status_code == 200
    assert client.get("/api/trades/S:1/7").json()["note"]["rating"] == 5
    assert "XAUUSD" in client.get("/api/export.csv").text


# --- news and fundamentals -------------------------------------------------
from app import ai, feeds, markets  # noqa: E402

FF = b'[{"title":"CPI m/m","country":"USD","date":"2026-11-10T08:30:00-05:00","impact":"High","forecast":"0.3%","previous":"0.2%"},' \
     b'{"title":"Bank Holiday","country":"JPY","date":"2026-11-10T00:00:00-05:00","impact":"Holiday","forecast":"","previous":""},' \
     b'{"title":"Bad","country":"?","date":"2026-11-10T00:00:00-05:00","impact":"Low"}]'
RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title> Gold rises as dollar slips </title><link> https://x.test/a </link><pubDate>Tue, 03 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Bad link</title><link>javascript:alert(1)</link></item>
<item><title>Dow Jones closes higher</title><link>https://x.test/b</link></item>
</channel></rss>"""
NOW = 1793700000


def test_forex_factory_rows_are_normalised():
    rows = feeds.parse_forex_factory(FF)
    assert len(rows) == 2
    assert rows[0]["impact"] == "high" and rows[0]["currency"] == "USD"
    assert rows[1]["forecast"] is None


def test_rss_keeps_only_web_links_and_tags_markets(conn):
    rows = feeds.parse_rss(RSS, NOW)
    assert [r["link"] for r in rows] == ["https://x.test/a", "https://x.test/b"]
    feeds.store_news(conn, "t", rows, NOW)
    tags = dict(conn.execute("SELECT title, markets FROM news_items").fetchall())
    assert "XAUUSD" in tags["Gold rises as dollar slips"]
    assert "US30" in tags["Dow Jones closes higher"]


def test_rss_with_entity_declaration_is_refused():
    with pytest.raises(ValueError):
        feeds.parse_rss(b'<!DOCTYPE x [<!ENTITY a "b">]><rss/>', NOW)


def test_one_broken_source_does_not_stop_the_others(conn):
    def fetcher(url, proxy):
        if "federalreserve" in url:
            raise OSError("blocked")
        return RSS
    feeds.refresh_news(conn, fetcher, NOW)
    status = {r["name"]: r for r in conn.execute("SELECT * FROM source_status")}
    assert status["فدرال رزرو"]["error"] == "blocked" and status["فدرال رزرو"]["last_ok"] is None
    assert status["طلا"]["last_ok"] == NOW
    assert conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0] == 2


@pytest.mark.parametrize("text,value", [("0.3%", 0.3), ("175K", 175000), ("1.2B", 1.2e9), ("-0.1%", -0.1), ("1,250", 1250), ("", None), ("n/a", None), (None, None)])
def test_parse_figure(text, value):
    assert markets.parse_figure(text) == value


def event(title, actual, forecast="0.3%", currency="USD"):
    return {"title": title, "actual": actual, "forecast": forecast, "currency": currency, "code": ""}


def test_hot_inflation_is_usually_bad_for_gold_and_dow():
    e = event("CPI m/m", "0.5%")
    assert markets.event_effect(e, "XAUUSD") == "down" and markets.event_effect(e, "US30") == "down"
    assert markets.event_effect(e, "EURUSD") == "down"


def test_soft_inflation_flips_and_inline_has_no_direction():
    assert markets.event_effect(event("CPI m/m", "0.1%"), "XAUUSD") == "up"
    assert markets.event_effect(event("CPI m/m", "0.3%"), "XAUUSD") is None


def test_higher_unemployment_supports_gold():
    assert markets.event_effect(event("Unemployment Rate", "4.4%", "4.2%"), "XAUUSD") == "up"


def test_unreleased_event_has_no_direction():
    assert markets.event_effect(event("CPI m/m", None), "XAUUSD") is None


def test_symbol_names_map_to_currencies():
    assert markets.currencies_for_symbol("XAUUSD.m") == ["USD"]
    assert markets.currencies_for_symbol("GOLD") == ["USD"]
    assert markets.currencies_for_symbol("US30Cash") == ["USD"]
    assert markets.currencies_for_symbol("EURJPY") == ["EUR", "JPY"]


def test_mt5_calendar_replaces_the_feed_for_the_same_span_and_fills_actual(conn):
    feeds.store_calendar(conn, [{"id": "ff:1", "time_utc": 100000 - 7200, "currency": "USD", "title": "CPI m/m", "impact": "high", "forecast": "0.3%", "previous": None}], NOW)
    msg = SyncIn(account=ACC, calendar=[{"id": "5", "time": 100000, "currency": "USD", "title": "CPI", "code": "cpi-mm", "impact": "high", "forecast": 0.3, "actual": 0.5}])
    apply_sync(conn, msg, NOW)
    rows = markets.load_events(conn, 0, 10**7)
    assert len(rows) == 1 and rows[0]["source"] == "mt5" and rows[0]["actual"] == "0.5"


def test_trade_near_high_impact_news_is_flagged():
    trades = [{"symbol": "XAUUSD", "open_time": 1000, "flags": []}, {"symbol": "XAUUSD", "open_time": 9000, "flags": []}]
    markets.flag_news_trades(trades, [{"impact": "high", "currency": "USD", "time_utc": 1300}])
    assert trades[0]["flags"] == ["news_trade"] and trades[1]["flags"] == []


def test_chart_alert_before_high_impact_news(conn):
    feeds.store_calendar(conn, [{"id": "ff:2", "time_utc": NOW + 600, "currency": "USD", "title": "CPI m/m", "impact": "high", "forecast": None, "previous": None}], NOW)
    found = markets.news_alerts(conn, {"news_alert_minutes": 30}, ["XAUUSD"], NOW)
    assert found and "10 min" in found[0][2]
    assert markets.news_alerts(conn, {"news_alert_minutes": 30}, ["XAUUSD"], NOW + 3600) == []
    assert markets.news_alerts(conn, {"news_alert_minutes": 0}, ["XAUUSD"], NOW) == []


class FakeOpener:
    def __init__(self, reply):
        self.reply, self.request = reply, None

    def open(self, request, timeout=0):
        import io
        self.request = request
        return io.BytesIO(self.reply)


AI = {"format": "openai", "base_url": "https://ai.test/v1", "model": "m", "api_key": "k", "auto_every": 0}


def test_openai_style_call():
    op = FakeOpener(b'{"choices":[{"message":{"content":" hi "}}]}')
    assert ai.call_model(AI, "s", "u", opener=op) == "hi"
    assert op.request.full_url == "https://ai.test/v1/chat/completions"
    assert op.request.get_header("Authorization") == "Bearer k"


def test_anthropic_style_call():
    op = FakeOpener(b'{"content":[{"type":"text","text":"sa"},{"type":"text","text":"lam"}]}')
    cfg = {**AI, "format": "anthropic", "base_url": "https://api.anthropic.com"}
    assert ai.call_model(cfg, "s", "u", opener=op) == "salam"
    assert op.request.full_url == "https://api.anthropic.com/v1/messages"


def test_unexpected_ai_reply_is_a_clear_error():
    with pytest.raises(ai.AiError):
        ai.call_model(AI, "s", "u", opener=FakeOpener(b'{"foo":1}'))


def test_coach_sends_no_account_identity_and_uses_previous_report(conn):
    db.put_setting(conn, "ai", AI)
    legs = []
    for i in range(12):
        legs += [deal(100 + 2 * i, i, "buy", "in", 1, 100, 10000 + 9000 * i, sl=90),
                 deal(101 + 2 * i, i, "sell", "out", 1, 110, 12000 + 9000 * i, profit=100)]
    secret = AccountIn(login="SECRET-LOGIN", server="SECRET-SERVER", name="SECRET-NAME", currency="USD", gmt_offset=0)
    apply_sync(conn, SyncIn(account=secret, deals=legs))
    trades = trades_of(conn)
    overview = analytics.build_overview(trades, UTC, "USD")
    op = FakeOpener(b'{"choices":[{"message":{"content":"## first"}}]}')
    ai.run_coach(conn, overview, trades, {}, opener=op)
    sent = op.request.data.decode()
    assert "SECRET" not in sent
    ai.run_coach(conn, overview, trades, {}, opener=op)
    assert "## first" in json.loads(op.request.data)["messages"][1]["content"]
    assert len(ai.latest(conn, "coach", limit=5)) == 2


def test_coach_needs_enough_trades(conn):
    db.put_setting(conn, "ai", AI)
    with pytest.raises(ai.AiError):
        ai.run_coach(conn, analytics.build_overview([], UTC, ""), [], {}, opener=FakeOpener(b"{}"))


def test_api_key_never_leaves_the_server_and_survives_a_partial_save(client):
    assert client.put("/api/settings", json={"ai": {"format": "openai", "base_url": "https://a.test/v1", "model": "m", "api_key": "topsecret"}}).status_code == 200
    data = client.get("/api/settings")
    assert "topsecret" not in data.text and data.json()["ai"]["has_key"] is True
    client.put("/api/settings", json={"ai": {"format": "openai", "base_url": "https://b.test/v1", "model": "m"}})
    assert client.get("/api/settings").json()["ai"]["has_key"] is True


def test_news_page_works_without_ai_or_data(client):
    data = client.get("/api/news/XAUUSD").json()
    assert data["ai_ready"] is False and data["lean"] == "هنوز داده کافی نیست"
    assert client.get("/api/news/NOPE").status_code == 404
    assert client.post("/api/coach", json={}).status_code == 409


def test_fetch_builds_an_https_opener_with_and_without_proxy():
    assert feeds.build_opener() is not None
    assert feeds.build_opener("http://127.0.0.1:10809") is not None


def test_platform_is_reported_for_the_connect_page(client):
    assert client.get("/api/settings").json()["platform"]


def test_simultaneous_requests_never_fail(client):
    import threading
    token = client.get("/api/settings").json()["token"]
    failures = []

    def hit(path, method="get", **kw):
        for _ in range(40):
            res = getattr(client, method)(path, **kw)
            if res.status_code != 200:
                failures.append((path, res.status_code))

    jobs = [threading.Thread(target=hit, args=("/api/overview",)), threading.Thread(target=hit, args=("/api/status",)),
            threading.Thread(target=hit, args=("/api/ea/sync", "post"), kwargs={"json": body(), "headers": {"X-Journal-Token": token}})]
    [j.start() for j in jobs]
    [j.join() for j in jobs]
    assert failures == []


# --- desktop shortcut ------------------------------------------------------
import launcher  # noqa: E402


@pytest.fixture
def steps(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(launcher, "LOG", tmp_path / "data" / "launcher.log")
    monkeypatch.setattr(launcher, "update", lambda: calls.append("update"))
    monkeypatch.setattr(launcher, "ensure_environment", lambda: calls.append("env"))
    monkeypatch.setattr(launcher, "stop_server", lambda: calls.append("stop"))
    monkeypatch.setattr(launcher, "start_server", lambda: calls.append("start"))
    monkeypatch.setattr(launcher, "wait_until_ready", lambda: True)
    monkeypatch.setattr(launcher, "current_commit", lambda: "new")
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: calls.append(url))
    return calls


def test_starts_server_when_none_is_running(steps, monkeypatch):
    monkeypatch.setattr(launcher, "server_state", lambda: None)
    assert launcher.main() == 0
    assert steps == ["update", "env", "start", launcher.URL]


def test_up_to_date_server_is_left_running(steps, monkeypatch):
    monkeypatch.setattr(launcher, "server_state", lambda: {"commit": "new"})
    launcher.main()
    assert steps == ["update", "env", launcher.URL]


def test_old_server_restarts_after_an_update(steps, monkeypatch):
    monkeypatch.setattr(launcher, "server_state", lambda: {"commit": "old"})
    launcher.main()
    assert steps == ["update", "env", "stop", "start", launcher.URL]


def test_failed_update_still_opens_the_journal(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "LOG", tmp_path / "data" / "launcher.log")
    monkeypatch.setattr(launcher, "git", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    launcher.update()
    assert "offline" in launcher.LOG.read_text() or "skipped" in launcher.LOG.read_text()


def test_shutdown_needs_the_token(client):
    assert client.post("/api/shutdown", json={}).status_code == 401
    assert "commit" in client.get("/api/version").json()


def test_server_with_unknown_commit_is_restarted_after_update(steps, monkeypatch):
    monkeypatch.setattr(launcher, "server_state", lambda: {"commit": ""})
    launcher.main()
    assert "stop" in steps and "start" in steps


def test_git_runs_natively_on_apple_silicon(monkeypatch):
    from app import gitinfo
    monkeypatch.setattr(gitinfo.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(gitinfo.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "1\n"})())
    assert gitinfo.git_command() == ["/usr/bin/arch", "-arm64", "git"]
    monkeypatch.setattr(gitinfo.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "\n"})())
    assert gitinfo.git_command() == ["git"]


def test_head_commit_reads_loose_packed_and_detached(tmp_path):
    from app import gitinfo
    git_dir = tmp_path / ".git"
    (git_dir / "refs/heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    (git_dir / "packed-refs").write_text("# pack\nabc123 refs/heads/main\n")
    assert gitinfo.head_commit(tmp_path) == "abc123"
    (git_dir / "refs/heads/main").write_text("def456\n")
    assert gitinfo.head_commit(tmp_path) == "def456"
    (git_dir / "HEAD").write_text("fff999\n")
    assert gitinfo.head_commit(tmp_path) == "fff999"
    assert gitinfo.head_commit(tmp_path / "missing") == ""
