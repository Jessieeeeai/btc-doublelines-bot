"""临时: 生成合成 BTCUSDT_1h 数据用于验证 pipeline。
真实数据由 fetch_data.py 从 Coinglass 拉取后会覆盖此文件。"""
import os
import csv
import random
from datetime import datetime, timedelta

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(OUT, exist_ok=True)

START = datetime(2025, 5, 10)
BARS = 8760  # 1 年 1h

random.seed(42)
price = 60000.0
rows = []
for d in range(BARS):
    dt = START + timedelta(hours=d)
    drift = random.gauss(0, price * 0.005)
    if random.random() < 0.05:
        drift *= 4
    o = price
    c = max(0.01, price + drift)
    h = max(o, c) * (1 + abs(random.gauss(0, 0.002)))
    l = min(o, c) * (1 - abs(random.gauss(0, 0.002)))
    rows.append([dt.strftime("%Y-%m-%d %H:%M"), round(o, 2), round(h, 2), round(l, 2), round(c, 2), 0])
    price = c

path = os.path.join(OUT, "BTCUSDT_1h.csv")
with open(path, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date", "open", "high", "low", "close", "volume"])
    w.writerows(rows)
print(f"Generated {len(rows)} bars -> {path}")
