"""
F6 å®æ¶ä¿¡å·æºå¨äºº â æ¯æ¬¡è¿è¡:
1) æææ° BTC 1h Kçº¿ (300 æ ¹è¶³å¤ ADX/EMA-200 è®¡ç®)
2) åºç¨ F6 ç­ç¥æ£æµä¿¡å·
3) è·è¸ªæ¯ä¸ªä¿¡å·ççå½å¨æ: waiting -> entered -> tp_hit/sl_hit/expired
4) ç¶æååæ¶æ¨é TG
5) 10 ä¸ªä¿¡å·å¨é¨å®æå,åææ¥

ç¨æ³: python3 signal_bot.py
ç¯å¢åé:
  COINGLASS_API_KEY  - æ°æ® API key
  TELEGRAM_BOT_TOKEN - TG bot token
  TELEGRAM_CHAT_ID   - æ¥æ¶æ¶æ¯ç chat_id
"""
import os
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta

from signals import detect_signals
from backtest import VariantConfig, _compute_ema, _compute_adx
from tg_notify import (send_message, msg_signal_formed, msg_entered,
                        msg_tp_hit, msg_sl_hit, msg_expired,
                        msg_invalidated_by_sl, msg_final_report)


# F6 ç­ç¥éç½® (ä¸ variants.py ç F6 ä¸è´)
CFG = VariantConfig(
    name="F6_live",
    body_ratio=0.5,
    r_multiple=2.0,
    sl_buffer_pct=0.02,
    entry_mode="breakout_confirm",
    entry_wait_bars=3,
    regime_mode="optimal",
    regime_adx_high=25,
    regime_ema_dist_trend=0.02,
)

MAX_SIGNALS = 10  # æ¶ 10 ä¸ªå°±åºææ¥
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
N_BARS = 720       # æå¤å°æ ¹ 1h Kçº¿ (>200 æè½ç® EMA-200)
COINGLASS_BASE = "https://open-api-v4.coinglass.com"


# ========== æ°æ®æå ==========

def fetch_btc_1h_bars(api_key: str, n: int = 300):
    """ææè¿ n æ ¹ BTC 1h Kçº¿"""
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (n + 5) * 3600 * 1000
    params = {
        "exchange": "Binance",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "limit": 1000,
        "start_time": start_ms,
        "end_time": end_ms,
    }
    url = f"{COINGLASS_BASE}/api/futures/price/history?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "CG-API-KEY": api_key,
        "accept": "application/json",
    })
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
        if ts > 1e12:
            ts //= 1000
        bars.append({
            "date": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M"),
            "ts": ts, "open": o, "high": h, "low": l, "close": c,
        })
    bars.sort(key=lambda x: x["ts"])
    return bars


# ========== ç¶æç®¡ç ==========

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"signals": [], "first_signal_date": None, "final_sent": False,
                "anchor_ts": None, "started": False}
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ========== ä¿¡å·æ£æµ & è·è¸ª ==========

def apply_f6_filter(bars, sig):
    """å¯¹åä¸ªä¿¡å·å¤å® F6 æ¯å¦æ¥å (regime + é¡ºå¿ EMA-200)"""
    idx = sig["index"]
    ema200 = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)
    close = bars[idx]["close"]
    ev = ema200[idx]
    dist = abs(close - ev) / ev if ev > 0 else 0
    # å¼ºè¶å¿æè·³è¿
    if adx[idx] > CFG.regime_adx_high and dist > CFG.regime_ema_dist_trend:
        return False
    # é¡ºå¿ EMA-200
    if sig["direction"] == "long" and close > ev:
        return True
    if sig["direction"] == "short" and close < ev:
        return True
    return False


def build_signal_record(bars, sig):
    """ä» raw signal æé è·è¸ªè®°å½"""
    direction = sig["direction"]
    # SL: B/C æå¼ Â± ç¼å²
    if direction == "long":
        extremity = min(sig["B_low"], sig["C_low"])
        sl = extremity * (1 - CFG.sl_buffer_pct)
        trigger = max(sig["B_close"], sig["C_close"])  # çªç ´ä¸æ²¿
    else:
        extremity = max(sig["B_high"], sig["C_high"])
        sl = extremity * (1 + CFG.sl_buffer_pct)
        trigger = min(sig["B_close"], sig["C_close"])  # è·ç ´ä¸æ²¿
    r = abs(trigger - sl)
    if direction == "long":
        tp = trigger + CFG.r_multiple * r
    else:
        tp = trigger - CFG.r_multiple * r

    sig_bar = bars[sig["index"]]
    expires_ts = sig_bar["ts"] + (CFG.entry_wait_bars + 1) * 3600  # ä¿¡å·Kçº¿+3h
    expires_str = datetime.utcfromtimestamp(expires_ts).strftime("%Y-%m-%d %H:%M UTC")

    pattern = ("çæ¶¨åè½¬ (æ¥è·ååºé¨ç¼ ç»)" if direction == "long"
               else "çè·åè½¬ (æ¥æ¶¨åé¡¶é¨ç¼ ç»)")

    return {
        "signal_time": sig_bar["date"] + " UTC",
        "signal_ts": sig_bar["ts"],
        "direction": direction,
        "trigger_price": round(trigger, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "expires_at": expires_str,
        "expires_ts": expires_ts,
        "pattern_desc": pattern,
        "status": "waiting",
        "entry_price": None,
        "entry_time": None,
        "exit_price": None,
        "exit_time": None,
        "result_r": None,
    }


def detect_new_signals(bars, state):
    """æ«æ bars æ¾ F6 ä¿¡å·, è· state æ¯å¯¹æ¾æ°å¢ãåªè¦ anchor_ts ä¹åç"""
    anchor_ts = state.get("anchor_ts") or 0
    known_ts = {s["signal_ts"] for s in state["signals"]}
    raw_signals = detect_signals(bars, CFG.body_ratio)
    new = []
    for sig in raw_signals:
        sig_bar = bars[sig["index"]]
        if sig_bar["ts"] in known_ts:
            continue
        # éç¹ä¹åçä¿¡å·å¿½ç¥ (é¿åé¦æ¬¡é¨ç½²æ¶æåå²ä¿¡å·å¨æ¨ä¸é)
        if sig_bar["ts"] <= anchor_ts:
            continue
        # ä¿¡å· K çº¿å¿é¡»å·²æ¶ç
        if sig["index"] >= len(bars) - 1:
            continue
        if not apply_f6_filter(bars, sig):
            continue
        rec = build_signal_record(bars, sig)
        new.append(rec)
    return new


def update_signal_status(bars, sig_rec):
    """å¯¹ä¸ä¸ª waiting/entered ä¿¡å·, çåç»­ K çº¿æ¨è¿å®çç¶æã"""
    sig_ts = sig_rec["signal_ts"]
    # æ¾ signal ä¹åç bars
    after = [b for b in bars if b["ts"] > sig_ts]
    if not after:
        return False  # è¿æ²¡ä¸ä¸æ ¹

    changed = False
    direction = sig_rec["direction"]
    trigger = sig_rec["trigger_price"]
    sl = sig_rec["sl"]
    tp = sig_rec["tp"]

    if sig_rec["status"] == "waiting":
        # å¨ expires_ts ä¹åç­çªç ´æ SL ååè§¦å
        for bar in after:
            if bar["ts"] > sig_rec["expires_ts"]:
                # çªå£è¿äº, ä½åº
                sig_rec["status"] = "expired"
                changed = True
                break
            if direction == "long":
                # åå: ä»·æ ¼è§¦å SL (æ²¡å¥åºå°±åææ)
                if bar["low"] <= sl:
                    sig_rec["status"] = "invalidated"
                    changed = True
                    break
                # çªç ´: ä»·æ ¼ä¸ç ´ trigger
                if bar["high"] >= trigger:
                    sig_rec["status"] = "entered"
                    sig_rec["entry_price"] = trigger
                    sig_rec["entry_time"] = bar["date"] + " UTC"
                    sig_rec["entry_ts"] = bar["ts"]
                    changed = True
                    break
            else:
                if bar["high"] >= sl:
                    sig_rec["status"] = "invalidated"
                    changed = True
                    break
                if bar["low"] <= trigger:
                    sig_rec["status"] = "entered"
                    sig_rec["entry_price"] = trigger
                    sig_rec["entry_time"] = bar["date"] + " UTC"
                    sig_rec["entry_ts"] = bar["ts"]
                    changed = True
                    break

    if sig_rec["status"] == "entered":
        entry_ts = sig_rec.get("entry_ts", sig_ts)
        for bar in after:
            if bar["ts"] <= entry_ts:
                continue
            # æ£æ¥ TP/SL (ä¿å®: åæ ¹ K çº¿åæ¶è§¦åæ SL)
            if direction == "long":
                if bar["low"] <= sl:
                    sig_rec["status"] = "sl_hit"
                    sig_rec["exit_price"] = sl
                    sig_rec["exit_time"] = bar["date"] + " UTC"
                    sig_rec["exit_ts"] = bar["ts"]
                    sig_rec["result_r"] = -1.0
                    changed = True
                    break
                if bar["high"] >= tp:
                    sig_rec["status"] = "tp_hit"
                    sig_rec["exit_price"] = tp
                    sig_rec["exit_time"] = bar["date"] + " UTC"
                    sig_rec["exit_ts"] = bar["ts"]
                    sig_rec["result_r"] = 2.0
                    changed = True
                    break
            else:
                if bar["high"] >= sl:
                    sig_rec["status"] = "sl_hit"
                    sig_rec["exit_price"] = sl
                    sig_rec["exit_time"] = bar["date"] + " UTC"
                    sig_rec["exit_ts"] = bar["ts"]
                    sig_rec["result_r"] = -1.0
                    changed = True
                    break
                if bar["low"] <= tp:
                    sig_rec["status"] = "tp_hit"
                    sig_rec["exit_price"] = tp
                    sig_rec["exit_time"] = bar["date"] + " UTC"
                    sig_rec["exit_ts"] = bar["ts"]
                    sig_rec["result_r"] = 2.0
                    changed = True
                    break

    return changed


# ========== æç»©ç»è®¡ ==========

def compute_stats(state):
    completed = [s for s in state["signals"] if s["status"] in ("tp_hit", "sl_hit")]
    expired = [s for s in state["signals"] if s["status"] in ("expired", "invalidated")]
    wins = sum(1 for s in completed if s["status"] == "tp_hit")
    losses = sum(1 for s in completed if s["status"] == "sl_hit")
    total_r = sum(s["result_r"] for s in completed if s["result_r"] is not None)

    # è¿èè¿è´¥
    streak_win = streak_loss = max_win = max_loss = 0
    for s in completed:
        if s["status"] == "tp_hit":
            streak_win += 1; streak_loss = 0
            max_win = max(max_win, streak_win)
        else:
            streak_loss += 1; streak_win = 0
            max_loss = max(max_loss, streak_loss)

    return {
        "total_signals": len(state["signals"]),
        "completed": len(completed),
        "wins": wins,
        "losses": losses,
        "expired": len(expired),
        "win_rate": wins / len(completed) if completed else 0,
        "total_r": total_r,
        "max_win_streak": max_win,
        "max_loss_streak": max_loss,
    }


# ========== ä¸»æµç¨ ==========

def main():
    api_key = os.environ.get("COINGLASS_API_KEY")
    if not api_key:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("COINGLASS_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if not api_key:
        print("ERROR: ç¼ºå° COINGLASS_API_KEY")
        sys.exit(1)

    print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] å¼å§æ£æ¥...")
    state = load_state()

    # 1) ææ°æ®
    try:
        bars = fetch_btc_1h_bars(api_key, N_BARS)
    except Exception as e:
        print(f"  ææ°æ®å¤±è´¥: {e}")
        sys.exit(1)
    if len(bars) < 250:
        print(f"  æ°æ®ä¸è¶³ {len(bars)} æ ¹, éåº")
        sys.exit(1)
    print(f"  æå° {len(bars)} æ ¹ 1h Kçº¿, ææ°: {bars[-1]['date']} = ${bars[-1]['close']:.2f}")

    # 1.5) é¦æ¬¡è¿è¡: è®¾ç½®éç¹ + åæ¬¢è¿æ¶æ¯, ä¸å¤çä»»ä½åå²ä¿¡å·
    if not state.get("started"):
        state["anchor_ts"] = bars[-2]["ts"]  # åæ°ç¬¬äºæ ¹ (ææ°è¿å¨ forming)
        state["started"] = True
        latest_close = bars[-1]["close"]
        welcome = (
            f"ð¤ *F6 ä¿¡å·æºå¨äººå·²å¯å¨*\n"
            f"âââââââââââââââ\n"
            f"ç­ç¥: F6 (Regime + EMA-200 é¡ºå¿ + çªç ´å¥åº)\n"
            f"æ ç: BTCUSDT 1h\n"
            f"å½å BTC: `${latest_close:,.2f}`\n"
            f"éç¹æ¶é´: `{bars[-2]['date']} UTC`\n\n"
            f"â± æ¯ 5 åéæ£æ¥ä¸æ¬¡\n"
            f"ð¯ æ¶æ»¡ 10 ä¸ªä¿¡å·èªå¨åææ¥\n\n"
            f"_ç­å¾ç¬¬ä¸ä¸ª F6 ä¿¡å·..._"
        )
        send_message(welcome)
        save_state(state)
        print(f"  é¦æ¬¡å¯å¨, éç¹ {bars[-2]['date']}, å·²åæ¬¢è¿æ¶æ¯")
        return

    # 2) æ£æ¥ç°æä¿¡å·çç¶æåå
    new_messages = []
    for i, sig in enumerate(state["signals"], 1):
        if sig["status"] in ("tp_hit", "sl_hit", "expired", "invalidated"):
            continue
        old_status = sig["status"]
        if update_signal_status(bars, sig):
            new_status = sig["status"]
            print(f"  ä¿¡å· #{i:03d}: {old_status} -> {new_status}")
            stats = compute_stats(state)
            if new_status == "entered":
                new_messages.append(msg_entered(i, sig, sig["entry_price"], sig["entry_time"]))
            elif new_status == "tp_hit":
                hold = (sig["exit_ts"] - sig["entry_ts"]) / 3600
                new_messages.append(msg_tp_hit(i, sig, sig["exit_price"], sig["exit_time"], hold, stats))
            elif new_status == "sl_hit":
                hold = (sig["exit_ts"] - sig["entry_ts"]) / 3600
                new_messages.append(msg_sl_hit(i, sig, sig["exit_price"], sig["exit_time"], hold, stats))
            elif new_status == "expired":
                new_messages.append(msg_expired(i, sig))
            elif new_status == "invalidated":
                new_messages.append(msg_invalidated_by_sl(i, sig))

    # 3) å¦æè¿æ²¡æ¶æ»¡ 10 ä¸ª, æ£æµæ°ä¿¡å·
    if len(state["signals"]) < MAX_SIGNALS:
        new_sigs = detect_new_signals(bars, state)
        for sig_rec in new_sigs:
            if len(state["signals"]) >= MAX_SIGNALS:
                break
            state["signals"].append(sig_rec)
            if state["first_signal_date"] is None:
                state["first_signal_date"] = sig_rec["signal_time"]
            n = len(state["signals"])
            print(f"  æ°ä¿¡å· #{n:03d}: {sig_rec['direction']} @ {sig_rec['signal_time']}")
            new_messages.append(msg_signal_formed(n, sig_rec))
            # ç«å»å°è¯æ¨è¿å®çç¶æ (å¯è½ä¸ä¸ªå°æ¶å·²ç»çªç ´)
            update_signal_status(bars, sig_rec)

    # 4) å TG
    for msg in new_messages:
        send_message(msg)
        time.sleep(0.5)  # é¿å TG éæµ

    # 5) ææ¥å¤å®
    stats = compute_stats(state)
    if (stats["completed"] + stats["expired"]) >= MAX_SIGNALS and not state["final_sent"]:
        period_end = datetime.utcnow().strftime("%Y-%m-%d")
        period = f"{state['first_signal_date'][:10] if state['first_signal_date'] else '?'} ~ {period_end}"
        stats["period"] = period
        send_message(msg_final_report(stats))
        state["final_sent"] = True
        print("  ææ¥å·²åé!")

    save_state(state)
    print(f"  done. å½å {len(state['signals'])} ä¿¡å·, "
          f"{stats['wins']}è {stats['losses']}è´¥ {stats['expired']}ä½åº, R={stats['total_r']:+.2f}")


if __name__ == "__main__":
    main()
