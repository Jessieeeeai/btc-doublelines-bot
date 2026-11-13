"""按 data_requests/request.txt 里列的币 (每行一个, 如 HYPEUSDT), 从 data.binance.vision 下载 U 本位永续 5m K线,
合成 {SYMBOL}_5m_full.csv.gz (列与研究用的 *_5m_full.csv 一致)。只在 GitHub Actions 里跑。"""
import csv, gzip, io, sys, urllib.request, urllib.error, zipfile
from datetime import datetime, timezone, timedelta

BASE = "https://data.binance.vision/data/futures/um"
COLS = ["ts", "open", "high", "low", "close", "volume", "quote_vol", "trades", "taker_buy_base", "taker_buy_quote"]


def grab(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "kline-fetch"}), timeout=90) as r:
            z = zipfile.ZipFile(io.BytesIO(r.read()))
        rows = list(csv.reader(io.StringIO(z.read(z.namelist()[0]).decode())))
        return rows[1:] if rows and not rows[0][0].isdigit() else rows
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def main():
    syms = [l.strip().upper() for l in open("data_requests/request.txt") if l.strip() and not l.startswith("#")]
    now = datetime.now(timezone.utc)
    for sym in syms:
        out = {}
        y, m = 2023, 5
        while (y, m) < (now.year, now.month):
            rows = grab(f"{BASE}/monthly/klines/{sym}/5m/{sym}-5m-{y:04d}-{m:02d}.zip")
            if rows:
                for r in rows:
                    out[int(r[0])] = [r[0], r[1], r[2], r[3], r[4], r[5], r[7], r[8], r[9], r[10]]
            m += 1
            if m == 13:
                y, m = y + 1, 1
        d = (now - timedelta(days=45)).replace(hour=0, minute=0, second=0, microsecond=0)
        while d.date() < now.date():
            if (d.year, d.month) >= (now.year, now.month) or not any(datetime.fromtimestamp(k / 1000, timezone.utc).date() == d.date() for k in list(out)[-9000:]):
                rows = grab(f"{BASE}/daily/klines/{sym}/5m/{sym}-5m-{d:%Y-%m-%d}.zip")
                if rows:
                    for r in rows:
                        out[int(r[0])] = [r[0], r[1], r[2], r[3], r[4], r[5], r[7], r[8], r[9], r[10]]
            d += timedelta(days=1)
        ks = sorted(out)
        if not ks:
            print(sym, "没有数据"); continue
        with gzip.open(f"{sym}_5m_full.csv.gz", "wt", newline="") as f:
            w = csv.writer(f); w.writerow(COLS)
            for k in ks:
                w.writerow(out[k])
        f0 = datetime.fromtimestamp(ks[0] / 1000, timezone.utc); f1 = datetime.fromtimestamp(ks[-1] / 1000, timezone.utc)
        print(sym, len(ks), "根", f0, "→", f1)


if __name__ == "__main__":
    main()
