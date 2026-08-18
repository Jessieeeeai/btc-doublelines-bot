#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初创套餐深度补拉：1h 数据回补到 180 天、费率到 360 天。
关键修正：startTime 必须落在套餐权限窗口内，否则 API 忽略参数只回最近1000根。
    python3 fetch_deep.py
"""
import json
import os
import time
import urllib.request
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
DATA = os.path.join(HERE, "data")
CG_KEY = CFG["coinglass_api_key"]
NOW_MS = int(time.time() * 1000)
D180 = NOW_MS - 178 * 86400_000  # 留2天余量
D360 = NOW_MS - 358 * 86400_000


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


def load(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p) if l.strip()]


def save(name, rows):
    uniq = {int(r["time"]): r for r in rows}
    with open(os.path.join(DATA, name), "w") as f:
        for k in sorted(uniq):
            f.write(json.dumps(uniq[k]) + "\n")
    return len(uniq)


def backfill(name, path, floor_ms, **params):
    rows = load(name)
    oldest = min((int(r["time"]) for r in rows), default=NOW_MS)
    pages = 0
    while oldest > floor_ms and pages < 20:
        resp = cg(path, limit=1000, startTime=floor_ms, endTime=oldest - 1, **params)
        code = str(resp.get("code"))
        data = resp.get("data") or []
        new = [d for d in data if int(d["time"]) < oldest]
        if code != "0" or not new:
            print(f"    {name}: 停止（code={code}, 新数据{len(new)}条）")
            break
        rows.extend(new)
        oldest = min(int(d["time"]) for d in new)
        pages += 1
        print(f"    {name}: 回补至 {time.strftime('%Y-%m-%d', time.gmtime(oldest/1000))}")
    n = save(name, rows) if rows else 0
    ts = [int(r["time"]) for r in rows] or [0]
    print(f"  [{name}] 共{n}行  {time.strftime('%Y-%m-%d', time.gmtime(min(ts)/1000))} → "
          f"{time.strftime('%Y-%m-%d', time.gmtime(max(ts)/1000))}")


def main():
    for coin, pair, suf in [("BTC", "BTCUSDT", ""), ("ETH", "ETHUSDT", "_eth")]:
        print(f"== {coin} 1h 数据回补至180天 ==")
        backfill(f"cg_taker_spot{suf}.jsonl", "/api/spot/taker-buy-sell-volume/history",
                 D180, exchange="Bybit", symbol=pair, interval="1h")
        if coin == "BTC":
            backfill("cg_taker_perp.jsonl", "/api/futures/taker-buy-sell-volume/history",
                     D180, exchange="Bybit", symbol=pair, interval="1h")
            backfill("cg_oi.jsonl", "/api/futures/open-interest/aggregated-history",
                     D180, symbol=coin, interval="1h")
            backfill("cg_orderbook.jsonl", "/api/futures/orderbook/ask-bids-history",
                     D180, exchange="Bybit", symbol=pair, interval="1h", range="1")
            backfill("cg_liquidation.jsonl", "/api/futures/liquidation/history",
                     D180, exchange="Bybit", symbol=pair, interval="1h")
        print(f"== {coin} 费率回补至360天 ==")
        backfill(f"cg_funding{suf}.jsonl", "/api/futures/funding-rate/history",
                 D360, exchange="Bybit", symbol=pair, interval="8h")
    print("\n完成，回到 Cowork 说「好了」。")


if __name__ == "__main__":
    main()
