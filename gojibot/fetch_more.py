#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补充下载 v3：在 fetch_data.py 之后运行——
    python3 fetch_more.py
1) 探测 CoinGlass 价格 OHLC 端点（替代被封锁的交易所K线）
2) 对所有数据集用 endTime 向回翻页，拉取更早历史（直到套餐上限或2年）
结果合并进 data/*.jsonl，报告写入 data/fetch_more_report.json
"""
import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
DATA_DIR = os.path.join(HERE, CFG.get("data_dir", "data"))
NOW_MS = int(time.time() * 1000)
START_MS = NOW_MS - CFG["lookback_days"] * 86400_000
CG_KEY = CFG["coinglass_api_key"]
CG_SLEEP = CFG.get("coinglass_rate_limit_sleep_sec", 2.2)
CG_BASE = "https://open-api-v4.coinglass.com"
REPORT = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "actions": {}}

PAIR = f"{CFG['symbol']}USDT"


def cg_get(path, params):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{CG_BASE}{path}?{q}",
                                 headers={"CG-API-KEY": CG_KEY, "accept": "application/json"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode("utf-8"))
            time.sleep(CG_SLEEP)
            return resp
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):
                time.sleep(10 * (i + 1)); continue
            time.sleep(CG_SLEEP)
            return {"_http_error": e.code}
        except Exception as e:
            time.sleep(3)
    return {"_http_error": "network"}


def load_rows(name):
    p = os.path.join(DATA_DIR, name)
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p) if l.strip()]


def save_rows(name, rows):
    rows = {int(r["time"]): r for r in rows}
    rows = [rows[k] for k in sorted(rows)]
    with open(os.path.join(DATA_DIR, name), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return len(rows)


def backfill(name, path, params):
    """向回翻页：endTime = 当前最老时间-1，直到 START_MS / 无更早数据 / 报错。"""
    rows = load_rows(name)
    oldest = min((int(r["time"]) for r in rows), default=NOW_MS)
    pages, stopped = 0, ""
    while oldest > START_MS:
        p = dict(params)
        p.update({"limit": 1000, "endTime": oldest - 1, "startTime": START_MS})
        resp = cg_get(path, p)
        code = str(resp.get("code", resp.get("_http_error")))
        data = resp.get("data") or []
        if code != "0":
            stopped = f"code={code} {str(resp.get('msg',''))[:80]}"; break
        new = [d for d in data if int(d["time"]) < oldest]
        if not new:
            stopped = "no older data (endTime 被忽略或已达套餐历史上限)"; break
        rows.extend(new)
        oldest = min(int(d["time"]) for d in new)
        pages += 1
        print(f"    {name}: +{len(new)} rows, back to "
              f"{time.strftime('%Y-%m-%d', time.gmtime(oldest/1000))}")
        if pages > 40:
            stopped = "page cap"; break
    n = save_rows(name, rows) if rows else 0
    span = ""
    if rows:
        ts = [int(r["time"]) for r in rows]
        span = f"{time.strftime('%Y-%m-%d', time.gmtime(min(ts)/1000))} → {time.strftime('%Y-%m-%d', time.gmtime(max(ts)/1000))}"
    REPORT["actions"][name] = {"rows": n, "span": span, "stopped": stopped}
    print(f"  [{name}] rows={n}  {span}  ({stopped})")


def probe_price(kind):
    """kind: 'perp'|'spot' → 找到可用的价格OHLC端点后回填。"""
    if kind == "perp":
        cands = [
            ("/api/futures/price/ohlc-history", {"exchange": "Bybit", "symbol": PAIR, "interval": "1h"}),
            ("/api/futures/price/ohlc-history", {"exchange": "Binance", "symbol": PAIR, "interval": "1h"}),
            ("/api/price/ohlc-history", {"exchange": "Bybit", "symbol": PAIR, "interval": "1h"}),
        ]
    else:
        cands = [
            ("/api/spot/price/ohlc-history", {"exchange": "Bybit", "symbol": PAIR, "interval": "1h"}),
            ("/api/spot/price/ohlc-history", {"exchange": "Binance", "symbol": PAIR, "interval": "1h"}),
        ]
    name = f"cg_price_{kind}.jsonl"
    for path, params in cands:
        p = dict(params); p["limit"] = 10
        resp = cg_get(path, p)
        code = str(resp.get("code", resp.get("_http_error")))
        n = len(resp.get("data") or [])
        print(f"    probe {path} {params['exchange']} -> code={code} n={n} {str(resp.get('msg',''))[:80]}")
        if code == "0" and n > 0:
            # 先拿最近1000
            p = dict(params); p["limit"] = 1000
            resp = cg_get(path, p)
            save_rows(name, resp.get("data") or [])
            backfill(name, path, params)
            return
    REPORT["actions"][name] = {"rows": 0, "span": "", "stopped": "no price endpoint available"}
    print(f"  [{name}] 无可用价格端点")


def main():
    print("== 价格 OHLC（CoinGlass）==")
    probe_price("perp")
    probe_price("spot")

    print("== 回填历史 ==")
    backfill("cg_funding.jsonl", "/api/futures/funding-rate/history",
             {"exchange": "Bybit", "symbol": PAIR, "interval": "8h"})
    backfill("cg_oi.jsonl", "/api/futures/open-interest/aggregated-history",
             {"symbol": CFG["symbol"], "interval": "1h"})
    backfill("cg_taker_perp.jsonl", "/api/futures/taker-buy-sell-volume/history",
             {"exchange": "Bybit", "symbol": PAIR, "interval": "1h"})
    backfill("cg_taker_spot.jsonl", "/api/spot/taker-buy-sell-volume/history",
             {"exchange": "Bybit", "symbol": PAIR, "interval": "1h"})
    backfill("cg_orderbook.jsonl", "/api/futures/orderbook/ask-bids-history",
             {"exchange": "Bybit", "symbol": PAIR, "interval": "1h", "range": "1"})
    backfill("cg_liquidation.jsonl", "/api/futures/liquidation/history",
             {"exchange": "Bybit", "symbol": PAIR, "interval": "1h"})

    with open(os.path.join(DATA_DIR, "fetch_more_report.json"), "w") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2)
    print("\n完成。回到 Cowork 说「好了」。")


if __name__ == "__main__":
    main()
