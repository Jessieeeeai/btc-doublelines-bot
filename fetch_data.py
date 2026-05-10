"""
通过 Coinglass v4 API 拉取 BTC 1h K线 (近 1 年, 约 8760 根, 自动分页)
API key 从环境变量 COINGLASS_API_KEY 或 .env 读取, 不要写死!
"""
import os
import sys
import time
import json
import urllib.request
import urllib.parse
import urllib.error
import csv
from datetime import datetime

SYMBOLS = ["BTCUSDT"]        # 只跑BTC
EXCHANGE = "Binance"
INTERVAL = "1h"
DAYS = 1095                   # 近3年 (3年×365×24h ≈ 26,280 根, 自动分页)
PAGE_LIMIT = 1000             # Coinglass 单页上限

API_BASE = "https://open-api-v4.coinglass.com"
ENDPOINT = "/api/futures/price/history"

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(OUT_DIR, exist_ok=True)


def _http_get(url: str, api_key: str):
    req = urllib.request.Request(url, headers={
        "CG-API-KEY": api_key,
        "accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _normalize_items(raw):
    """兼容多种返回字段命名 —— 返回标准化的 dict 列表 (按 ts 升序)。"""
    if isinstance(raw, dict):
        items = raw.get("data") or raw.get("result") or []
    else:
        items = raw or []
    rows = []
    for it in items:
        if isinstance(it, dict):
            ts = int(it.get("time") or it.get("t") or it.get("timestamp") or 0)
            o = float(it.get("open") or it.get("o") or 0)
            h = float(it.get("high") or it.get("h") or 0)
            l = float(it.get("low") or it.get("l") or 0)
            c = float(it.get("close") or it.get("c") or 0)
            v = float(it.get("volume_usd") or it.get("volume") or it.get("v") or 0)
        else:
            ts = int(it[0]); o = float(it[1]); h = float(it[2])
            l = float(it[3]); c = float(it[4])
            v = float(it[5]) if len(it) > 5 else 0
        if ts > 1e12:
            ts //= 1000
        rows.append({"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})
    rows.sort(key=lambda r: r["ts"])
    return rows


def fetch_paginated(symbol: str, api_key: str):
    """分页拉取一年的 1h 数据。"""
    interval_sec = 3600  # 1h
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - DAYS * 86400 * 1000

    all_rows = []
    cursor = start_ms

    while cursor < end_ms:
        # 单页能覆盖 cursor + PAGE_LIMIT * interval 这么多时间
        page_end = min(end_ms, cursor + PAGE_LIMIT * interval_sec * 1000)
        params = {
            "exchange": EXCHANGE,
            "symbol": symbol,
            "interval": INTERVAL,
            "limit": PAGE_LIMIT,
            "start_time": cursor,
            "end_time": page_end,
        }
        url = f"{API_BASE}{ENDPOINT}?{urllib.parse.urlencode(params)}"
        try:
            raw = _http_get(url, api_key)
        except urllib.error.HTTPError as e:
            body = ""
            try: body = e.read().decode()
            except Exception: pass
            print(f"    HTTP {e.code} at {datetime.utcfromtimestamp(cursor/1000)}: {body[:200]}")
            break

        rows = _normalize_items(raw)
        if not rows:
            # 没数据了, 跳到下一页继续 (避免死循环)
            cursor = page_end + 1
            continue

        all_rows.extend(rows)
        last_ts_ms = rows[-1]["ts"] * 1000
        if last_ts_ms <= cursor:
            cursor = page_end + 1  # 防卡死
        else:
            cursor = last_ts_ms + interval_sec * 1000

        print(f"    page got {len(rows)} bars, cursor -> {datetime.utcfromtimestamp(cursor/1000)}")
        time.sleep(0.25)

    # 去重 (按 ts)
    seen = set()
    dedup = []
    for r in all_rows:
        if r["ts"] in seen:
            continue
        seen.add(r["ts"])
        dedup.append(r)
    dedup.sort(key=lambda r: r["ts"])
    return dedup


def save_csv(symbol: str, rows):
    path = os.path.join(OUT_DIR, f"{symbol}_{INTERVAL}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for r in rows:
            date = datetime.utcfromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M")
            w.writerow([date, r["open"], r["high"], r["low"], r["close"], r["volume"]])
    return path


def _load_env_key():
    api_key = os.environ.get("COINGLASS_API_KEY")
    if api_key:
        return api_key
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("COINGLASS_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def main():
    api_key = _load_env_key()
    if not api_key:
        print("ERROR: 没有找到 COINGLASS_API_KEY")
        print("  方法1: export COINGLASS_API_KEY='你的key' && python3 fetch_data.py")
        print("  方法2: 在本目录建 .env 文件, 写入: COINGLASS_API_KEY=你的key")
        sys.exit(1)

    print(f"Fetching {len(SYMBOLS)} symbol(s) {INTERVAL} from Coinglass, last {DAYS} days...")
    for sym in SYMBOLS:
        print(f"  {sym}:")
        try:
            rows = fetch_paginated(sym, api_key)
            if not rows:
                print(f"    返回空, 检查 API key 或 endpoint")
                continue
            path = save_csv(sym, rows)
            print(f"    OK: {len(rows)} bars -> {path}")
        except Exception as e:
            print(f"    FAILED ({type(e).__name__}: {e})")
    print("Done.")


if __name__ == "__main__":
    main()
