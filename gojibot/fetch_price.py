#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格与粒度补充 v4：
    python3 fetch_price.py
1) Coinbase 公共API拉 2 年 BTC-USD 1h K线（无需key，美区畅通）；失败则 CryptoCompare
2) CoinGlass 再拉 4h 粒度的 OI/taker/订单簿/清算（1000根≈166天，扩展全条件窗口）
"""
import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
DATA_DIR = os.path.join(HERE, CFG.get("data_dir", "data"))
NOW_S = int(time.time())
START_S = NOW_S - CFG["lookback_days"] * 86400
CG_KEY = CFG["coinglass_api_key"]
CG_SLEEP = CFG.get("coinglass_rate_limit_sleep_sec", 2.2)
PAIR = f"{CFG['symbol']}USDT"
REPORT = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "actions": {}}


def get_json(url, headers=None, timeout=30, retries=3):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "gojibot/1.0"})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(5 * (i + 1)); continue
            try:
                return {"_http_error": e.code, "_body": e.read().decode()[:200]}
            except Exception:
                return {"_http_error": e.code}
        except Exception as e:
            time.sleep(2 * (i + 1))
            err = str(e)
    return {"_http_error": "network", "_body": err}


def save_rows(name, rows, tkey="open_time_ms"):
    uniq = {int(r[tkey]): r for r in rows}
    rows = [uniq[k] for k in sorted(uniq)]
    with open(os.path.join(DATA_DIR, name), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return len(rows)


# ----------------------------------------------------------------------
def coinbase_klines():
    """Coinbase Exchange 公共 candles：300根/请求，1h。"""
    rows, cur = [], START_S
    fails = 0
    while cur < NOW_S and fails < 5:
        end = min(cur + 300 * 3600, NOW_S)
        iso = lambda s: datetime.fromtimestamp(s, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = ("https://api.exchange.coinbase.com/products/BTC-USD/candles?"
               + urllib.parse.urlencode({"granularity": 3600, "start": iso(cur), "end": iso(end)}))
        resp = get_json(url)
        if isinstance(resp, dict):
            fails += 1
            print(f"    coinbase err: {resp}"); time.sleep(2)
            if fails >= 5:
                return None, str(resp)[:150]
            continue
        fails = 0
        for k in resp:  # [time, low, high, open, close, volume]
            rows.append({"open_time_ms": int(k[0]) * 1000, "open": k[3], "high": k[2],
                         "low": k[1], "close": k[4], "volume": k[5], "taker_buy_base": None})
        cur = end
        done = (cur - START_S) / (NOW_S - START_S) * 100
        if int(done) % 10 == 0:
            print(f"    coinbase {done:.0f}%", end="\r")
        time.sleep(0.25)
    if rows:
        n = save_rows("price_1h.jsonl", rows)
        return n, "coinbase"
    return None, "empty"


def cryptocompare_klines():
    rows, to_ts = [], NOW_S
    while to_ts > START_S:
        url = ("https://min-api.cryptocompare.com/data/v2/histohour?"
               + urllib.parse.urlencode({"fsym": "BTC", "tsym": "USD", "limit": 2000, "toTs": to_ts}))
        resp = get_json(url)
        data = ((resp.get("Data") or {}).get("Data")) or []
        if resp.get("Response") != "Success" or not data:
            break
        for k in data:
            if k["time"] >= START_S:
                rows.append({"open_time_ms": k["time"] * 1000, "open": k["open"], "high": k["high"],
                             "low": k["low"], "close": k["close"],
                             "volume": k["volumefrom"], "taker_buy_base": None})
        to_ts = data[0]["time"] - 1
        time.sleep(0.3)
    if rows:
        n = save_rows("price_1h.jsonl", rows)
        return n, "cryptocompare"
    return None, "fail"


# ----------------------------------------------------------------------
def cg_fetch_4h(name, path, params):
    q = dict(params); q["limit"] = 1000
    url = f"https://open-api-v4.coinglass.com{path}?" + urllib.parse.urlencode(q)
    resp = get_json(url, headers={"CG-API-KEY": CG_KEY, "accept": "application/json"})
    time.sleep(CG_SLEEP)
    data = resp.get("data") or []
    if str(resp.get("code")) == "0" and data:
        n = save_rows(name, data, tkey="time")
        ts = [int(r["time"]) for r in data]
        span = f"{time.strftime('%Y-%m-%d', time.gmtime(min(ts)/1000))} → {time.strftime('%Y-%m-%d', time.gmtime(max(ts)/1000))}"
        REPORT["actions"][name] = {"rows": n, "span": span}
        print(f"  [OK ] {name}: {n} rows  {span}")
    else:
        REPORT["actions"][name] = {"rows": 0, "note": str(resp)[:150]}
        print(f"  [FAIL] {name}: {str(resp)[:120]}")


def main():
    print("== 价格K线（Coinbase → CryptoCompare）==")
    n, src = coinbase_klines()
    if not n:
        print(f"    coinbase失败({src})，改用 CryptoCompare")
        n, src = cryptocompare_klines()
    REPORT["actions"]["price_1h.jsonl"] = {"rows": n or 0, "source": src}
    print(f"  price: {n} rows via {src}")

    print("== CoinGlass 4h 粒度扩展 ==")
    coin = CFG["symbol"]
    cg_fetch_4h("cg_oi_4h.jsonl", "/api/futures/open-interest/aggregated-history",
                {"symbol": coin, "interval": "4h"})
    cg_fetch_4h("cg_taker_perp_4h.jsonl", "/api/futures/taker-buy-sell-volume/history",
                {"exchange": "Bybit", "symbol": PAIR, "interval": "4h"})
    cg_fetch_4h("cg_taker_spot_4h.jsonl", "/api/spot/taker-buy-sell-volume/history",
                {"exchange": "Bybit", "symbol": PAIR, "interval": "4h"})
    cg_fetch_4h("cg_orderbook_4h.jsonl", "/api/futures/orderbook/ask-bids-history",
                {"exchange": "Bybit", "symbol": PAIR, "interval": "4h", "range": "1"})
    cg_fetch_4h("cg_liquidation_4h.jsonl", "/api/futures/liquidation/history",
                {"exchange": "Bybit", "symbol": PAIR, "interval": "4h"})

    with open(os.path.join(DATA_DIR, "fetch_price_report.json"), "w") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2)
    print("\n完成。回到 Cowork 说「好了」。")


if __name__ == "__main__":
    main()
