# -*- coding: utf-8 -*-
"""
GojiBot 策略引擎：特征构建、阈值校准、S01/S02(4变体)/S03 信号、L01 止损、门控。
所有特征只用截至当前 bar 收盘的已完成数据，无前视。
"""
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd

KZ_HOURS = set(range(0, 3)) | set(range(7, 10)) | set(range(13, 16))  # UTC killzones
US_OPEN_HOURS = {13, 14, 15}  # UTC 13:00-15:30 近似


# ----------------------------------------------------------------------
# 特征
# ----------------------------------------------------------------------
def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """df: hourly UTC index, cols: open high low close volume taker_buy_base
    spot_close spot_volume spot_taker_buy_base funding oi [ob_bids ob_asks]"""
    out = df.copy()

    # CVD：优先使用外部预计算的 perp_delta/spot_delta（如 CoinGlass taker 买卖差），
    # 否则从K线 taker_buy_base 推导
    if "perp_delta" not in out.columns:
        out["perp_delta"] = 2 * out["taker_buy_base"] - out["volume"]
    if "spot_delta" not in out.columns:
        out["spot_delta"] = 2 * out["spot_taker_buy_base"] - out["spot_volume"]
    out["perp_cvd_24h"] = out["perp_delta"].rolling(24).sum()
    out["spot_cvd_24h"] = out["spot_delta"].rolling(24).sum()
    out["perp_cvd_slope"] = out["perp_delta"].rolling(6).sum()   # 6h 净流
    out["spot_cvd_slope"] = out["spot_delta"].rolling(6).sum()

    # funding（已 ffill 到小时）
    out["fr_min_24h"] = out["funding"].rolling(24).min()

    # OI
    out["oi_chg_24h"] = out["oi"].pct_change(24)

    # 订单簿失衡（可能缺失）
    if "ob_bids" in out.columns and out["ob_bids"].notna().any():
        tot = out["ob_bids"] + out["ob_asks"]
        out["ob_imb"] = (out["ob_bids"] - out["ob_asks"]) / tot.replace(0, np.nan)
    else:
        out["ob_imb"] = np.nan

    # 4H / 1D 结构（只用已完成的bar：shift 后再 reindex-ffill）
    h4 = out[["high", "low"]].resample("4h").agg({"high": "max", "low": "min"})
    d1 = out[["high", "low"]].resample("1D").agg({"high": "max", "low": "min"})
    # 最近3根已完成4H最高/最低（L01）
    out["h4_high3"] = h4["high"].shift(1).rolling(3).max().reindex(out.index, method="ffill")
    out["h4_low3"] = h4["low"].shift(1).rolling(3).min().reindex(out.index, method="ffill")
    # 最近5根已完成1D最高/最低（L01）
    out["d1_high5"] = d1["high"].shift(1).rolling(5).max().reindex(out.index, method="ffill")
    out["d1_low5"] = d1["low"].shift(1).rolling(5).min().reindex(out.index, method="ffill")
    # S01 阻力：最近20根已完成4H最高
    out["resistance"] = h4["high"].shift(1).rolling(20).max().reindex(out.index, method="ffill")
    # 最近一根已完成4H是否阴线
    h4c = out["close"].resample("4h").agg(["first", "last"])
    out["h4_bearish"] = (h4c["last"] < h4c["first"]).shift(1).reindex(out.index, method="ffill")

    # 90日高点回撤 / 48h回撤
    out["high_90d"] = out["high"].rolling(24 * 90, min_periods=24 * 30).max()
    out["dd_from_90d"] = 1 - out["close"] / out["high_90d"]
    rmax48 = out["high"].rolling(48).max()
    rmin48 = out["low"].rolling(48).min()
    out["dd_48h"] = (rmax48 - rmin48) / rmax48

    # S03：前5根1H（不含当前）
    out["prev5_max"] = out["high"].shift(1).rolling(5).max()
    out["prev5_min"] = out["low"].shift(1).rolling(5).min()
    out["prev5_range"] = (out["prev5_max"] - out["prev5_min"]) / out["close"]

    # 1H fallback 结构位（L01）
    out["h1_high6"] = out["high"].shift(1).rolling(6).max()
    out["h1_low6"] = out["low"].shift(1).rolling(6).min()

    hrs = out.index.hour
    out["in_kz"] = pd.Series(hrs, index=out.index).isin(KZ_HOURS)
    out["us_open"] = pd.Series(hrs, index=out.index).isin(US_OPEN_HOURS)

    out["atr24"] = (out["high"] - out["low"]).rolling(24).mean()
    return out


# ----------------------------------------------------------------------
# 阈值校准（在训练段上取分位数，替代文档的绝对值 —— 解决单位不明+过拟合问题）
# ----------------------------------------------------------------------
DOC_ABS = {  # 文档原始绝对阈值（8h费率，小数制：0.30% = 0.003）
    "s01_fr_hi": 0.003, "s02_fr_ext_neg": -0.003, "s02_4h_neg": -0.002,
    "mirror_fr_hi": 0.003,
}


def calibrate_thresholds(feat: pd.DataFrame, mode: str = "percentile",
                         train_frac: float = 0.5, pctl: dict = None) -> dict:
    """每个指标在【各自数据覆盖段】的前 train_frac 上取分位数，
    避免不同数据源覆盖窗口不一致导致训练段为空。"""
    def q(series, p):
        s = series.dropna()
        if not len(s):
            return np.nan
        s = s.iloc[: max(int(len(s) * train_frac), 10)]
        return float(s.quantile(p))

    P = {"s01_fr_hi": 0.90, "s02_fr_ext_neg": 0.03, "s02_4h_neg": 0.08,
         "mirror_fr_hi": 0.97, "s01_cvd": 0.15, "s01_cvd_usopen": 0.25}
    P.update(pctl or {})

    fr, cvd = feat["funding"], feat["perp_cvd_24h"]
    fr_train = fr.dropna()
    fr_train = fr_train.iloc[: max(int(len(fr_train) * train_frac), 10)]
    thr = {
        "s01_fr_hi": q(fr, P["s01_fr_hi"]),
        "s01_cvd_neg": q(cvd, P["s01_cvd"]),
        "s01_cvd_neg_usopen": q(cvd, P["s01_cvd_usopen"]),
        "s02_fr_ext_neg": q(fr, P["s02_fr_ext_neg"]),
        "s02_4h_neg": q(fr, P["s02_4h_neg"]),
        "mirror_fr_hi": q(fr, P["mirror_fr_hi"]),
        "fr_recovery_delta": max(1e-5, float(fr_train.std()) * 0.05) if len(fr_train) else 1e-5,
    }
    if mode == "doc_abs":
        thr.update(DOC_ABS)
    return thr


# ----------------------------------------------------------------------
# L01 止损（Andrew 二步法 + 5% 近端保护）
# ----------------------------------------------------------------------
MAX_STOP_DIST = 0.05


def l01_stop(row, direction: str, entry: float) -> Optional[float]:
    if direction == "SHORT":
        h4, d1, h1 = row["h4_high3"], row["d1_high5"], row["h1_high6"]
        if not np.isfinite(h4):
            return h1 * 1.002 if np.isfinite(h1) else None
        if h4 > entry * 1.002:
            if np.isfinite(d1) and d1 > h4 and (d1 / entry - 1) < MAX_STOP_DIST:
                return d1 * 1.003
            return h4 * 1.002
        return h4 * 1.002 if h4 > entry else entry * 1.008
    else:
        l4, d1, l1 = row["h4_low3"], row["d1_low5"], row["h1_low6"]
        if not np.isfinite(l4):
            return l1 * 0.998 if np.isfinite(l1) else None
        if l4 < entry * 0.998:
            if np.isfinite(d1) and d1 < l4 and (1 - d1 / entry) < MAX_STOP_DIST:
                return d1 * 0.997
            return l4 * 0.998
        return l4 * 0.998 if l4 < entry else entry * 0.992


# ----------------------------------------------------------------------
# 信号
# ----------------------------------------------------------------------
@dataclass
class Signal:
    time: pd.Timestamp
    strategy: str
    direction: str          # LONG / SHORT
    entry_ref: float        # 信号bar收盘价（实际入场=下一bar开盘）
    stop: float
    tp1: float
    tp2: float
    max_hold_h: int
    meta: dict = field(default_factory=dict)


def _r_targets(entry, stop, direction, r1=1.1, r2=2.0):
    r = abs(entry - stop)
    if direction == "SHORT":
        return entry - r1 * r, entry - r2 * r
    return entry + r1 * r, entry + r2 * r


def _ob_ok(v, want_neg: bool):
    """订单簿数据缺失时视为通过（条件降级），并在meta里标记。"""
    if not np.isfinite(v):
        return True
    return (v < 0) if want_neg else (v > 0)


def gen_signals_bar(row, thr: dict, enabled=None) -> list:
    """对单个已收盘bar产生候选信号（未经过门控）。"""
    sigs = []
    en = enabled or {"S01", "S02V1", "S02V2", "S02V3", "S02M", "S03"}
    px = row["close"]

    # ---- S01 反弹做空 ----
    if "S01" in en and np.isfinite(row["resistance"]):
        near = 0.02 if row["us_open"] else 0.015
        cvd_thr = thr["s01_cvd_neg_usopen"] if row["us_open"] else thr["s01_cvd_neg"]
        if (
            (row["resistance"] / px - 1) < near and px < row["resistance"] * 1.005
            and row["perp_cvd_24h"] < cvd_thr
            and row["spot_cvd_24h"] < 0
            and _ob_ok(row["ob_imb"], want_neg=True)
            and row["funding"] >= thr["s01_fr_hi"]
            and row["perp_cvd_slope"] < 0
            and (not np.isfinite(row["oi_chg_24h"]) or row["oi_chg_24h"] < 0.02)
        ):
            stop = l01_stop(row, "SHORT", px)
            if stop and stop > px:
                tp1, tp2 = _r_targets(px, stop, "SHORT")
                sigs.append(Signal(row.name, "S01", "SHORT", px, stop, tp1, tp2, 72))

    fr, frmin = row["funding"], row["fr_min_24h"]

    # ---- S02 V1 极端负费率直接做多 ----
    if "S02V1" in en and np.isfinite(fr):
        if (
            fr < thr["s02_fr_ext_neg"]
            and row["spot_cvd_slope"] > 0
            and 0 < row["perp_cvd_slope"] < row["spot_cvd_slope"]
            and _ob_ok(row["ob_imb"], want_neg=False)
            and row["dd_from_90d"] > 0.30
        ):
            stop = l01_stop(row, "LONG", px)
            if stop and stop < px:
                sigs.append(Signal(row.name, "S02V1", "LONG", px, stop,
                                   px * 1.045, px * 1.09, 48))

    # ---- S02 V2 费率恢复做多（Eve 3/5）----
    if "S02V2" in en and np.isfinite(frmin):
        recovering = (frmin < thr["s02_fr_ext_neg"]
                      and fr > frmin + thr["fr_recovery_delta"] and fr < 0.001)
        if recovering and row["dd_from_90d"] > 0.30:
            eve = sum([
                (fr - frmin) > 0.5 * (0 - frmin),
                row["perp_cvd_slope"] > 0,
                row["spot_cvd_slope"] > 0,
                row["oi_chg_24h"] > -0.005,
                np.isfinite(row["ob_imb"]) and row["ob_imb"] > 0,
            ])
            if eve >= 3:
                stop = l01_stop(row, "LONG", px)
                if stop and stop < px:
                    sigs.append(Signal(row.name, "S02V2", "LONG", px, stop,
                                       px * 1.045, px * 1.09, 48))

    # ---- S02 V3 4H费率恢复（固定-4%止损/+3%目标）----
    if "S02V3" in en and np.isfinite(frmin):
        if (frmin < thr["s02_4h_neg"] and row["dd_48h"] > 0.04
                and fr > frmin + thr["fr_recovery_delta"]):
            sigs.append(Signal(row.name, "S02V3", "LONG", px, px * 0.96,
                               px * 1.015, px * 1.03, 48))

    # ---- S02 Mirror 多头拥挤做空 ----
    if "S02M" in en and np.isfinite(fr) and fr >= thr["mirror_fr_hi"]:
        stop = l01_stop(row, "SHORT", px)
        if stop and stop > px:
            tp1, tp2 = _r_targets(px, stop, "SHORT")
            sigs.append(Signal(row.name, "S02M", "SHORT", px, stop, tp1, tp2, 48))

    # ---- S03 KZ假突破做空 ----
    if "S03" in en and row["in_kz"] and row["h4_bearish"] is True:
        if (np.isfinite(row["prev5_range"]) and row["prev5_range"] < 0.03
                and px > row["prev5_max"]):
            stop = row["high"] * 1.012
            tp1, tp2 = _r_targets(px, stop, "SHORT")
            sigs.append(Signal(row.name, "S03", "SHORT", px, stop, tp1, tp2, 48))

    return sigs


# ----------------------------------------------------------------------
# 门控（O层）
# ----------------------------------------------------------------------
PRIORITY = ["S01", "S03", "S02M", "S02V1", "S02V2", "S02V3"]


class Gate:
    """单品种：持仓互斥 + 止损后同方向冷却（1根1h bar≈文档45分钟）。"""

    def __init__(self, cooldown_bars: int = 1):
        self.cooldown_bars = cooldown_bars
        self.block_until = {"LONG": None, "SHORT": None}

    def on_stopout(self, direction, bar_time, bar_hours=1):
        self.block_until[direction] = bar_time + pd.Timedelta(hours=self.cooldown_bars * bar_hours)

    def filter(self, sigs, bar_time, has_open_position):
        if has_open_position or not sigs:
            return None
        ok = [s for s in sigs
              if not (self.block_until[s.direction] and bar_time < self.block_until[s.direction])]
        if not ok:
            return None
        ok.sort(key=lambda s: PRIORITY.index(s.strategy))
        return ok[0]
