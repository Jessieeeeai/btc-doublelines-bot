#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对账数据：拉最近800h的1h价格/现货taker/费率（与bot完全同源同参），存 data/week_*.jsonl
    python3 fetch_week.py
跑完回 Cowork 说「好了」。
"""
import json
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
DATA = os.path.join(HERE, "data")
CG_KEY = CFG["coinglass_api_key"]


def cg(path, **params):
    url = f"https://open-api-v4.coinglass.com{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"CG-API-KEY": CG_KEY, "accept": "application/json"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode())
            time.sleep(1.5)
            return resp
        except Exception:
            time.sleep(3)
    return {}


def save(name, resp):
    data = resp.get("data") or []
    if not data:
        print(f"  [FAIL] {name}: {str(resp)[:110]}")
        return
    with open(os.path.join(DATA, name), "w") as f:
        for d in sorted(data, key=lambda x: int(x["time"])):
            f.write(json.dumps(d) + "\n")
    ts = [int(d["time"]) for d in data]
    fmt = lambda t: time.strftime("%m-%d %H:%M", time.gmtime(t / 1000))
    print(f"  [OK] {name}: {len(data)}行 {fmt(min(ts))} → {fmt(max(ts))}")


def main():
    end = int(time.time() * 1000)
    for pair, suf in [("BTCUSDT", ""), ("ETHUSDT", "_eth")]:
        save(f"week_price{suf}.jsonl",
             cg("/api/futures/price/history", exchange="Binance", symbol=pair,
                interval="1h", limit=1000, start_time=end - 805 * 3600_000, end_time=end))
        save(f"week_taker{suf}.jsonl",
             cg("/api/spot/taker-buy-sell-volume/history",
                exchange="Bybit", symbol=pair, interval="1h", limit=800))
        save(f"week_funding{suf}.jsonl",
             cg("/api/futures/funding-rate/history",
                exchange="Bybit", symbol=pair, interval="8h", limit=100))
    print("\n完成，回到 Cowork 说「好了」。")


if __name__ == "__main__":
    main()
