#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 data.binance.vision（币安官方历史数据仓库，静态S3，通常不受451地区封锁影响）
下载 2 年完整数据：
  - 现货 1h K线（含 taker 买量 → 现货CVD）
  - U本位永续 1h K线（含 taker 买量 → 合约CVD）
  - 永续资金费率
  - 永续 metrics（含 OI，2023年起有）
用法：python3 fetch_binance_vision.py
"""
import csv
import io
import json
import os
import time
import urllib.request
import urllib.error
import zipfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
DATA_DIR = os.path.join(HERE, CFG.get("data_dir", "data"))
os.makedirs(DATA_DIR, exist_ok=True)

SYM = CFG["binance_perp_symbol"]
BASE = "https://data.binance.vision/data"
NOW = datetime.now(timezone.utc)
MONTHS = []
y, m = NOW.year, NOW.month
for _ in range(25):  # 25个月，覆盖2年+当月
    MONTHS.append(f"{y:04d}-{m:02d}")
    m -= 1
    if m == 0:
        y, m = y - 1, 12
MONTHS.reverse()

REPORT = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "datasets": {}}


def fetch_zip_csv(url):
    """下载zip并返回csv行列表；404返回None。"""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "gojibot"}), timeout=60) as r:
            buf = io.BytesIO(r.read())
        with zipfile.ZipFile(buf) as z:
            name = z.namelist()[0]
            text = z.read(name).decode("utf-8")
        rows = list(csv.reader(io.StringIO(text)))
        # 跳过表头行（新数据带表头）
        if rows and not rows[0][0].isdigit():
            rows = rows[1:]
        return rows
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception as e:
        print(f"    err {url.split('/')[-1]}: {e}")
        return None


def dl_klines(kind, out_name):
    """kind: 'spot' | 'um'"""
    prefix = f"{BASE}/spot/monthly/klines/{SYM}/1h" if kind == "spot" \
        else f"{BASE}/futures/um/monthly/klines/{SYM}/1h"
    out = []
    for mon in MONTHS:
        rows = fetch_zip_csv(f"{prefix}/{SYM}-1h-{mon}.zip")
        if rows is None:
            print(f"    {kind} {mon}: 404/skip")
            continue
        for k in rows:
            t = int(k[0])
            if t > 10**14:  # 2025+新档案微秒时间戳 → 毫秒
                t //= 1000
            out.append({"open_time_ms": t, "open": float(k[1]), "high": float(k[2]),
                        "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
                        "taker_buy_base": float(k[9])})
        print(f"    {kind} {mon}: +{len(rows)}")
        time.sleep(0.2)
    if out:
        uniq = {r["open_time_ms"]: r for r in out}
        out = [uniq[k] for k in sorted(uniq)]
        with open(os.path.join(DATA_DIR, out_name), "w") as f:
            for r in out:
                f.write(json.dumps(r) + "\n")
    REPORT["datasets"][out_name] = {"ok": bool(out), "rows": len(out)}
    print(f"  [{'OK' if out else 'FAIL'}] {out_name}: {len(out)} rows")


def dl_funding(out_name):
    out = []
    for mon in MONTHS:
        rows = fetch_zip_csv(f"{BASE}/futures/um/monthly/fundingRate/{SYM}/{SYM}-fundingRate-{mon}.zip")
        if rows is None:
            continue
        for k in rows:
            # calc_time, funding_interval_hours?, last_funding_rate —— 兼容新旧两种列序
            try:
                t = int(k[0]); rate = float(k[-1])
            except ValueError:
                continue
            if t > 10**14:
                t //= 1000
            out.append({"time_ms": t, "funding_rate": rate})
        time.sleep(0.2)
    if out:
        uniq = {r["time_ms"]: r for r in out}
        out = [uniq[k] for k in sorted(uniq)]
        with open(os.path.join(DATA_DIR, out_name), "w") as f:
            for r in out:
                f.write(json.dumps(r) + "\n")
    REPORT["datasets"][out_name] = {"ok": bool(out), "rows": len(out)}
    print(f"  [{'OK' if out else 'FAIL'}] {out_name}: {len(out)} rows")


def dl_metrics(out_name):
    """metrics 含 sum_open_interest（5m粒度，按日zip太大——用月度metrics如无则跳过）。"""
    out = []
    for mon in MONTHS:
        rows = fetch_zip_csv(f"{BASE}/futures/um/monthly/metrics/{SYM}/{SYM}-metrics-{mon}.zip")
        if rows is None:
            continue
        for k in rows:
            try:
                # create_time(str/ms), symbol, sum_open_interest, sum_open_interest_value, ...
                ts = k[0]
                if ts.isdigit():
                    t = int(ts)
                    if t > 10**14:
                        t //= 1000
                else:
                    t = int(datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
                            .replace(tzinfo=timezone.utc).timestamp() * 1000)
                oi_val = float(k[3])
            except (ValueError, IndexError):
                continue
            # 只保留整点，压体积
            if t % 3600_000 == 0:
                out.append({"time": t, "close": oi_val})
        print(f"    metrics {mon}: ok")
        time.sleep(0.2)
    if out:
        uniq = {r["time"]: r for r in out}
        out = [uniq[k] for k in sorted(uniq)]
        with open(os.path.join(DATA_DIR, out_name), "w") as f:
            for r in out:
                f.write(json.dumps(r) + "\n")
    REPORT["datasets"][out_name] = {"ok": bool(out), "rows": len(out)}
    print(f"  [{'OK' if out else 'FAIL'}] {out_name}: {len(out)} rows")


def main():
    print("== Binance Vision 历史档案 ==")
    print("  永续K线（含taker→合约CVD）")
    dl_klines("um", "perp_1h.jsonl")
    print("  现货K线（含taker→现货CVD）")
    dl_klines("spot", "spot_1h.jsonl")
    print("  资金费率")
    dl_funding("funding_binance.jsonl")
    print("  OI metrics")
    dl_metrics("cg_oi_binance.jsonl")

    with open(os.path.join(DATA_DIR, "fetch_vision_report.json"), "w") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2)
    print("\n完成。回到 Cowork 说「好了」。若第一个文件就404/超时，说明此域名也被封，我们就维持现有数据。")


if __name__ == "__main__":
    main()
