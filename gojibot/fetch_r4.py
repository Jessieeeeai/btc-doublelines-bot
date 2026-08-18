#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第四轮数据扩容：OI / 清算 / 盘口深度 / 合约taker / 多空持仓比，BTC+ETH 多粒度。
粗粒度换历史深度（12h×1000行≈500天，可覆盖 2025-08 上行段）。
    python3 fetch_r4.py
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
        return False
    with open(os.path.join(DATA, name), "w") as f:
        for d in sorted(data, key=lambda x: int(x["time"])):
            f.write(json.dumps(d) + "\n")
    ts = [int(d["time"]) for d in data]
    fmt = lambda t: time.strftime("%Y-%m-%d", time.gmtime(t / 1000))
    print(f"  [OK] {name}: {len(data)}行 {fmt(min(ts))} → {fmt(max(ts))}")
    return True


def main():
    jobs = []
    for coin, pair, suf in [("BTC", "BTCUSDT", ""), ("ETH", "ETHUSDT", "_eth")]:
        # BTC 已有 1h/4h 的四个旧源，只补缺口；ETH 全拉
        ivs_old_src = ["2h", "6h", "12h"] if coin == "BTC" else ["1h", "2h", "4h", "6h", "12h"]
        for iv in ivs_old_src:
            tag = "" if iv == "1h" else f"_{iv}"
            jobs += [
                (f"cg_oi{suf}{tag}.jsonl", "/api/futures/open-interest/aggregated-history",
                 {"symbol": coin, "interval": iv, "limit": 1000}),
                (f"cg_taker_perp{suf}{tag}.jsonl", "/api/futures/taker-buy-sell-volume/history",
                 {"exchange": "Bybit", "symbol": pair, "interval": iv, "limit": 1000}),
                (f"cg_orderbook{suf}{tag}.jsonl", "/api/futures/orderbook/ask-bids-history",
                 {"exchange": "Bybit", "symbol": pair, "interval": iv, "range": "1", "limit": 1000}),
                (f"cg_liquidation{suf}{tag}.jsonl", "/api/futures/liquidation/history",
                 {"exchange": "Bybit", "symbol": pair, "interval": iv, "limit": 1000}),
            ]
        # 多空比：新端点，全粒度试探
        for iv in ["1h", "4h", "6h", "12h"]:
            tag = "" if iv == "1h" else f"_{iv}"
            jobs += [
                (f"cg_lsr_global{suf}{tag}.jsonl",
                 "/api/futures/global-long-short-account-ratio/history",
                 {"exchange": "Bybit", "symbol": pair, "interval": iv, "limit": 1000}),
                (f"cg_lsr_top{suf}{tag}.jsonl",
                 "/api/futures/top-long-short-position-ratio/history",
                 {"exchange": "Bybit", "symbol": pair, "interval": iv, "limit": 1000}),
            ]

    ok = fail = 0
    for name, path, params in jobs:
        if save(name, cg(path, **params)):
            ok += 1
        else:
            fail += 1
    print(f"\n完成：{ok} OK / {fail} FAIL（FAIL多半是套餐不含该端点，正常）")
    print("回到 Cowork 说「好了」。")


if __name__ == "__main__":
    main()
