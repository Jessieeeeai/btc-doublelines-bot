#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优化B：拉取 ETH 数据做准样本外验证（信号核参数一个不改）。
    python3 fetch_eth.py
产出：data/price_1h_eth.jsonl, cg_taker_spot_eth(.., _4h).jsonl, cg_funding_eth.jsonl
"""
import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
DATA = os.path.join(HERE, "data")
NOW_S = int(time.time())
START_S = NOW_S - 730 * 86400
CG_KEY = CFG["coinglass_api_key"]


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "gojibot"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(3)
    return None


def save(name, rows, tkey):
    uniq = {int(r[tkey]): r for r in rows}
    with open(os.path.join(DATA, name), "w") as f:
        for k in sorted(uniq):
            f.write(json.dumps(uniq[k]) + "\n")
    print(f"  [OK] {name}: {len(uniq)} rows")


def cg(path, **params):
    url = f"https://open-api-v4.coinglass.com{path}?" + urllib.parse.urlencode(params)
    resp = get_json(url, headers={"CG-API-KEY": CG_KEY, "accept": "application/json"})
    time.sleep(1.5)
    data = (resp or {}).get("data") or []
    if not data:
        print(f"  [FAIL] {path} {params.get('interval','')}: {str(resp)[:120]}")
    return data


def main():
    print("== Coinbase ETH-USD 1h × 2年 ==")
    rows, cur = [], START_S
    while cur < NOW_S:
        end = min(cur + 300 * 3600, NOW_S)
        iso = lambda s: datetime.fromtimestamp(s, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = get_json("https://api.exchange.coinbase.com/products/ETH-USD/candles?"
                        + urllib.parse.urlencode({"granularity": 3600, "start": iso(cur), "end": iso(end)}))
        if isinstance(data, list):
            for k in data:
                rows.append({"open_time_ms": int(k[0]) * 1000, "open": k[3], "high": k[2],
                             "low": k[1], "close": k[4], "volume": k[5]})
        cur = end
        time.sleep(0.25)
    save("price_1h_eth.jsonl", rows, "open_time_ms")

    print("== CoinGlass ETH ==")
    d = cg("/api/spot/taker-buy-sell-volume/history", exchange="Bybit", symbol="ETHUSDT", interval="1h", limit=1000)
    if d: save("cg_taker_spot_eth.jsonl", d, "time")
    d = cg("/api/spot/taker-buy-sell-volume/history", exchange="Bybit", symbol="ETHUSDT", interval="4h", limit=1000)
    if d: save("cg_taker_spot_eth_4h.jsonl", d, "time")
    d = cg("/api/futures/funding-rate/history", exchange="Bybit", symbol="ETHUSDT", interval="8h", limit=1000)
    if d: save("cg_funding_eth.jsonl", d, "time")
    print("\n完成，回到 Cowork 说「好了」。")


if __name__ == "__main__":
    main()
