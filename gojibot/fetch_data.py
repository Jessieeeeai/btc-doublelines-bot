#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GojiBot 数据下载脚本 v2 —— 在你自己的电脑上运行：
    cd 交易/gojibot && python3 fetch_data.py

变化（v2）：
- K线源：Bybit → OKX → Binance 依次尝试（解决 Binance 451 地区封锁）
- 资金费率：Bybit 公共接口（与文档口径一致），CoinGlass 作为补充
- CoinGlass：每个候选端点的完整返回码/报错都写入 fetch_report.json
- 数据落盘为 JSONL（data/*.jsonl），更稳
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
os.makedirs(DATA_DIR, exist_ok=True)

NOW_MS = int(time.time() * 1000)
START_MS = NOW_MS - CFG["lookback_days"] * 86400_000
CG_KEY = CFG["coinglass_api_key"]
CG_SLEEP = CFG.get("coinglass_rate_limit_sleep_sec", 2.2)
REPORT = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "datasets": {}, "probes": {}}


def http_get_json(url, headers=None, retries=3, timeout=30):
    req = urllib.request.Request(url, headers=headers or {})
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")[:300]
            except Exception:
                pass
            if e.code in (418, 429):
                time.sleep(10 * (i + 1)); last = f"429 {body}"; continue
            return {"_http_error": e.code, "_body": body}
        except Exception as e:
            last = str(e); time.sleep(2 * (i + 1))
    return {"_http_error": "network", "_body": str(last)}


def save_jsonl(name, rows):
    path = os.path.join(DATA_DIR, name)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return path


def record(name, ok, rows=0, note=""):
    REPORT["datasets"][name] = {"ok": ok, "rows": rows, "note": str(note)[:300]}
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: rows={rows} {str(note)[:160]}")


# ======================================================================
# K线：Bybit → OKX → Binance
# ======================================================================
def klines_bybit(category, symbol, out_name):
    """Bybit v5，1h，窗口分页。无taker细分。"""
    rows, cur = [], START_MS
    step = 1000 * 3600_000
    while cur < NOW_MS:
        q = urllib.parse.urlencode({"category": category, "symbol": symbol,
                                    "interval": "60", "start": cur,
                                    "end": min(cur + step - 1, NOW_MS), "limit": 1000})
        resp = http_get_json(f"https://api.bybit.com/v5/market/kline?{q}")
        lst = (resp.get("result") or {}).get("list") or []
        if resp.get("retCode") != 0:
            return None, f"retCode={resp.get('retCode')} {resp.get('retMsg', resp)}"
        for k in sorted(lst, key=lambda x: int(x[0])):
            rows.append({"open_time_ms": int(k[0]), "open": float(k[1]), "high": float(k[2]),
                         "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
                         "taker_buy_base": None})
        cur += step
        time.sleep(0.12)
    if rows:
        save_jsonl(out_name, rows)
        return len(rows), "bybit"
    return None, "empty"


def klines_okx(inst, out_name):
    rows, before = [], NOW_MS
    while True:
        q = urllib.parse.urlencode({"instId": inst, "bar": "1H", "after": before, "limit": 100})
        resp = http_get_json(f"https://www.okx.com/api/v5/market/history-candles?{q}")
        lst = resp.get("data") or []
        if resp.get("code") not in ("0", 0) or not lst:
            break
        for k in lst:
            t = int(k[0])
            if t < START_MS:
                continue
            rows.append({"open_time_ms": t, "open": float(k[1]), "high": float(k[2]),
                         "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
                         "taker_buy_base": None})
        before = int(lst[-1][0])
        if before <= START_MS:
            break
        time.sleep(0.15)
    if rows:
        rows.sort(key=lambda r: r["open_time_ms"])
        save_jsonl(out_name, rows)
        return len(rows), "okx"
    return None, str(resp)[:200]


def klines_binance(base, symbol, out_name):
    rows, cur = [], START_MS
    while True:
        q = urllib.parse.urlencode({"symbol": symbol, "interval": "1h", "limit": 1000, "startTime": cur})
        resp = http_get_json(f"{base}?{q}")
        if isinstance(resp, dict):
            return None, str(resp)[:200]
        if not resp:
            break
        for k in resp:
            rows.append({"open_time_ms": k[0], "open": float(k[1]), "high": float(k[2]),
                         "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
                         "taker_buy_base": float(k[9])})
        cur = resp[-1][0] + 1
        if len(resp) < 1000 or cur >= NOW_MS:
            break
        time.sleep(0.15)
    if rows:
        save_jsonl(out_name, rows)
        return len(rows), "binance"
    return None, "empty"


def fetch_klines(kind, out_name):
    """kind: 'perp'|'spot'"""
    sym = CFG["binance_perp_symbol"] if kind == "perp" else CFG["binance_spot_symbol"]
    # Bybit
    n, note = klines_bybit("linear" if kind == "perp" else "spot", sym, out_name)
    if n:
        record(out_name, True, n, "source=bybit"); return
    print(f"    bybit fail: {note}")
    # OKX
    inst = "BTC-USDT-SWAP" if kind == "perp" else "BTC-USDT"
    n, note = klines_okx(inst, out_name)
    if n:
        record(out_name, True, n, "source=okx"); return
    print(f"    okx fail: {note}")
    # Binance
    base = ("https://fapi.binance.com/fapi/v1/klines" if kind == "perp"
            else "https://api.binance.com/api/v3/klines")
    n, note = klines_binance(base, sym, out_name)
    if n:
        record(out_name, True, n, "source=binance"); return
    record(out_name, False, 0, note)


def fetch_funding_bybit_public(out_name):
    """Bybit v5 资金费率历史（8h一条），窗口回退分页。"""
    rows, end = [], NOW_MS
    while end > START_MS:
        q = urllib.parse.urlencode({"category": "linear", "symbol": CFG["binance_perp_symbol"],
                                    "startTime": START_MS, "endTime": end, "limit": 200})
        resp = http_get_json(f"https://api.bybit.com/v5/market/funding/history?{q}")
        lst = (resp.get("result") or {}).get("list") or []
        if resp.get("retCode") != 0 or not lst:
            if not rows:
                record(out_name, False, 0, str(resp)[:200])
                return
            break
        for d in lst:
            rows.append({"time_ms": int(d["fundingRateTimestamp"]),
                         "funding_rate": float(d["fundingRate"])})
        end = min(int(d["fundingRateTimestamp"]) for d in lst) - 1
        time.sleep(0.15)
    rows.sort(key=lambda r: r["time_ms"])
    # 去重
    seen, ded = set(), []
    for r in rows:
        if r["time_ms"] not in seen:
            seen.add(r["time_ms"]); ded.append(r)
    save_jsonl(out_name, ded)
    record(out_name, True, len(ded), "source=bybit_public")


# ======================================================================
# CoinGlass v4：探测（记录全部返回）→ 命中后全量分页
# ======================================================================
CG_BASE = "https://open-api-v4.coinglass.com"


def cg_get(path, params):
    q = urllib.parse.urlencode(params)
    resp = http_get_json(f"{CG_BASE}{path}?{q}",
                         headers={"CG-API-KEY": CG_KEY, "accept": "application/json"})
    time.sleep(CG_SLEEP)
    return resp


def cg_probe_and_fetch(dataset, candidates):
    """candidates: [(path, params)]。探测：limit=10 不带时间参数。
    命中后：先试秒级 startTime，数据不对再试毫秒。全过程写入 REPORT['probes']。"""
    probes = []
    winner = None
    for path, params in candidates:
        p = dict(params); p["limit"] = 10
        resp = cg_get(path, p)
        code = str(resp.get("code", resp.get("_http_error")))
        msg = str(resp.get("msg", resp.get("_body", "")))[:200]
        n = len(resp.get("data") or []) if isinstance(resp.get("data"), list) else 0
        probes.append({"path": path, "params": params, "code": code, "msg": msg, "n": n})
        print(f"    probe {path} [{params.get('interval','')}] -> code={code} n={n} {msg[:80]}")
        if code == "0" and n > 0:
            winner = (path, params, resp["data"][0])
            break
    REPORT["probes"][dataset] = probes
    if not winner:
        record(f"{dataset}.jsonl", False, 0, "no candidate returned data")
        return

    path, params, sample = winner
    tkey = "time" if "time" in sample else ("t" if "t" in sample else list(sample.keys())[0])
    # 判断该端点时间单位（样本时间戳量级）
    ts = int(sample[tkey])
    unit_ms = ts > 10**12

    rows, cur = [], (START_MS if unit_ms else START_MS // 1000)
    end_all = NOW_MS if unit_ms else NOW_MS // 1000
    stall = 0
    while cur < end_all and stall < 3:
        p = dict(params); p.update({"limit": 1000, "startTime": cur, "endTime": end_all})
        resp = cg_get(path, p)
        data = resp.get("data") or []
        if str(resp.get("code")) != "0" or not data:
            stall += 1
            cur += (86400_000 * 30 if unit_ms else 86400 * 30)  # 跳一个月再试
            continue
        stall = 0
        for d in data:
            rows.append(d)
        last_t = int(data[-1].get(tkey, cur))
        if last_t <= cur:
            break
        cur = last_t + 1
        if len(data) < 50:
            break
    if rows:
        # 去重
        seen, ded = set(), []
        for r in rows:
            k = r.get(tkey)
            if k not in seen:
                seen.add(k); ded.append(r)
        save_jsonl(f"{dataset}.jsonl", ded)
        record(f"{dataset}.jsonl", True, len(ded), f"via {path} unit={'ms' if unit_ms else 's'}")
    else:
        record(f"{dataset}.jsonl", False, 0, f"probe ok but pagination empty via {path}")


def main():
    coin = CFG["symbol"]
    pair = f"{coin}USDT"
    fund_ex = CFG.get("funding_exchange", "Bybit")

    print("== K线（Bybit→OKX→Binance）==")
    fetch_klines("perp", "perp_1h.jsonl")
    fetch_klines("spot", "spot_1h.jsonl")

    print("== 资金费率（Bybit 公共）==")
    fetch_funding_bybit_public("funding_bybit_public.jsonl")

    print("== CoinGlass v4 ==")
    resp = cg_get("/api/futures/supported-coins", {})
    REPORT["coinglass_key_check"] = {"code": str(resp.get("code")), "msg": str(resp.get("msg", ""))[:120]}
    print(f"  key check: {REPORT['coinglass_key_check']}")

    cg_probe_and_fetch("cg_funding", [
        ("/api/futures/funding-rate/history", {"exchange": fund_ex, "symbol": pair, "interval": "8h"}),
        ("/api/futures/funding-rate/history", {"exchange": fund_ex, "symbol": pair, "interval": "1h"}),
        ("/api/futures/funding-rate/ohlc-history", {"exchange": fund_ex, "symbol": pair, "interval": "8h"}),
        ("/api/futures/funding-rate/ohlc-history", {"exchange": fund_ex, "symbol": pair, "interval": "1h"}),
        ("/api/futures/fundingRate/ohlc-history", {"exchange": fund_ex, "symbol": pair, "interval": "8h"}),
    ])

    cg_probe_and_fetch("cg_oi", [
        ("/api/futures/open-interest/aggregated-history", {"symbol": coin, "interval": "1h"}),
        ("/api/futures/open-interest/ohlc-aggregated-history", {"symbol": coin, "interval": "1h"}),
        ("/api/futures/open-interest/history", {"exchange": "Bybit", "symbol": pair, "interval": "1h"}),
        ("/api/futures/open-interest/ohlc-history", {"exchange": "Bybit", "symbol": pair, "interval": "1h"}),
        ("/api/futures/openInterest/ohlc-aggregated-history", {"symbol": coin, "interval": "1h"}),
    ])

    cg_probe_and_fetch("cg_taker_perp", [
        ("/api/futures/taker-buy-sell-volume/history", {"exchange": "Bybit", "symbol": pair, "interval": "1h"}),
        ("/api/futures/taker-buy-sell-volume/history", {"exchange": "Binance", "symbol": pair, "interval": "1h"}),
        ("/api/futures/aggregated-taker-buy-sell-volume/history", {"exchange_list": "Binance,Bybit,OKX", "symbol": coin, "interval": "1h"}),
        ("/api/futures/v2/taker-buy-sell-volume/history", {"exchange": "Bybit", "symbol": pair, "interval": "1h"}),
    ])

    cg_probe_and_fetch("cg_taker_spot", [
        ("/api/spot/taker-buy-sell-volume/history", {"exchange": "Bybit", "symbol": pair, "interval": "1h"}),
        ("/api/spot/taker-buy-sell-volume/history", {"exchange": "Binance", "symbol": pair, "interval": "1h"}),
        ("/api/spot/aggregated-taker-buy-sell-volume/history", {"exchange_list": "Binance,Bybit,OKX", "symbol": coin, "interval": "1h"}),
    ])

    cg_probe_and_fetch("cg_orderbook", [
        ("/api/futures/orderbook/ask-bids-history", {"exchange": "Bybit", "symbol": pair, "interval": "1h", "range": "1"}),
        ("/api/futures/orderbook/ask-bids-history", {"exchange": "Binance", "symbol": pair, "interval": "1h", "range": "1"}),
        ("/api/futures/orderbook/aggregated-ask-bids-history", {"exchange_list": "Binance,Bybit", "symbol": coin, "interval": "1h", "range": "1"}),
        ("/api/spot/orderbook/ask-bids-history", {"exchange": "Binance", "symbol": pair, "interval": "1h", "range": "1"}),
    ])

    cg_probe_and_fetch("cg_liquidation", [
        ("/api/futures/liquidation/history", {"exchange": "Bybit", "symbol": pair, "interval": "1h"}),
        ("/api/futures/liquidation/aggregated-history", {"exchange_list": "Binance,Bybit,OKX", "symbol": coin, "interval": "1h"}),
        ("/api/futures/liquidation/v2/history", {"exchange": "Bybit", "symbol": pair, "interval": "1h"}),
    ])

    with open(os.path.join(DATA_DIR, "fetch_report.json"), "w") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2)
    print("\n完成。回到 Cowork 说「数据好了」即可（即使部分 FAIL 也没关系，报告里有细节）。")


if __name__ == "__main__":
    main()
