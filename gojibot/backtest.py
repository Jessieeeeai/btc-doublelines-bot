# -*- coding: utf-8 -*-
"""
回测执行器：逐bar撮合，含成本；TP1平半仓移保本；同bar双触发按止损优先（保守）。
"""
from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd

from strategy import Gate, gen_signals_bar


@dataclass
class Costs:
    taker_fee_pct: float = 0.05   # 单边 %
    slippage_pct: float = 0.02    # 单边 %

    @property
    def side(self):  # 单边总成本（小数）
        return (self.taker_fee_pct + self.slippage_pct) / 100.0


class Position:
    def __init__(self, sig, entry_px, entry_time):
        self.sig = sig
        self.entry = entry_px
        self.entry_time = entry_time
        self.stop = sig.stop
        self.tp1, self.tp2 = sig.tp1, sig.tp2
        self.half_closed = False
        self.legs = []  # (fraction, exit_px, reason)

    def _hit(self, level, bar, side_low):
        return bar["low"] <= level if side_low else bar["high"] >= level

    def step(self, bar, bar_time, costs: Costs):
        """返回 'closed' / None。同bar止损与TP同时可触时，止损优先。"""
        d = self.sig.direction
        stop_hit = self._hit(self.stop, bar, side_low=(d == "LONG"))
        tp1_hit = self._hit(self.tp1, bar, side_low=(d == "SHORT"))
        tp2_hit = self._hit(self.tp2, bar, side_low=(d == "SHORT"))

        if stop_hit:
            frac = 0.5 if self.half_closed else 1.0
            reason = "be_stop" if self.half_closed else "stop"
            self.legs.append((frac, self.stop, reason))
            return "closed"

        if not self.half_closed and tp1_hit:
            self.legs.append((0.5, self.tp1, "tp1"))
            self.half_closed = True
            self.stop = self.entry  # 移保本
            # TP1 与 TP2 同bar：保守只按TP1处理，TP2留给后续bar
            return None

        if self.half_closed and tp2_hit:
            self.legs.append((0.5, self.tp2, "tp2"))
            return "closed"

        # 超时
        held_h = (bar_time - self.entry_time).total_seconds() / 3600
        if held_h >= self.sig.max_hold_h:
            frac = 0.5 if self.half_closed else 1.0
            self.legs.append((frac, bar["close"], "time"))
            return "closed"
        return None

    def result(self, costs: Costs, exit_time):
        d = 1.0 if self.sig.direction == "LONG" else -1.0
        pnl = 0.0
        for frac, px, _ in self.legs:
            gross = d * (px / self.entry - 1)
            pnl += frac * (gross - 2 * costs.side)
        risk_pct = abs(self.entry - self.sig.stop) / self.entry
        return {
            "strategy": self.sig.strategy,
            "direction": self.sig.direction,
            "t_signal": self.sig.time,
            "t_entry": self.entry_time,
            "t_exit": exit_time,
            "entry": self.entry,
            "stop_init": self.sig.stop,
            "tp1": self.tp1, "tp2": self.tp2,
            "exit_reason": "+".join(r for _, _, r in self.legs),
            "pnl_pct": pnl * 100,
            "risk_pct": risk_pct * 100,
            "hold_h": (exit_time - self.entry_time).total_seconds() / 3600,
            "stopped_out": any(r == "stop" for _, _, r in self.legs),
        }


def run_backtest(feat: pd.DataFrame, thr: dict, costs: Costs,
                 enabled=None, start=None, end=None) -> pd.DataFrame:
    """feat: build_features 输出。信号在bar收盘生成，下一bar开盘入场。"""
    idx = feat.index
    lo = idx.searchsorted(pd.Timestamp(start)) if start else 0
    hi = idx.searchsorted(pd.Timestamp(end)) if end else len(idx)

    gate = Gate()
    pos: Optional[Position] = None
    pending = None  # 待下bar开盘入场的信号
    trades = []

    for i in range(lo, hi):
        bar = feat.iloc[i]
        t = idx[i]

        # 1) 开盘：处理待入场信号
        if pending is not None:
            e = bar["open"]
            d = pending.direction
            slip = 1 + costs.side if d == "LONG" else 1 - costs.side  # 成本在result里统一扣，入场价只按滑点方向修正
            entry_px = e
            # 跳空穿越止损/TP1的信号放弃
            bad = (d == "SHORT" and entry_px >= pending.stop) or \
                  (d == "LONG" and entry_px <= pending.stop) or \
                  (d == "SHORT" and entry_px <= pending.tp1) or \
                  (d == "LONG" and entry_px >= pending.tp1)
            if not bad:
                pos = Position(pending, entry_px, t)
            pending = None

        # 2) 持仓管理（入场bar本身也检查止损/TP）
        if pos is not None:
            status = pos.step(bar, t, costs)
            if status == "closed":
                rec = pos.result(costs, t)
                trades.append(rec)
                if rec["stopped_out"]:
                    gate.on_stopout(pos.sig.direction, t)
                pos = None

        # 3) 收盘：生成新信号（有持仓则跳过）
        if pos is None and pending is None:
            sigs = gen_signals_bar(bar, thr, enabled)
            chosen = gate.filter(sigs, t, has_open_position=False)
            if chosen is not None:
                pending = chosen

    # 收尾：未平仓头寸按最后收盘价平掉
    if pos is not None:
        last = feat.iloc[hi - 1]
        frac = 0.5 if pos.half_closed else 1.0
        pos.legs.append((frac, last["close"], "eod"))
        trades.append(pos.result(costs, idx[hi - 1]))

    return pd.DataFrame(trades)
