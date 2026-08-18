"""
重叠K线颈线突破 — 串行回测引擎 (新策略, 与双线反战完全独立)

规则 (2026-08-17 与大漂亮确认):
- 形态确认后, 在上颈线挂 buy-stop, 下颈线挂 sell-stop, 先触发哪个做哪个方向
- TP = 颈线价 ± 2L, SL = 颈线价 ∓ 1.5L (以触发那条颈线价为基准, L=实体交集高度)
- 盈亏比 2 : 1.5 ≈ 1.33 : 1

口径声明 (阶段2.5 固定):
1. 挂单语义: 形态在第二根K线收盘确认, 从下一根K线开始等待触发, expire_bars 根内
   未触发则作废 (默认 3, 与 F 系列 entry_wait_bars=3 同约定)
2. gap 处理: 若某根K线开盘价已越过颈线, 按开盘价成交 (更不利); 否则按颈线价成交
3. 同一根K线内上下颈线都可能触发且无法判序时 → 该信号作废 (保守), 计数为 ambiguous
4. TP/SL 从颈线价起算 (不是实际成交价), 与用户约定一致; R 记账单位 = 1.5L (设计风险)
5. 入场那根K线剩余部分不用于判 SL/TP, 从下一根开始扫 (与现有 backtest.py 同约定)
6. 同一根K线同时触及 SL 和 TP → SL 优先 (保守)
7. 串行持仓: 同一时间只持一单, 持仓期间出现的新形态一律忽略;
   空仓时若多个未过期形态同时可触发, 取最新的形态 (最新市场结构)
8. 手续费: 双边各 0.05% (taker), 计入 net_r
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from neckline_signals import detect_overlap_signals, REF_MODES


@dataclass
class NecklineConfig:
    name: str
    ref_mode: str = "longer"     # longer / shorter / first / second
    ratio: float = 0.5           # 交集高度 > ratio * 参照实体高度
    tp_mult: float = 2.0         # TP = 颈线 ± tp_mult * L
    sl_mult: float = 1.5         # SL = 颈线 ∓ sl_mult * L
    expire_bars: int = 3         # 形态确认后等待触发的窗口
    max_hold_bars: int = 0       # 0 = 不启用时间止损
    fee_rate: float = 0.0        # 单边费率, 0 = 不计手续费 (用户要求)
    notional_usd: float = 10000.0  # 每单名义仓位 ($1,000保证金 x 10x杠杆, 与双线反战同约定)
    # ---- 第二轮变形参数 ----
    min_l_pct: float = 0.0       # L/价格 最小门槛 (0.0025 = 0.25%), 0 = 不启用
    regime_skip_trend: bool = False  # F6式: ADX>25 且 |close-EMA200|/EMA200>2% 的强趋势期跳过
    breakeven_at_l: float = 0.0  # 浮盈达到 X*L (从颈线价算) 时把SL移到入场价, 0 = 不启用
    # ---- 第三轮变形参数 (2026-08-17 网上资料: 假突破过滤工具箱) ----
    entry_confirm: str = "stop"  # "stop"=盘中触价(默认) / "close"=收盘确认后下根开盘进 / "retest"=突破后等回踩颈线进
    buffer_l: float = 0.0        # 突破缓冲: 触发价 = 颈线 ± buffer_l*L; >0 时 TP/SL 改从触发价起算
    vol_expansion: float = 0.0   # 放量形态: 第二根K线 volume >= X * 前20根均量, 0 = 不启用
    squeeze_atr: float = 0.0     # 压缩前置: 两根K线总波幅(max high - min low) <= X * ATR14, 0 = 不启用
    # ---- 第四轮变形参数: 趋势过滤器 (方向门, 取信号bar收盘时点, 无前视) ----
    # ""=关闭 / "ema200"=EMA200位置 / "ema50_slope"=EMA50斜率(vs 8根前)
    # "supertrend"=SuperTrend(10,3)方向 / "adx20"=ADX14>=20强度门(不限方向) / "rsi50"=RSI14中轴
    trend_filter: str = ""
    # ---- 第六轮: 出场/仓位管理 ----
    # exit_mode: ""=固定TP/SL(默认) / "chandelier"=吊灯跟踪(峰值-X*ATR14, 无TP)
    #            / "trail_l"=L距离跟踪(峰值-1.5L, 无TP) / "stair"=阶梯锁利(TP=6L, +2L锁+1L, +4L锁+2L)
    #            / "scaled"=分批(+1.5L平一半+SL推入场价, 余半TP=4L)
    # 同bar顺序约定: 先用旧止损判出场, 再用本bar极值更新跟踪线 (保守, 与BE同约定)
    exit_mode: str = ""
    chand_atr_mult: float = 3.0
    # 等风险仓位: >0 时每单名义 = min(risk_sizing_usd / 止损距离%, notional_cap_usd)
    risk_sizing_usd: float = 0.0
    notional_cap_usd: float = 100000.0


def _compute_supertrend_dir(bars, period=10, mult=3.0):
    """SuperTrend方向序列: +1=上升趋势(价在带上方), -1=下降趋势"""
    from backtest import _compute_atr
    atr = _compute_atr(bars, period)
    n = len(bars)
    trend = [1] * n
    f_ub = [0.0] * n
    f_lb = [0.0] * n
    for i in range(n):
        hl2 = (bars[i]["high"] + bars[i]["low"]) / 2.0
        ub = hl2 + mult * atr[i]
        lb = hl2 - mult * atr[i]
        if i == 0:
            f_ub[i], f_lb[i] = ub, lb
            continue
        f_ub[i] = ub if (ub < f_ub[i-1] or bars[i-1]["close"] > f_ub[i-1]) else f_ub[i-1]
        f_lb[i] = lb if (lb > f_lb[i-1] or bars[i-1]["close"] < f_lb[i-1]) else f_lb[i-1]
        if bars[i]["close"] > f_ub[i-1]:
            trend[i] = 1
        elif bars[i]["close"] < f_lb[i-1]:
            trend[i] = -1
        else:
            trend[i] = trend[i-1]
    return trend


def _compute_rsi(bars, period=14):
    """Wilder RSI"""
    n = len(bars)
    rsi = [50.0] * n
    avg_g = avg_l = 0.0
    for i in range(1, n):
        ch = bars[i]["close"] - bars[i-1]["close"]
        g = max(ch, 0.0)
        l = max(-ch, 0.0)
        if i <= period:
            avg_g += g / period
            avg_l += l / period
            if i == period and (avg_g + avg_l) > 0:
                rsi[i] = 100.0 * avg_g / (avg_g + avg_l)
        else:
            avg_g = (avg_g * (period - 1) + g) / period
            avg_l = (avg_l * (period - 1) + l) / period
            if (avg_g + avg_l) > 0:
                rsi[i] = 100.0 * avg_g / (avg_g + avg_l)
    return rsi


def _apply_trend_filter(bars, signals, mode):
    """给信号打 allow_long/allow_short 标记 (取信号bar收盘时点, 无前视)。
    热身期信号直接丢弃。adx20 模式为强度门: 不限方向, ADX<20 的信号丢弃。"""
    from backtest import _compute_ema, _compute_adx
    if mode == "ema200":
        ema = _compute_ema(bars, 200)
        warm = 200
        out = []
        for s in signals:
            i = s["index"]
            if i < warm:
                continue
            s = dict(s)
            s["allow_long"] = bars[i]["close"] > ema[i]
            s["allow_short"] = bars[i]["close"] < ema[i]
            out.append(s)
        return out
    if mode == "ema50_slope":
        ema = _compute_ema(bars, 50)
        warm = 58
        out = []
        for s in signals:
            i = s["index"]
            if i < warm:
                continue
            up = ema[i] > ema[i - 8]
            s = dict(s)
            s["allow_long"] = up
            s["allow_short"] = not up
            out.append(s)
        return out
    if mode == "supertrend":
        st = _compute_supertrend_dir(bars, 10, 3.0)
        warm = 30
        out = []
        for s in signals:
            i = s["index"]
            if i < warm:
                continue
            s = dict(s)
            s["allow_long"] = st[i] == 1
            s["allow_short"] = st[i] == -1
            out.append(s)
        return out
    if mode == "adx20":
        adx = _compute_adx(bars, 14)
        warm = 28
        return [s for s in signals if s["index"] >= warm and adx[s["index"]] >= 20]
    if mode == "rsi50":
        rsi = _compute_rsi(bars, 14)
        warm = 15
        out = []
        for s in signals:
            i = s["index"]
            if i < warm:
                continue
            up = rsi[i] > 50
            s = dict(s)
            s["allow_long"] = up
            s["allow_short"] = not up
            out.append(s)
        return out
    raise ValueError(f"未知 trend_filter: {mode}")


def _position_notional(cfg: NecklineConfig, entry: float, L: float) -> float:
    """P5 等风险仓位: 名义 = 风险$ / 止损距离%, 封顶 notional_cap"""
    if cfg.risk_sizing_usd > 0 and entry > 0 and L > 0:
        sl_frac = (cfg.sl_mult * L) / entry
        if sl_frac > 0:
            return min(cfg.risk_sizing_usd / sl_frac, cfg.notional_cap_usd)
    return cfg.notional_usd


def _init_exit_fields(pos: Dict[str, Any], cfg: NecklineConfig) -> None:
    """入场时初始化出场模式相关字段 (所有模式都设置 notional/peak)"""
    d, level, L = pos["direction"], pos["level"], pos["L"]
    pos["notional"] = _position_notional(cfg, pos["entry"], L)
    pos["peak"] = pos["entry"]
    if cfg.exit_mode in ("chandelier", "trail_l"):
        pos["tp"] = None  # 无固定TP, 靠跟踪线出场
    elif cfg.exit_mode == "stair":
        pos["tp"] = level + 6 * L if d == "long" else level - 6 * L
        pos["lock1"] = pos["lock2"] = False
    elif cfg.exit_mode == "scaled":
        pos["tp1"] = level + 1.5 * L if d == "long" else level - 1.5 * L
        pos["tp"] = level + 4 * L if d == "long" else level - 4 * L
        pos["frac_open"] = 1.0
        pos["realized_usd"] = 0.0


def _manage_exit(pos: Dict[str, Any], bar: Dict[str, Any], cfg: NecklineConfig, atr_j: float):
    """第六轮出场模式管理。返回 (exit_price, exit_reason) 或 (None, None)。
    同bar顺序: 先用既有止损/TP判出场, 再用本bar极值更新跟踪线 (保守)。"""
    d, sl, tp, L, level = pos["direction"], pos["sl"], pos["tp"], pos["L"], pos["level"]
    if d == "long":
        if bar["low"] <= sl:
            reason = "TRAIL" if pos.get("trailed") else ("BE" if pos.get("be_moved") else "SL")
            return sl, reason
        if tp is not None and bar["high"] >= tp:
            return tp, "TP"
    else:
        if bar["high"] >= sl:
            reason = "TRAIL" if pos.get("trailed") else ("BE" if pos.get("be_moved") else "SL")
            return sl, reason
        if tp is not None and bar["low"] <= tp:
            return tp, "TP"

    # scaled: 半仓止盈 (出场未触后判)
    if cfg.exit_mode == "scaled" and pos.get("frac_open", 1.0) == 1.0:
        tp1 = pos["tp1"]
        hit1 = bar["high"] >= tp1 if d == "long" else bar["low"] <= tp1
        if hit1:
            gross1 = (tp1 - pos["entry"]) if d == "long" else (pos["entry"] - tp1)
            pos["realized_usd"] = 0.5 * pos["notional"] * gross1 / pos["entry"]
            pos["frac_open"] = 0.5
            pos["sl"] = pos["entry"]  # 剩余仓位保本
            pos["be_moved"] = True

    # 更新峰值与跟踪线 (下一bar生效)
    fav = bar["high"] if d == "long" else bar["low"]
    pos["peak"] = max(pos["peak"], fav) if d == "long" else min(pos["peak"], fav)
    new_sl = None
    if cfg.exit_mode == "chandelier":
        dist = cfg.chand_atr_mult * atr_j
        new_sl = pos["peak"] - dist if d == "long" else pos["peak"] + dist
    elif cfg.exit_mode == "trail_l":
        dist = cfg.sl_mult * L
        new_sl = pos["peak"] - dist if d == "long" else pos["peak"] + dist
    elif cfg.exit_mode == "stair":
        if d == "long":
            if not pos["lock2"] and pos["peak"] >= level + 4 * L:
                new_sl, pos["lock2"] = level + 2 * L, True
            elif not pos["lock1"] and pos["peak"] >= level + 2 * L:
                new_sl, pos["lock1"] = level + 1 * L, True
        else:
            if not pos["lock2"] and pos["peak"] <= level - 4 * L:
                new_sl, pos["lock2"] = level - 2 * L, True
            elif not pos["lock1"] and pos["peak"] <= level - 2 * L:
                new_sl, pos["lock1"] = level - 1 * L, True
    if new_sl is not None:
        if d == "long" and new_sl > pos["sl"]:
            pos["sl"] = new_sl
            pos["trailed"] = True
        elif d == "short" and new_sl < pos["sl"]:
            pos["sl"] = new_sl
            pos["trailed"] = True
    return None, None


def run_neckline_backtest(bars: List[Dict[str, Any]], cfg: NecklineConfig) -> Dict[str, Any]:
    signals = detect_overlap_signals(bars, cfg.ref_mode, cfg.ratio)
    n_bars = len(bars)

    # 变形 C: 最小 L 门槛 (相对信号bar收盘价)
    if cfg.min_l_pct > 0:
        signals = [s for s in signals
                   if s["L"] / bars[s["index"]]["close"] >= cfg.min_l_pct]

    # 变形 I: 放量形态 (第二根K线成交量 >= X * 前20根均量; 信号bar已收盘, 无前视)
    if cfg.vol_expansion > 0:
        kept = []
        for s in signals:
            idx = s["index"]
            if idx < 21:
                continue
            vols = [bars[k].get("volume", 0.0) for k in range(idx - 20, idx)]
            avg = sum(vols) / 20.0
            if avg > 0 and bars[idx].get("volume", 0.0) >= cfg.vol_expansion * avg:
                kept.append(s)
        signals = kept

    # 变形 J: 压缩前置 (两根K线总波幅 <= X * ATR14; ATR取到信号bar为止, 无前视)
    if cfg.squeeze_atr > 0:
        from backtest import _compute_atr
        atr = _compute_atr(bars, 14)
        kept = []
        for s in signals:
            idx = s["index"]
            pair_range = max(bars[idx - 1]["high"], bars[idx]["high"]) - \
                min(bars[idx - 1]["low"], bars[idx]["low"])
            if atr[idx] > 0 and pair_range <= cfg.squeeze_atr * atr[idx]:
                kept.append(s)
        signals = kept

    # 变形 D: F6式强趋势跳过 (在信号bar收盘时点判定, 无前视)
    if cfg.regime_skip_trend:
        from backtest import _compute_ema, _compute_adx
        ema200 = _compute_ema(bars, 200)
        adx = _compute_adx(bars, 14)
        kept = []
        for s in signals:
            idx = s["index"]
            close = bars[idx]["close"]
            ev = ema200[idx]
            dist = abs(close - ev) / ev if ev > 0 else 0
            if adx[idx] > 25 and dist > 0.02:
                continue  # 强趋势期跳过
            kept.append(s)
        signals = kept

    # 第四轮: 趋势过滤器 (方向门 / 强度门)
    if cfg.trend_filter:
        signals = _apply_trend_filter(bars, signals, cfg.trend_filter)

    trades: List[Dict[str, Any]] = []
    n_ambiguous = 0
    n_expired = 0
    n_skipped_in_position = 0
    n_dir_filtered = 0

    atr14 = None
    if cfg.exit_mode == "chandelier":
        from backtest import _compute_atr
        atr14 = _compute_atr(bars, 14)

    # 按 bar 推进的串行模拟
    # active 元素: {"sig": s, "phase": "wait"|"retest", "dir": str|None, "deadline": int}
    #   wait   窗口: sig.index+1 .. sig.index+expire_bars
    #   retest 窗口: 初次突破bar+1 .. 初次突破bar+expire_bars (回踩确认模式)
    sig_ptr = 0            # 尚未进入窗口的信号指针
    active: List[Dict[str, Any]] = []
    pending: Optional[tuple] = None   # close确认模式: (sig, direction), 下一根开盘入场
    pos: Optional[Dict[str, Any]] = None

    j = 1
    while j < n_bars:
        bar = bars[j]

        # 1) 新信号进入活跃窗口 (形态在 index 收盘确认, index+1 起可触发)
        while sig_ptr < len(signals) and signals[sig_ptr]["index"] + 1 <= j:
            s = signals[sig_ptr]
            if pos is not None:
                n_skipped_in_position += 1
            else:
                active.append({"sig": s, "phase": "wait", "dir": None,
                               "deadline": s["index"] + cfg.expire_bars})
            sig_ptr += 1

        # 2) 持仓管理
        if pos is not None and cfg.exit_mode:
            exit_price, exit_reason = _manage_exit(pos, bar, cfg, atr14[j] if atr14 else 0.0)
            if exit_price is None and cfg.max_hold_bars > 0 and \
                    j - pos["entry_idx"] >= cfg.max_hold_bars:
                exit_price, exit_reason = bar["close"], "TIME"
            if exit_price is not None:
                trades.append(_close_trade(pos, exit_price, exit_reason, bar, j, cfg))
                pos = None
                active = []
                pending = None
            j += 1
            continue
        if pos is not None:
            direction = pos["direction"]
            sl, tp = pos["sl"], pos["tp"]
            exit_price = None
            exit_reason = None
            if direction == "long":
                if bar["low"] <= sl:
                    exit_price, exit_reason = sl, ("BE" if pos.get("be_moved") else "SL")
                elif bar["high"] >= tp:
                    exit_price, exit_reason = tp, "TP"
            else:
                if bar["high"] >= sl:
                    exit_price, exit_reason = sl, ("BE" if pos.get("be_moved") else "SL")
                elif bar["low"] <= tp:
                    exit_price, exit_reason = tp, "TP"

            # 变形 E: 浮盈到 breakeven_at_l * L 时把SL推到入场价 (本bar先判出场, 后武装, 保守)
            if exit_price is None and cfg.breakeven_at_l > 0 and not pos.get("be_moved"):
                trig = (pos["level"] + cfg.breakeven_at_l * pos["L"]) if direction == "long" \
                    else (pos["level"] - cfg.breakeven_at_l * pos["L"])
                hit = bar["high"] >= trig if direction == "long" else bar["low"] <= trig
                if hit:
                    pos["sl"] = max(pos["sl"], pos["entry"]) if direction == "long" \
                        else min(pos["sl"], pos["entry"])
                    pos["be_moved"] = True
            if exit_price is None and cfg.max_hold_bars > 0 and \
                    j - pos["entry_idx"] >= cfg.max_hold_bars:
                exit_price, exit_reason = bar["close"], "TIME"

            if exit_price is not None:
                trades.append(_close_trade(pos, exit_price, exit_reason, bar, j, cfg))
                pos = None
                active = []  # 持仓期间的形态已全部忽略, 窗口从零开始
                pending = None
            j += 1
            continue

        # 2.5) close确认模式: 上一根收盘确认过, 本根开盘入场 (TP/SL 仍从颈线价起算)
        if pending is not None:
            s, direction = pending
            pending = None
            L = s["L"]
            level = s["overlap_hi"] if direction == "long" else s["overlap_lo"]
            if direction == "long":
                tp = level + cfg.tp_mult * L
                sl = level - cfg.sl_mult * L
            else:
                tp = level - cfg.tp_mult * L
                sl = level + cfg.sl_mult * L
            pos = {"signal_date": s["date"], "entry_date": bar["date"], "entry_idx": j,
                   "direction": direction, "entry": bar["open"], "level": level,
                   "L": L, "sl": sl, "tp": tp}
            _init_exit_fields(pos, cfg)
            active = []
            j += 1
            continue

        # 3) 空仓: 清掉过期形态 / 过期回踩窗口
        still = []
        for st in active:
            if j > st["deadline"]:
                n_expired += 1
            else:
                still.append(st)
        active = still

        # 4) 空仓: 找触发 (多个可触发时取最新形态)
        triggered = None
        to_remove = []
        for st in reversed(active):  # 最新优先
            s = st["sig"]
            hi, lo, L = s["overlap_hi"], s["overlap_lo"], s["L"]

            # --- 变形F close确认模式: 只认收盘价, 确认后下一根开盘入场 ---
            if cfg.entry_confirm == "close":
                if bar["close"] > hi:
                    if not s.get("allow_long", True):
                        n_dir_filtered += 1
                        to_remove.append(st)
                        continue
                    pending = (s, "long")
                    break
                if bar["close"] < lo:
                    if not s.get("allow_short", True):
                        n_dir_filtered += 1
                        to_remove.append(st)
                        continue
                    pending = (s, "short")
                    break
                continue

            # --- 变形H retest模式第二阶段: 初次突破后等回踩颈线 (限价单语义) ---
            if st["phase"] == "retest":
                lvl = hi if st["dir"] == "long" else lo
                if st["dir"] == "long":
                    if bar["low"] <= lvl:
                        entry = bar["open"] if bar["open"] < lvl else lvl  # gap更优价按开盘
                        triggered = (s, "long", entry, lvl)
                        break
                else:
                    if bar["high"] >= lvl:
                        entry = bar["open"] if bar["open"] > lvl else lvl
                        triggered = (s, "short", entry, lvl)
                        break
                continue

            # --- stop模式 / retest模式第一阶段: 盘中触价 (变形G: 含突破缓冲 buffer_l) ---
            hi_t = hi + cfg.buffer_l * L
            lo_t = lo - cfg.buffer_l * L
            o = bar["open"]
            gap_up = o > hi_t
            gap_dn = o < lo_t
            hit_up = bar["high"] >= hi_t
            hit_dn = bar["low"] <= lo_t
            if gap_up:
                direction, entry, level = "long", o, hi_t
            elif gap_dn:
                direction, entry, level = "short", o, lo_t
            elif hit_up and hit_dn:
                n_ambiguous += 1
                to_remove.append(st)
                continue
            elif hit_up:
                direction, entry, level = "long", hi_t, hi_t
            elif hit_dn:
                direction, entry, level = "short", lo_t, lo_t
            else:
                continue

            # 趋势方向门: 触发了被禁方向 → 信号作废
            if not s.get("allow_" + direction, True):
                n_dir_filtered += 1
                to_remove.append(st)
                continue

            if cfg.entry_confirm == "retest":
                # 初次突破不进场, 转入回踩等待 (窗口重置为突破bar+expire_bars)
                st["phase"] = "retest"
                st["dir"] = direction
                st["deadline"] = j + cfg.expire_bars
                continue

            triggered = (s, direction, entry, level)
            break

        for st in to_remove:
            if st in active:
                active.remove(st)

        if pending is not None:
            active = []
            j += 1
            continue

        if triggered is not None:
            s, direction, entry, level = triggered
            L = s["L"]
            if direction == "long":
                tp = level + cfg.tp_mult * L
                sl = level - cfg.sl_mult * L
            else:
                tp = level - cfg.tp_mult * L
                sl = level + cfg.sl_mult * L
            pos = {
                "signal_date": s["date"],
                "entry_date": bar["date"],
                "entry_idx": j,
                "direction": direction,
                "entry": entry,
                "level": level,
                "L": L,
                "sl": sl,
                "tp": tp,
            }
            _init_exit_fields(pos, cfg)
            active = []
        j += 1

    if pos is not None:
        trades.append(_close_trade(pos, bars[-1]["close"], "EOD", bars[-1], n_bars - 1, cfg))

    res = _summarize(trades, cfg, len(signals), n_ambiguous, n_expired, n_skipped_in_position)
    res["n_dir_filtered"] = n_dir_filtered
    return res


def _close_trade(pos, exit_price, exit_reason, bar, j, cfg: NecklineConfig):
    direction = pos["direction"]
    entry = pos["entry"]
    risk = cfg.sl_mult * pos["L"]  # R 记账单位 = 设计风险 1.5L
    if direction == "long":
        gross = exit_price - entry
    else:
        gross = entry - exit_price
    fee = (entry + exit_price) * cfg.fee_rate
    notional = pos.get("notional", cfg.notional_usd)
    frac = pos.get("frac_open", 1.0)
    # 每单金额记账: $notional 名义仓位的价格百分比盈亏 (与 signal_bot_race 同口径)
    # scaled模式: 已实现的半仓利润 realized_usd 加回
    pnl_usd = frac * (gross - fee) / entry * notional + pos.get("realized_usd", 0.0)
    net_r = (pnl_usd / notional) * entry / risk if notional > 0 else 0.0
    return {
        "pnl_usd": pnl_usd,
        "notional": round(notional, 0),
        "signal_date": pos["signal_date"],
        "entry_date": pos["entry_date"],
        "exit_date": bar["date"],
        "direction": direction,
        "entry": entry,
        "level": pos["level"],
        "L": pos["L"],
        "sl": pos["sl"],
        "tp": pos["tp"],
        "exit": exit_price,
        "exit_reason": exit_reason,
        "bars_held": j - pos["entry_idx"],
        "net_r": net_r,
        "win": net_r > 0,
    }


def _summarize(trades, cfg, n_signals, n_ambiguous, n_expired, n_skipped):
    n = len(trades)
    wins = sum(1 for t in trades if t["win"])
    total_r = sum(t["net_r"] for t in trades)
    total_usd = sum(t["pnl_usd"] for t in trades)
    equity = peak = max_dd = 0.0
    for t in trades:
        equity += t["net_r"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    eq_u = peak_u = max_dd_usd = 0.0
    for t in trades:
        eq_u += t["pnl_usd"]
        peak_u = max(peak_u, eq_u)
        max_dd_usd = max(max_dd_usd, peak_u - eq_u)
    lw = ll = cw = cl = 0
    for t in trades:
        if t["win"]:
            cw += 1; cl = 0; lw = max(lw, cw)
        else:
            cl += 1; cw = 0; ll = max(ll, cl)
    return {
        "variant": cfg.name,
        "ref_mode": cfg.ref_mode,
        "ratio": cfg.ratio,
        "n_signals": n_signals,
        "n_ambiguous": n_ambiguous,
        "n_expired": n_expired,
        "n_skipped_in_position": n_skipped,
        "n_trades": n,
        "n_wins": wins,
        "win_rate": round(wins / n, 4) if n else 0,
        "avg_r": round(total_r / n, 3) if n else 0,
        "total_r": round(total_r, 2),
        "max_drawdown_r": round(max_dd, 2),
        "total_usd": round(total_usd, 2),
        "avg_usd": round(total_usd / n, 2) if n else 0,
        "max_drawdown_usd": round(max_dd_usd, 2),
        "longest_winning_streak": lw,
        "longest_losing_streak": ll,
        "trades": trades,
    }


if __name__ == "__main__":
    # 自检: 合成数据 (与 backtest.py 同款生成器)
    import random
    random.seed(42)
    bars = []
    price = 60000.0
    for d in range(2000):
        drift = random.gauss(0, price * 0.005)
        if random.random() < 0.06:
            drift *= 4
        o = price
        c = max(1.0, price + drift)
        h = max(o, c) * (1 + abs(random.gauss(0, 0.003)))
        l = min(o, c) * (1 - abs(random.gauss(0, 0.003)))
        bars.append({"date": f"bar{d:04d}", "open": o, "high": h, "low": l, "close": c})
        price = c
    for m in REF_MODES:
        cfg = NecklineConfig(name=f"selftest_{m}", ref_mode=m, ratio=0.5)
        r = run_neckline_backtest(bars, cfg)
        print(f"{m:8s} signals={r['n_signals']:4d} trades={r['n_trades']:4d} "
              f"wr={r['win_rate']*100:5.1f}% totalR={r['total_r']:8.2f} maxDD={r['max_drawdown_r']:.2f}")
