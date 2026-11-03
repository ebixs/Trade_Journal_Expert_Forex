"""Plays the role of the expert over HTTP, to test the journal without MetaTrader."""
import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
token = json.load(urllib.request.urlopen(f"{BASE}/api/settings"))["token"]


def send(positions=(), deals=()):
    now = int(time.time())
    body = {"account": {"login": "777", "server": "Sim-Live", "broker": "Sim", "currency": "USD",
                        "platform": "MT5", "balance": 5000, "equity": 5000, "gmt_offset": 7200},
            "positions": list(positions), "deals": list(deals)}
    req = urllib.request.Request(f"{BASE}/api/ea/sync", json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Journal-Token": token})
    return urllib.request.urlopen(req).read().decode()


broker = int(time.time()) + 7200
pos = {"id": "42", "symbol": "XAUUSD", "side": "buy", "volume": 0.1, "price": 2650, "time": broker - 900, "sl": 0, "tp": 2670}
print(send([pos], [{"id": "4201", "position": "42", "symbol": "XAUUSD", "type": "buy", "entry": "in", "volume": 0.1, "price": 2650, "tp": 2670, "time": broker - 900}]))
print(send([{**pos, "sl": 2640}]))
print(send([{**pos, "sl": 2645}]))
print(send([], [{"id": "4202", "position": "42", "symbol": "XAUUSD", "type": "sell", "entry": "out", "volume": 0.1, "price": 2645, "profit": -50, "commission": -0.7, "time": broker, "mfe": 2656, "mae": 2644}]))
