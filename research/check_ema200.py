"""
拉最新 BTC 1h, 算 EMA-200, 查 5/14 期间哪些反转信号被 F6 挡了
直接在你 Mac 终端跑: python3 research/check_ema200.py
"""
import os, sys, time, json
import urllib.request, urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from signals import detect_signals
from backtest import _compute_ema, _compute_adx


def get_api_key():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    with open(env_path) as f:
        for line in f:
            if line.startswith("COINGLASS_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("没找到 COINGLASS_API_KEY")


def fetch_bars(n=400):
    api_key = get_api_key()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (n + 10) * 3600 * 1000
    params = {
        "exchange": "Binance", "symbol": "BTCUSDT",
        "interval": "1h", "limit": 1000,
        "start_time": start_ms, "end_time": end_ms,
    }
    url = f"https://open-api-v4.coinglass.com/api/futures/price/history?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"CG-API-KEY": api_key, "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = json.loads(resp.read().decode())
    items = raw.get("data") or raw.get("result") or []
    bars = []
    for it in items:
        if isinstance(it, dict):
            ts = int(it.get("time") or it.get("t") or it.get("timestamp"))
            o = float(it.get("open") or it.get("o"))
            h = float(it.get("high") or it.get("h"))
            l = float(it.get("low") or it.get("l"))
            c = float(it.get("close") or it.get("c"))
        else:
            ts, o, h, l, c = int(it[0]), float(it[1]), float(it[2]), float(it[3]), float(it[4])
        if ts > 1e12: ts //= 1000
        bars.append({
            "date": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M"),
            "ts": ts, "open": o, "high": h, "low": l, "close": c,
        })
    bars.sort(key=lambda x: x["ts"])
    return bars


def main():
    print("拉最近 400 根 BTC 1h K线...")
    bars = fetch_bars(400)
    print(f"  {bars[0]['date']} UTC  ~  {bars[-1]['date']} UTC\n")

    ema200 = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)

    # 找 5/14 整天的 K 线对应索引
    print("=== 5/14 当天 BTC 价格 vs EMA-200 ===")
    print(f"{'时间 UTC':<18} {'价格':>10} {'EMA-200':>10} {'差距%':>8} {'位置':>10}")
    print("-" * 75)
    for i, bar in enumerate(bars):
        if bar["date"].startswith("2026-05-14"):
            ev = ema200[i]
            if ev is None: continue
            diff_pct = (bar["close"] - ev) / ev * 100
            pos = "EMA 上方 ✓" if bar["close"] > ev else "EMA 下方 ✗"
            print(f"{bar['date']:<18} {bar['close']:>10.2f} {ev:>10.2f} {diff_pct:>+7.2f}% {pos:>12}")

    # 跑 T5 容差找信号
    print("\n=== 5/13~5/15 期间所有原始反转信号 (含 F6 判定) ===")
    sigs = detect_signals(bars, body_ratio_threshold=0.5, entanglement_tolerance=0.005)
    found_any = False
    for sig in sigs:
        idx = sig["index"]
        if not (bars[idx]["date"].startswith("2026-05-13") or
                bars[idx]["date"].startswith("2026-05-14") or
                bars[idx]["date"].startswith("2026-05-15")):
            continue
        found_any = True
        close = bars[idx]["close"]
        ev = ema200[idx]
        a = adx[idx]
        dist_pct = abs(close - ev) / ev * 100 if ev else 0

        # F6 判定逻辑
        f6_ok = True
        reasons = []
        if ev is None or ev <= 0:
            f6_ok = False
            reasons.append("EMA无效")
        else:
            if a > 25 and dist_pct/100 > 0.02:
                f6_ok = False
                reasons.append(f"强趋势期 (ADX={a:.0f}>25 且 |close-EMA|/EMA={dist_pct:.2f}%>2%)")
            if sig["direction"] == "long" and close < ev:
                f6_ok = False
                reasons.append(f"逆势 (多单但 close ${close:.0f} < EMA ${ev:.0f})")
            if sig["direction"] == "short" and close > ev:
                f6_ok = False
                reasons.append(f"逆势 (空单但 close ${close:.0f} > EMA ${ev:.0f})")

        mark = "✓ 通过" if f6_ok else "✗ 被挡"
        print(f"\n  [{bars[idx]['date']} UTC] {sig['direction']:<5} → {mark}")
        if not f6_ok:
            for r in reasons:
                print(f"       原因: {r}")
        print(f"       价格 ${close:.0f} | EMA-200 ${ev:.0f} | ADX {a:.1f}")
    if not found_any:
        print("(没找到 5/13~5/15 期间的原始信号)")


if __name__ == "__main__":
    main()
