"""
3 策略赛马 bot
A: baseline 2R (控制组)
B: H 阶梯锁 + 连亏 2 停 24h (中庸 +840%)
C: 终极 alpha - H + Kelly + 金字塔 + 单向冷却 (激进 +1785%)

每个策略独立 state, TG 消息加 [A]/[B]/[C] 前缀。
"""
import os, sys, json, time
import urllib.request, urllib.parse, urllib.error
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

from signals import detect_signals
from backtest import _compute_ema, _compute_adx
from tg_notify import send_message


MAX_SIGNALS = 30  # 收 30 个就出战报 (3 策略共享, 实际每个最多 ~10 单)
N_BARS = 300
COINGLASS_BASE = "https://open-api-v4.coinglass.com"


# 通用 F6 参数 (3 策略共用)
COMMON_F6 = dict(
    body_ratio=0.5,
    entanglement_tolerance=0.005,
    sl_buffer_pct=0.02,
    entry_wait_bars=3,
    regime_adx_high=25,
    regime_ema_dist_trend=0.02,
)


@dataclass
class StrategyConfig:
    code: str          # "A" / "B" / "C"
    name: str
    state_file: str
    tp_target_r: float = 2.0
    use_stair: bool = False
    stair_levels: List[Tuple[float, float]] = field(default_factory=list)
    use_cooldown: bool = False
    cd_loss_count: int = 0
    cd_pause_hours: int = 0
    cd_direction_aware: bool = False
    use_kelly: bool = False
    use_pyramid: bool = False


STRATEGIES = [
    StrategyConfig(
        code="A", name="baseline 2R",
        state_file="state_A.json",
        tp_target_r=2.0,
    ),
    StrategyConfig(
        code="B", name="H阶梯锁 + 连亏2停24h",
        state_file="state_B.json",
        tp_target_r=8.0, use_stair=True,
        stair_levels=[(2.0, 1.0), (4.0, 2.0)],
        use_cooldown=True, cd_loss_count=2, cd_pause_hours=24,
    ),
    StrategyConfig(
        code="C", name="终极alpha Kelly+金字塔+单向冷却",
        state_file="state_C.json",
        tp_target_r=8.0, use_stair=True,
        stair_levels=[(2.0, 1.0), (4.0, 2.0)],
        use_cooldown=True, cd_loss_count=2, cd_pause_hours=24, cd_direction_aware=True,
        use_kelly=True, use_pyramid=True,
    ),
]


# ========== 数据 & 共用 ==========

def fetch_btc_1h_bars(api_key, n=300):
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (n + 5) * 3600 * 1000
    params = {
        "exchange": "Binance", "symbol": "BTCUSDT",
        "interval": "1h", "limit": 1000,
        "start_time": start_ms, "end_time": end_ms,
    }
    url = f"{COINGLASS_BASE}/api/futures/price/history?{urllib.parse.urlencode(params)}"
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


def load_state(path):
    if not os.path.exists(path):
        return {
            "signals": [],
            "first_signal_date": None,
            "final_sent": False,
            "anchor_ts": None,
            "started": False,
            "pause_until_ts": 0,
            "pause_until_ts_long": 0,
            "pause_until_ts_short": 0,
        }
    with open(path) as f:
        return json.load(f)


def save_state(state, path):
    with open(path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def labeled_send(code, text):
    send_message(f"[{code}] {text}")


def apply_f6_filter(bars, sig, ema200, adx):
    idx = sig["index"]
    close = bars[idx]["close"]
    ev = ema200[idx]
    if ev is None or ev <= 0:
        return False
    dist = abs(close - ev) / ev
    if adx[idx] > COMMON_F6["regime_adx_high"] and dist > COMMON_F6["regime_ema_dist_trend"]:
        return False
    if sig["direction"] == "long" and close > ev:
        return True
    if sig["direction"] == "short" and close < ev:
        return True
    return False


# ========== 策略相关 ==========

def check_cooldown(strategy: StrategyConfig, state, direction, now_ts):
    """返回 True 表示在冷却中, 应跳过"""
    if not strategy.use_cooldown:
        return False
    if strategy.cd_direction_aware:
        key = "pause_until_ts_long" if direction == "long" else "pause_until_ts_short"
        return now_ts < state.get(key, 0)
    return now_ts < state.get("pause_until_ts", 0)


def get_kelly_size(strategy: StrategyConfig, state):
    """根据最近完结交易计算下一单仓位"""
    if not strategy.use_kelly:
        return 1.0
    completed = [s for s in state["signals"] if s["status"] in ("tp_hit", "sl_hit")]
    if not completed:
        return 1.0
    # 看最近 3 笔
    recent = completed[-3:]
    # 净 R (考虑 size_multiplier 之前的原始 R, 用 result_r_raw)
    if len(recent) >= 3 and all(t.get("result_r_raw", t.get("result_r", 0)) > 0 for t in recent):
        return 2.0
    if len(recent) >= 2 and all(t.get("result_r_raw", t.get("result_r", 0)) > 0 for t in recent[-2:]):
        return 1.5
    if recent[-1].get("result_r_raw", recent[-1].get("result_r", 0)) < 0:
        return 0.7
    return 1.0


def build_signal_record(strategy: StrategyConfig, bars, sig, state):
    """构造一笔交易的初始记录"""
    direction = sig["direction"]
    sl_buffer = COMMON_F6["sl_buffer_pct"]
    if direction == "long":
        extremity = min(sig["B_low"], sig["C_low"])
        sl = extremity * (1 - sl_buffer)
        trigger = max(sig["B_close"], sig["C_close"])
    else:
        extremity = max(sig["B_high"], sig["C_high"])
        sl = extremity * (1 + sl_buffer)
        trigger = min(sig["B_close"], sig["C_close"])
    r = abs(trigger - sl)
    if direction == "long":
        tp = trigger + strategy.tp_target_r * r
    else:
        tp = trigger - strategy.tp_target_r * r

    sig_bar = bars[sig["index"]]
    expires_ts = sig_bar["ts"] + (COMMON_F6["entry_wait_bars"] + 1) * 3600
    expires_str = datetime.utcfromtimestamp(expires_ts).strftime("%Y-%m-%d %H:%M UTC")
    pattern = ("看涨反转 (急跌后底部缠绕)" if direction == "long"
               else "看跌反转 (急涨后顶部缠绕)")

    size_mult = get_kelly_size(strategy, state)

    return {
        "signal_time": sig_bar["date"] + " UTC",
        "signal_ts": sig_bar["ts"],
        "direction": direction,
        "trigger_price": round(trigger, 2),
        "sl0": round(sl, 2),          # 初始 SL (不变)
        "current_sl": round(sl, 2),   # 实时 SL (B/C 会随阶梯调)
        "tp": round(tp, 2),
        "r_dollar": round(r, 2),
        "expires_at": expires_str,
        "expires_ts": expires_ts,
        "pattern_desc": pattern,
        "status": "waiting",
        "entry_price": None,
        "entry_time": None,
        "entry_ts": None,
        "exit_price": None,
        "exit_time": None,
        "exit_ts": None,
        "result_r": None,
        "result_r_raw": None,     # 不含 size_multiplier 的原始 R
        "size_multiplier": size_mult,
        # H 阶梯 & 金字塔状态
        "stair_2r_locked": False,
        "stair_4r_locked": False,
        "pyramid_entered": False,
        "pyramid_entry_price": None,
    }


def update_signal_status(strategy: StrategyConfig, bars, sig_rec):
    """推进单个信号状态。返回 True 如果状态变化"""
    if sig_rec["status"] in ("tp_hit", "sl_hit", "expired", "invalidated"):
        return False

    sig_ts = sig_rec["signal_ts"]
    after = [b for b in bars if b["ts"] > sig_ts]
    if not after:
        return False

    changed = False
    direction = sig_rec["direction"]
    trigger = sig_rec["trigger_price"]
    tp = sig_rec["tp"]
    r = sig_rec["r_dollar"]

    # 等待入场
    if sig_rec["status"] == "waiting":
        sl = sig_rec["current_sl"]
        for bar in after:
            if bar["ts"] > sig_rec["expires_ts"]:
                sig_rec["status"] = "expired"
                changed = True
                break
            if direction == "long":
                if bar["low"] <= sl:
                    sig_rec["status"] = "invalidated"
                    changed = True
                    break
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

    # 持仓中: 走 H 阶梯锁 + 金字塔 + 出场
    if sig_rec["status"] == "entered":
        entry = sig_rec["entry_price"]
        entry_ts = sig_rec.get("entry_ts", sig_ts)

        for bar in after:
            if bar["ts"] <= entry_ts:
                continue
            sl = sig_rec["current_sl"]

            # H 阶梯锁: 多
            if strategy.use_stair and direction == "long":
                # 2R 阶梯
                if not sig_rec["stair_2r_locked"] and bar["high"] >= entry + 2*r:
                    new_sl = entry + 1*r
                    if new_sl > sl:
                        sig_rec["current_sl"] = round(new_sl, 2)
                        sig_rec["stair_2r_locked"] = True
                        sl = new_sl
                        # 不算 status change, 静默移 SL
                # 4R 阶梯
                if not sig_rec["stair_4r_locked"] and bar["high"] >= entry + 4*r:
                    new_sl = entry + 2*r
                    if new_sl > sl:
                        sig_rec["current_sl"] = round(new_sl, 2)
                        sig_rec["stair_4r_locked"] = True
                        sl = new_sl

            # H 阶梯锁: 空
            if strategy.use_stair and direction == "short":
                if not sig_rec["stair_2r_locked"] and bar["low"] <= entry - 2*r:
                    new_sl = entry - 1*r
                    if new_sl < sl:
                        sig_rec["current_sl"] = round(new_sl, 2)
                        sig_rec["stair_2r_locked"] = True
                        sl = new_sl
                if not sig_rec["stair_4r_locked"] and bar["low"] <= entry - 4*r:
                    new_sl = entry - 2*r
                    if new_sl < sl:
                        sig_rec["current_sl"] = round(new_sl, 2)
                        sig_rec["stair_4r_locked"] = True
                        sl = new_sl

            # 金字塔加仓 (1R 时)
            if strategy.use_pyramid and not sig_rec["pyramid_entered"]:
                if direction == "long" and bar["high"] >= entry + 1*r:
                    sig_rec["pyramid_entered"] = True
                    sig_rec["pyramid_entry_price"] = round(entry + r, 2)
                elif direction == "short" and bar["low"] <= entry - 1*r:
                    sig_rec["pyramid_entered"] = True
                    sig_rec["pyramid_entry_price"] = round(entry - r, 2)

            # 出场检查
            if direction == "long":
                if bar["low"] <= sl:
                    # 计算 R
                    main_r = (sl - entry) / r
                    pyramid_r = 0
                    if sig_rec["pyramid_entered"]:
                        pyramid_r = 0.5 * (sl - sig_rec["pyramid_entry_price"]) / r
                    total_r = main_r + pyramid_r
                    sig_rec["status"] = "sl_hit" if main_r < 0 else "tp_hit"
                    sig_rec["exit_price"] = round(sl, 2)
                    sig_rec["exit_time"] = bar["date"] + " UTC"
                    sig_rec["exit_ts"] = bar["ts"]
                    sig_rec["result_r_raw"] = round(total_r, 3)
                    sig_rec["result_r"] = round(total_r * sig_rec["size_multiplier"], 3)
                    changed = True
                    break
                if bar["high"] >= tp:
                    main_r = (tp - entry) / r
                    pyramid_r = 0
                    if sig_rec["pyramid_entered"]:
                        pyramid_r = 0.5 * (tp - sig_rec["pyramid_entry_price"]) / r
                    total_r = main_r + pyramid_r
                    sig_rec["status"] = "tp_hit"
                    sig_rec["exit_price"] = round(tp, 2)
                    sig_rec["exit_time"] = bar["date"] + " UTC"
                    sig_rec["exit_ts"] = bar["ts"]
                    sig_rec["result_r_raw"] = round(total_r, 3)
                    sig_rec["result_r"] = round(total_r * sig_rec["size_multiplier"], 3)
                    changed = True
                    break
            else:
                if bar["high"] >= sl:
                    main_r = (entry - sl) / r
                    pyramid_r = 0
                    if sig_rec["pyramid_entered"]:
                        pyramid_r = 0.5 * (sig_rec["pyramid_entry_price"] - sl) / r
                    total_r = main_r + pyramid_r
                    sig_rec["status"] = "sl_hit" if main_r < 0 else "tp_hit"
                    sig_rec["exit_price"] = round(sl, 2)
                    sig_rec["exit_time"] = bar["date"] + " UTC"
                    sig_rec["exit_ts"] = bar["ts"]
                    sig_rec["result_r_raw"] = round(total_r, 3)
                    sig_rec["result_r"] = round(total_r * sig_rec["size_multiplier"], 3)
                    changed = True
                    break
                if bar["low"] <= tp:
                    main_r = (entry - tp) / r
                    pyramid_r = 0
                    if sig_rec["pyramid_entered"]:
                        pyramid_r = 0.5 * (sig_rec["pyramid_entry_price"] - tp) / r
                    total_r = main_r + pyramid_r
                    sig_rec["status"] = "tp_hit"
                    sig_rec["exit_price"] = round(tp, 2)
                    sig_rec["exit_time"] = bar["date"] + " UTC"
                    sig_rec["exit_ts"] = bar["ts"]
                    sig_rec["result_r_raw"] = round(total_r, 3)
                    sig_rec["result_r"] = round(total_r * sig_rec["size_multiplier"], 3)
                    changed = True
                    break

    return changed


def update_cooldown(strategy: StrategyConfig, state):
    """单笔 SL 之后, 检查是否触发冷却"""
    if not strategy.use_cooldown:
        return False
    completed = [s for s in state["signals"] if s["status"] in ("tp_hit", "sl_hit")]
    if len(completed) < strategy.cd_loss_count:
        return False
    recent = completed[-strategy.cd_loss_count:]
    if not all((t.get("result_r_raw") or t.get("result_r", 0)) < 0 for t in recent):
        return False
    last_exit_ts = recent[-1]["exit_ts"]
    pause_ts = last_exit_ts + strategy.cd_pause_hours * 3600
    if strategy.cd_direction_aware:
        direction = recent[-1]["direction"]
        key = "pause_until_ts_long" if direction == "long" else "pause_until_ts_short"
        if pause_ts > state.get(key, 0):
            state[key] = pause_ts
            return True
    else:
        if pause_ts > state.get("pause_until_ts", 0):
            state["pause_until_ts"] = pause_ts
            return True
    return False


# ========== 信号检测 & TG ==========

def detect_new_signals(strategy: StrategyConfig, bars, state, ema200, adx):
    """返回原始 signal dict 列表 (不调用 build_signal_record).
    build 推到 process_strategy 里逐个调用, 这样 Kelly 仓位能看到刚 append 的上一单状态."""
    anchor_ts = state.get("anchor_ts") or 0
    known_ts = {s["signal_ts"] for s in state["signals"]}
    raw_signals = detect_signals(bars, COMMON_F6["body_ratio"], COMMON_F6["entanglement_tolerance"])
    new = []
    now_ts = int(time.time())
    # 突破窗口长度 (秒) - 信号 K + entry_wait_bars 后过期
    expire_window_sec = (COMMON_F6["entry_wait_bars"] + 1) * 3600
    for sig in raw_signals:
        sig_bar = bars[sig["index"]]
        if sig_bar["ts"] in known_ts:
            continue
        if sig_bar["ts"] <= anchor_ts:
            continue
        if sig["index"] >= len(bars) - 1:
            continue
        # 跳过陈旧信号 — 突破窗口已过期就不再推送
        if sig_bar["ts"] + expire_window_sec < now_ts:
            continue
        if not apply_f6_filter(bars, sig, ema200, adx):
            continue
        # 冷却检查
        if check_cooldown(strategy, state, sig["direction"], sig_bar["ts"]):
            continue
        new.append(sig)  # 返回原始 sig, build 推到调用方
    return new


def compute_strategy_stats(state):
    """计算策略当前累计战绩"""
    signals = state.get("signals", [])
    completed = [s for s in signals if s["status"] in ("tp_hit", "sl_hit")]
    n_total = len(signals)
    n_completed = len(completed)
    n_pending = sum(1 for s in signals if s["status"] in ("waiting", "entered"))
    n_expired = sum(1 for s in signals if s["status"] in ("expired", "invalidated"))
    wins = sum(1 for s in completed if (s.get("result_r_raw") or s.get("result_r") or 0) > 0)
    losses = n_completed - wins
    total_r_raw = sum((s.get("result_r_raw") or 0) for s in completed)
    total_r_net = sum((s.get("result_r") or 0) for s in completed)
    # 连胜连败
    cur_streak = 0; streak_type = None
    for s in reversed(completed):
        r = s.get("result_r_raw") or s.get("result_r") or 0
        if streak_type is None:
            streak_type = "win" if r > 0 else "loss"
            cur_streak = 1
        elif (streak_type == "win" and r > 0) or (streak_type == "loss" and r < 0):
            cur_streak += 1
        else:
            break
    # 最长连胜/连败
    max_win_streak = max_loss_streak = 0
    w_run = l_run = 0
    for s in completed:
        r = s.get("result_r_raw") or s.get("result_r") or 0
        if r > 0:
            w_run += 1; l_run = 0
            max_win_streak = max(max_win_streak, w_run)
        else:
            l_run += 1; w_run = 0
            max_loss_streak = max(max_loss_streak, l_run)
    win_rate = wins / n_completed if n_completed else 0
    return {
        "n_total": n_total, "n_completed": n_completed,
        "n_pending": n_pending, "n_expired": n_expired,
        "wins": wins, "losses": losses, "win_rate": win_rate,
        "total_r_raw": total_r_raw, "total_r_net": total_r_net,
        "cur_streak": cur_streak, "streak_type": streak_type,
        "max_win_streak": max_win_streak, "max_loss_streak": max_loss_streak,
    }


def fmt_stats_footer(strategy, state):
    """生成策略统计 footer, 加在每条消息底部"""
    s = compute_strategy_stats(state)
    if s["n_completed"] == 0 and s["n_pending"] == 0:
        return ""  # 没数据不显示

    # 连胜连败标识
    streak_emoji = ""
    if s["cur_streak"] > 0 and s["streak_type"]:
        if s["streak_type"] == "win":
            streak_emoji = f"🔥 连胜 {s['cur_streak']}"
        else:
            streak_emoji = f"❄️ 连败 {s['cur_streak']}"

    # 胜率显示
    wr_str = f"{s['win_rate']*100:.1f}%" if s["n_completed"] > 0 else "—"

    # 累计 R
    r_display = f"{s['total_r_net']:+.2f}R"
    if strategy.use_kelly or strategy.use_pyramid:
        # 策略 C: 显示净 R (含 Kelly 加仓) + 原始 R
        r_display = f"{s['total_r_net']:+.2f}R (原始 {s['total_r_raw']:+.2f}R)"

    # 冷却状态 (B/C 才有)
    cd_info = ""
    if strategy.use_cooldown:
        now_ts = int(time.time())
        if strategy.cd_direction_aware:
            until_long = state.get("pause_until_ts_long", 0)
            until_short = state.get("pause_until_ts_short", 0)
            if now_ts < until_long:
                hours_left = (until_long - now_ts) / 3600
                cd_info = f"\n❄️ 多单冷却中 ({hours_left:.1f}h 剩)"
            if now_ts < until_short:
                hours_left = (until_short - now_ts) / 3600
                cd_info += f"\n❄️ 空单冷却中 ({hours_left:.1f}h 剩)"
        else:
            until = state.get("pause_until_ts", 0)
            if now_ts < until:
                hours_left = (until - now_ts) / 3600
                cd_info = f"\n❄️ 冷却中 ({hours_left:.1f}h 剩)"

    footer = (
        f"\n━━━━━━━━━━━━━━━\n"
        f"📊 <b>[{strategy.code}] 累计战绩</b>\n"
        f"已完成 {s['n_completed']} 单 ({s['wins']}胜 {s['losses']}败, 胜率 {wr_str})\n"
        f"累计 R: <b>{r_display}</b>\n"
        f"持仓中: {s['n_pending']} 单 · 作废: {s['n_expired']} 单"
    )
    if streak_emoji:
        footer += f"\n{streak_emoji} (历史最长 {s['max_win_streak']}胜 / {s['max_loss_streak']}败)"
    footer += cd_info
    return footer


def fmt_signal_formed(strategy, n, sig, state=None):
    s = (f"🔔 <b>新信号 #{n:03d} — {strategy.name}</b>\n"
         f"━━━━━━━━━━━━━━━\n"
         f"方向: {'📈 做多' if sig['direction']=='long' else '📉 做空'} ({sig['direction'].upper()})\n"
         f"形态: {sig['pattern_desc']}\n"
         f"时间: <code>{sig['signal_time']}</code>\n\n"
         f"📍 入场触发: <code>${sig['trigger_price']:,.2f}</code>\n"
         f"🛑 止损 (初始): <code>${sig['sl0']:,.2f}</code>\n"
         f"🎯 止盈目标: <code>${sig['tp']:,.2f}</code> ({strategy.tp_target_r}R)\n"
         f"⚖️ 仓位倍数: <b>{sig['size_multiplier']}×</b>\n"
         f"⏰ 突破窗口: {sig['expires_at']} 前有效")
    if state is not None:
        s += fmt_stats_footer(strategy, state)
    return s


def fmt_entered(strategy, n, sig, state=None):
    s = (f"✅ <b>#{n:03d} 已入场 — {strategy.name}</b>\n"
         f"━━━━━━━━━━━━━━━\n"
         f"入场价: <code>${sig['entry_price']:,.2f}</code>\n"
         f"入场时间: {sig['entry_time']}\n"
         f"当前 SL: <code>${sig['current_sl']:,.2f}</code>\n"
         f"目标 TP: <code>${sig['tp']:,.2f}</code>\n"
         f"仓位: <b>{sig['size_multiplier']}×</b>")
    if state is not None:
        s += fmt_stats_footer(strategy, state)
    return s


def fmt_exit(strategy, n, sig, outcome, state=None):
    """outcome = 'tp' / 'sl'"""
    icon = "🟢 TP" if outcome == "tp" else "🔴 SL"
    r_str = f"{sig['result_r']:+.2f}R" if sig['result_r'] is not None else "?"
    extra = ""
    if sig.get("pyramid_entered"):
        extra = f"\n金字塔加仓: ${sig['pyramid_entry_price']:.2f}"
    if sig.get("stair_4r_locked"):
        extra += "\n阶梯锁: 达到 +4R, SL 已升到 +2R"
    elif sig.get("stair_2r_locked"):
        extra += "\n阶梯锁: 达到 +2R, SL 已升到 +1R"
    s = (f"{icon} <b>#{n:03d} 出场 — {strategy.name}</b>\n"
         f"━━━━━━━━━━━━━━━\n"
         f"出场价: <code>${sig['exit_price']:,.2f}</code>\n"
         f"时间: {sig['exit_time']}\n"
         f"结果: <b>{r_str}</b>\n"
         f"原始 R (无加仓): {sig.get('result_r_raw', '?')}\n"
         f"仓位倍数: {sig['size_multiplier']}×{extra}")
    if state is not None:
        s += fmt_stats_footer(strategy, state)
    return s


def fmt_stair(strategy, n, sig, level, state=None):
    """level = '2r' or '4r'"""
    s = (f"🪜 <b>#{n:03d} 阶梯锁升级 — {strategy.name}</b>\n"
         f"━━━━━━━━━━━━━━━\n"
         f"价格达到 +{level.upper()}, SL 已上移到 <code>${sig['current_sl']:,.2f}</code>\n"
         f"现在 {'最少赚 +1R' if level == '2r' else '最少赚 +2R'}")
    if state is not None:
        s += fmt_stats_footer(strategy, state)
    return s


def fmt_pyramid(strategy, n, sig, state=None):
    s = (f"🔺 <b>#{n:03d} 金字塔加仓 — {strategy.name}</b>\n"
         f"━━━━━━━━━━━━━━━\n"
         f"价格触及 +1R, 加 0.5× 仓位\n"
         f"加仓入场价: <code>${sig['pyramid_entry_price']:,.2f}</code>\n"
         f"总仓位: 1.5× ({sig['size_multiplier']}× 主仓 + 0.5× 加仓)")
    if state is not None:
        s += fmt_stats_footer(strategy, state)
    return s


def fmt_cooldown(strategy, hours, state=None):
    s = (f"❄️ <b>触发冷却 — {strategy.name}</b>\n"
         f"━━━━━━━━━━━━━━━\n"
         f"连续 {strategy.cd_loss_count} 次止损, 暂停 {hours} 小时不接新单\n"
         f"等市场情绪冷静后再战")
    if state is not None:
        s += fmt_stats_footer(strategy, state)
    return s


# ========== 主流程 ==========

def process_strategy(strategy: StrategyConfig, bars, ema200, adx):
    state = load_state(strategy.state_file)

    # 首次启动
    if not state.get("started"):
        state["anchor_ts"] = bars[-2]["ts"]
        state["started"] = True
        latest_close = bars[-1]["close"]
        welcome = (
            f"🤖 <b>{strategy.name} 已启动</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"策略代号: <b>{strategy.code}</b>\n"
            f"标的: BTCUSDT 1h\n"
            f"当前 BTC: <code>${latest_close:,.2f}</code>\n"
            f"锚点: <code>{bars[-2]['date']} UTC</code>\n\n"
            f"<i>等待 F6 信号...</i>"
        )
        labeled_send(strategy.code, welcome)
        save_state(state, strategy.state_file)
        return

    # 推进现有信号状态
    for i, sig in enumerate(state["signals"], 1):
        if sig["status"] in ("tp_hit", "sl_hit", "expired", "invalidated"):
            continue
        old_status = sig["status"]
        old_stair_2r = sig.get("stair_2r_locked", False)
        old_stair_4r = sig.get("stair_4r_locked", False)
        old_pyramid = sig.get("pyramid_entered", False)

        update_signal_status(strategy, bars, sig)

        new_status = sig["status"]

        # 状态变化通知 (传 state 以便加策略统计 footer)
        if old_status != new_status:
            if new_status == "entered":
                labeled_send(strategy.code, fmt_entered(strategy, i, sig, state))
            elif new_status == "tp_hit":
                labeled_send(strategy.code, fmt_exit(strategy, i, sig, "tp", state))
                cd_triggered = update_cooldown(strategy, state)
            elif new_status == "sl_hit":
                labeled_send(strategy.code, fmt_exit(strategy, i, sig, "sl", state))
                cd_triggered = update_cooldown(strategy, state)
                if cd_triggered:
                    labeled_send(strategy.code, fmt_cooldown(strategy, strategy.cd_pause_hours, state))
            elif new_status == "expired":
                labeled_send(strategy.code, f"⏰ [#{i:03d}] 突破窗口已过, 信号作废 — {strategy.name}" + fmt_stats_footer(strategy, state))
            elif new_status == "invalidated":
                labeled_send(strategy.code, f"❌ [#{i:03d}] 突破前先碰 SL, 信号作废 — {strategy.name}" + fmt_stats_footer(strategy, state))

        # 阶梯锁通知
        if strategy.use_stair and sig["status"] == "entered":
            if not old_stair_2r and sig.get("stair_2r_locked"):
                labeled_send(strategy.code, fmt_stair(strategy, i, sig, "2r", state))
            if not old_stair_4r and sig.get("stair_4r_locked"):
                labeled_send(strategy.code, fmt_stair(strategy, i, sig, "4r", state))

        # 金字塔通知
        if strategy.use_pyramid and not old_pyramid and sig.get("pyramid_entered"):
            labeled_send(strategy.code, fmt_pyramid(strategy, i, sig, state))
        time.sleep(0.3)

    # 检测新信号 (返回原始 sig, 逐个 build + append + 更新状态, 让 Kelly 能看到刚处理完的上一单)
    if len(state["signals"]) < MAX_SIGNALS:
        new_raw_sigs = detect_new_signals(strategy, bars, state, ema200, adx)
        for raw_sig in new_raw_sigs:
            if len(state["signals"]) >= MAX_SIGNALS:
                break
            # ⭐ build_signal_record 在每个信号被处理时调用, 而不是一次性 build
            #     这样 Kelly 看到的 completed 列表包含本批前面已 append 且已更新状态的信号
            sig_rec = build_signal_record(strategy, bars, raw_sig, state)
            state["signals"].append(sig_rec)
            if state["first_signal_date"] is None:
                state["first_signal_date"] = sig_rec["signal_time"]
            n = len(state["signals"])
            labeled_send(strategy.code, fmt_signal_formed(strategy, n, sig_rec, state))
            time.sleep(0.3)
            # 立刻推进状态 — 若上根 K 已突破或已 TP/SL, 立刻更新
            update_signal_status(strategy, bars, sig_rec)
            if sig_rec["status"] == "entered":
                labeled_send(strategy.code, fmt_entered(strategy, n, sig_rec, state))
                time.sleep(0.3)
            # 注意: 若 sig_rec 立刻 tp_hit/sl_hit, status 已更新, 但本轮不发出场消息
            #       (出场消息由下一轮 process 时检测 old_status != new_status 触发)

    save_state(state, strategy.state_file)


NOTIONAL_USD = 10000  # 每单仓位规模: $1000 保证金 × 10x 杠杆


def signal_dollar_pl(sig):
    """计算单笔 $ 盈亏 (假设 $10,000 仓位)"""
    if sig["status"] not in ("tp_hit", "sl_hit"):
        return None
    r = sig.get("result_r") or 0
    r_dollar = sig.get("r_dollar") or 0
    entry = sig.get("entry_price") or sig.get("trigger_price") or 0
    if entry == 0 or r_dollar == 0:
        return 0
    r_pct = r_dollar / entry  # R 占入场价的百分比
    return r * r_pct * NOTIONAL_USD


def build_summary_report(strategies_data, latest_btc, title="📊 战报"):
    """生成 3 策略合并汇总文本 ($ 格式, 假设 $1000 保证金 + 10x 杠杆 = $10,000 仓位)"""
    now_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    parts = [
        f"<b>{title}</b>",
        f"<i>截至 {now_utc} · BTC ${latest_btc:,.0f}</i>",
        f"<i>每单按 $1,000 保证金 + 10x 杠杆 = $10,000 仓位算</i>",
        "━━━━━━━━━━━━━━━",
    ]

    grand_total = {}

    for strategy, state in strategies_data:
        s = compute_strategy_stats(state)
        signals = state.get("signals", [])

        # 把信号分 3 组并按时间排序
        completed_sigs = []; entered_sigs = []; expired_sigs = []
        for i, sig in enumerate(signals, 1):
            if sig["status"] in ("tp_hit", "sl_hit"):
                completed_sigs.append((i, sig))
            elif sig["status"] == "entered":
                entered_sigs.append((i, sig))
            elif sig["status"] in ("expired", "invalidated"):
                expired_sigs.append((i, sig))
        completed_sigs.sort(key=lambda x: x[1].get("exit_ts") or 0)
        entered_sigs.sort(key=lambda x: x[1].get("entry_ts") or 0)
        expired_sigs.sort(key=lambda x: x[1].get("signal_ts") or 0)

        # 累计 $ 盈亏
        total_pl = sum(signal_dollar_pl(sig) or 0 for _, sig in completed_sigs)
        avg_pl = total_pl / len(completed_sigs) if completed_sigs else 0
        grand_total[strategy.code] = total_pl

        # Header 行
        wr_str = f"{s['win_rate']*100:.1f}%" if s["n_completed"] > 0 else "—"

        section_lines = [
            f"<b>[{strategy.code}] {strategy.name}</b>",
            f"总信号 {s['n_total']} · 完成 {s['n_completed']} ({s['wins']}胜 {s['losses']}败) · 持仓 {s['n_pending']} · 作废 {s['n_expired']}",
            f"胜率 <b>{wr_str}</b> · 累计盈亏 <b>${total_pl:+,.2f}</b> · 平均 <b>${avg_pl:+,.2f}</b>/单",
        ]

        # 已完成明细
        if completed_sigs:
            section_lines.append("\n✅❌ 已完结:")
            for i, sig in completed_sigs:
                dir_char = "📉空" if sig["direction"] == "short" else "📈多"
                sig_time = sig["signal_time"].replace(" UTC", "")
                outcome_icon = "🟢" if sig["status"] == "tp_hit" else "🔴"
                dollar_pl = signal_dollar_pl(sig) or 0
                section_lines.append(
                    f"  {outcome_icon} <code>#{i:03d}</code> {sig_time} {dir_char} "
                    f"@${sig['entry_price']:,.0f} → ${sig['exit_price']:,.0f} = <b>${dollar_pl:+,.2f}</b>"
                )

        # 持仓明细
        if entered_sigs:
            section_lines.append("\n⏳ 持仓中:")
            for i, sig in entered_sigs:
                dir_char = "📉空" if sig["direction"] == "short" else "📈多"
                sig_time = sig["signal_time"].replace(" UTC", "")
                # 算潜在亏损 ($ 单位)
                r_dollar = sig.get("r_dollar") or 0
                entry = sig.get("entry_price") or 0
                potential_loss = (r_dollar / entry) * NOTIONAL_USD if entry > 0 else 0
                section_lines.append(
                    f"  <code>#{i:03d}</code> {sig_time} {dir_char} "
                    f"@${sig['entry_price']:,.0f} | SL ${sig['current_sl']:,.0f} (亏-${potential_loss:,.0f}) | TP ${sig['tp']:,.0f}"
                )

        # 作废明细
        if expired_sigs:
            ids = ", ".join(f"#{i:03d}" for i, _ in expired_sigs)
            section_lines.append(f"\n⚪ 作废: {ids}")

        parts.append("\n".join(section_lines))
        parts.append("━━━━━━━━━━━━━━━")

    # 3 策略横向对比
    if grand_total:
        compare_lines = ["<b>🏁 3 策略横向对比</b>"]
        sorted_strats = sorted(grand_total.items(), key=lambda x: -x[1])
        medals = ["🥇", "🥈", "🥉"]
        for idx, (code, pl) in enumerate(sorted_strats):
            medal = medals[idx] if idx < 3 else "  "
            compare_lines.append(f"{medal} <b>[{code}]</b> 累计 <b>${pl:+,.2f}</b>")
        parts.append("\n".join(compare_lines))
        parts.append("━━━━━━━━━━━━━━━")

    parts.append("⏰ 下次汇总: 每周日 12:00 PT (北京周一 03:00)")
    return "\n\n".join(parts)


def maybe_send_summary_report(strategies_data, latest_btc):
    """首次跑发校对; 之后每周日 12:00 PT 自动推汇总.
    REPORT_FORMAT_VERSION 升级时也会重发一次校对."""
    REPORT_FORMAT_VERSION = 2  # 改成 $ 格式后, 重发一次校对
    now_ts = int(time.time())
    SECONDS_PER_DAY = 86400

    # 首次跑 / 报告格式升级 (state 没有当前版本的 v 字段)
    needs_correction = all(
        s.get("report_format_v") != REPORT_FORMAT_VERSION
        for _, s in strategies_data
    )
    if needs_correction:
        text = build_summary_report(strategies_data, latest_btc, title="📋 校对报告 (v2 · $ 格式)")
        send_message(text)
        for _, state in strategies_data:
            state["last_weekly_report_ts"] = now_ts
            state["report_format_v"] = REPORT_FORMAT_VERSION
        return True

    # 周日 12:00 PT 检查
    # PDT (3-11 月) = UTC-7 → 周日 12:00 PT = 周日 19:00 UTC
    now_dt = datetime.utcfromtimestamp(now_ts)
    is_sunday = now_dt.weekday() == 6
    is_noon_window = 19 <= now_dt.hour <= 20
    last_ts = min(s.get("last_weekly_report_ts", 0) for _, s in strategies_data)
    elapsed_days = (now_ts - last_ts) / SECONDS_PER_DAY

    if is_sunday and is_noon_window and elapsed_days >= 6:
        text = build_summary_report(strategies_data, latest_btc, title="📊 每周战报")
        send_message(text)
        for _, state in strategies_data:
            state["last_weekly_report_ts"] = now_ts
        return True
    return False


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
        print("ERROR: 缺少 COINGLASS_API_KEY")
        sys.exit(1)

    print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] 赛马 bot 启动")
    bars = fetch_btc_1h_bars(api_key, N_BARS)
    if len(bars) < 250:
        print(f"  数据不足 {len(bars)} 根")
        sys.exit(1)
    print(f"  拉到 {len(bars)} 根, 最新 {bars[-1]['date']} ${bars[-1]['close']:.2f}")

    ema200 = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)

    for strategy in STRATEGIES:
        print(f"\n--- 策略 {strategy.code}: {strategy.name} ---")
        try:
            process_strategy(strategy, bars, ema200, adx)
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback; traceback.print_exc()

    # 处理完所有策略后, 检查是否需要发汇总报告 (校对 / 每周战报)
    try:
        strategies_data = [(s, load_state(s.state_file)) for s in STRATEGIES]
        if maybe_send_summary_report(strategies_data, bars[-1]["close"]):
            for strategy, state in strategies_data:
                save_state(state, strategy.state_file)
            print("  汇总报告已推送")
    except Exception as e:
        print(f"  汇总报告 ERROR: {e}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()
