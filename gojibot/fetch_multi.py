#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多粒度补拉：现货taker 2h/6h/12h（历史深度随间隔放大，12h可达初创上限360天）。
    python3 fetch_multi.py
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


def main():
    for pair, suf in [("BTCUSDT", ""), ("ETHUSDT", "_eth")]:
        for iv in ["2h", "6h", "12h"]:
            resp = cg("/api/spot/taker-buy-sell-volume/history",
                      exchange="Bybit", symbol=pair, interval=iv, limit=1000)
            data = resp.get("data") or []
            name = f"cg_taker_spot{suf}_{iv}.jsonl"
            if data:
                with open(os.path.join(DATA, name), "w") as f:
                    for d in sorted(data, key=lambda x: int(x["time"])):
                        f.write(json.dumps(d) + "\n")
                ts = [int(d["time"]) for d in data]
                print(f"  [OK] {name}: {len(data)}行 "
                      f"{time.strftime('%Y-%m-%d', time.gmtime(min(ts)/1000))} → "
                      f"{time.strftime('%Y-%m-%d', time.gmtime(max(ts)/1000))}")
            else:
                print(f"  [FAIL] {name}: {str(resp)[:120]}")
    print("\n完成，回到 Cowork 说「好了」。")


if __name__ == "__main__":
    main()
