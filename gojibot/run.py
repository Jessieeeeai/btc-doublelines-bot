#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主入口：
    python3 run.py                # 用 data/ 里的真实数据
    python3 run.py --synthetic    # 合成数据冒烟测试
流程：加载数据 → 特征 → 前半段校准阈值 → 全样本+样本外分别回测 → 报告
"""
import argparse
import json
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from strategy import build_features, calibrate_thresholds
from backtest import run_backtest, Costs
from sizing import equity_curves, metrics, per_strategy_table

CFG = json.load(open(os.path.join(HERE, "config.json")))
DATA = os.path.join(HERE, CFG.get("data_dir", "data"))
OUT = os.path.join(HERE, "results")
os.makedirs(OUT, exist_ok=True)


# ----------------------------------------------------------------------
def _jsonl(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return None
    rows = [json.loads(l) for l in open(p) if l.strip()]
    return pd.DataFrame(rows) if rows else None


def _ts_index(df, key_candidates=("time", "t", "time_ms", "createTime")):
    key = next((k for k in key_candidates if k in df.columns), None)
    t = pd.to_numeric(df[key], errors="coerce")
    unit = "ms" if t.dropna().iloc[0] > 1e12 else "s"
    df = df.assign(_t=pd.to_datetime(t, unit=unit, utc=True)).set_index("_t").sort_index()
    return df[~df.index.duplicated(keep="last")]


def _pick(df, *names):
    for n in names:
        if n in df.columns and df[n].notna().any():
            return pd.to_numeric(df[n], errors="coerce")
    return None


def _buysell(name):
    tk = _jsonl(name)
    if tk is None:
        return None, None
    tk = _ts_index(tk)
    buy = _pick(tk, "taker_buy_volume_usd", "buy_vol_usd", "taker_buy_volume", "buy_vol", "buyVolUsd")
    sell = _pick(tk, "taker_sell_volume_usd", "sell_vol_usd", "taker_sell_volume", "sell_vol", "sellVolUsd")
    if buy is None or sell is None:
        return None, None
    return pd.Series(buy.values, index=tk.index), pd.Series(sell.values, index=tk.index)


def _taker_delta(base, close):
    """CoinGlass taker → 小时级 delta/volume，1h 优先、4h 摊到每小时补历史。"""
    b1, s1 = _buysell(f"{base}.jsonl")
    b4, s4 = _buysell(f"{base}_4h.jsonl")
    parts_d, parts_v = [], []
    if b4 is not None:
        d4 = (b4 - s4).reindex(close.index, method="ffill", limit=3) / 4.0
        v4 = (b4 + s4).reindex(close.index, method="ffill", limit=3) / 4.0
        parts_d.append(d4); parts_v.append(v4)
    if b1 is not None:
        d1 = (b1 - s1).reindex(close.index)
        v1 = (b1 + s1).reindex(close.index)
        parts_d.append(d1); parts_v.append(v1)
    if not parts_d:
        return None, None
    delta = parts_d[0]
    vol = parts_v[0]
    for d, v in zip(parts_d[1:], parts_v[1:]):
        delta = d.combine_first(delta)
        vol = v.combine_first(vol)
    # 单位启发：量级大 → USD，除以价格转成币单位
    if vol.dropna().median() > 1e6:
        delta, vol = delta / close, vol / close
    return delta, vol


def _level_series(base, fields, index):
    """1h+4h 拼接的水平量（OI、订单簿），1h 优先。"""
    out = None
    for suffix in ("_4h", ""):
        df = _jsonl(f"{base}{suffix}.jsonl")
        if df is None:
            continue
        df = _ts_index(df)
        s = _pick(df, *fields)
        if s is None:
            continue
        s = pd.Series(s.values, index=df.index).reindex(index, method="ffill", limit=4)
        out = s if out is None else s.combine_first(out)
    return out


def load_real() -> pd.DataFrame:
    perp = _jsonl("perp_1h.jsonl")
    spot = _jsonl("spot_1h.jsonl")

    if perp is not None:
        perp = _ts_index(perp, ("open_time_ms",))
        df = perp[["open", "high", "low", "close", "volume"]].astype(float)
        df["taker_buy_base"] = pd.to_numeric(perp["taker_buy_base"], errors="coerce")
        print("perp klines: exchange source")
    else:
        cp = _jsonl("cg_price_perp.jsonl") or _jsonl("price_1h.jsonl")
        if cp is None:
            raise SystemExit("无任何价格K线 —— 请运行 fetch_price.py")
        cp = _ts_index(cp, ("time", "open_time_ms"))
        df = cp[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
        df["volume"] = np.nan
        df["taker_buy_base"] = np.nan
        print("perp klines: 现货价格代理（Coinbase/CG）——忽略基差")

    if spot is not None:
        spot = _ts_index(spot, ("open_time_ms",))
        df["spot_close"] = spot["close"].astype(float)
        df["spot_volume"] = spot["volume"].astype(float)
        df["spot_taker_buy_base"] = pd.to_numeric(spot["taker_buy_base"], errors="coerce")
    else:
        cs = _jsonl("cg_price_spot.jsonl")
        if cs is not None:
            cs = _ts_index(cs)
            df["spot_close"] = pd.to_numeric(cs["close"], errors="coerce").reindex(df.index, method="ffill")
        else:
            df["spot_close"] = df["close"]
        df["spot_volume"] = np.nan
        df["spot_taker_buy_base"] = np.nan

    # ---- CVD：优先K线taker，缺失则 CoinGlass taker 买卖差（1h+4h拼接）----
    if df["taker_buy_base"].isna().all():
        delta, vol = _taker_delta("cg_taker_perp", df["close"])
        if delta is None:
            raise SystemExit("永续taker数据缺失，无法构建CVD")
        df["perp_delta"] = delta
        if df["volume"].isna().all():
            df["volume"] = vol
        print(f"perp CVD: CoinGlass taker（覆盖 {delta.notna().mean()*100:.0f}% bars）")
    if df["spot_taker_buy_base"].isna().all():
        delta, vol = _taker_delta("cg_taker_spot", df["close"])
        if delta is not None:
            df["spot_delta"] = delta
            df["spot_volume"] = vol
            print(f"spot CVD: CoinGlass taker（覆盖 {delta.notna().mean()*100:.0f}% bars）")
        else:
            print("警告：现货CVD不可得，用永续CVD替代（现货条件退化）")
            df["spot_delta"] = df.get("perp_delta")

    # ---- funding：CoinGlass(Bybit) 优先，Binance Vision 补齐长历史 ----
    fr_all, srcs = None, []
    fv = _jsonl("funding_binance.jsonl")
    if fv is not None:
        fv = _ts_index(fv, ("time_ms",))
        fr_all = fv["funding_rate"].astype(float).reindex(df.index, method="ffill")
        srcs.append("binance_vision")
    fb = _jsonl("cg_funding.jsonl")
    if fb is not None:
        fb = _ts_index(fb)
        fr = _pick(fb, "close", "funding_rate", "fundingRate", "c", "value")
        if fr is not None:
            if fr.abs().median() > 1e-3:  # 百分数 → 小数
                fr = fr / 100.0
            fr = fr.reindex(df.index, method="ffill", limit=8)
            fr_all = fr.combine_first(fr_all) if fr_all is not None else fr
            srcs.append("coinglass_bybit(优先)")
    if fr_all is None:
        fp = _jsonl("funding_bybit_public.jsonl")
        if fp is None:
            raise SystemExit("没有任何资金费率数据")
        fp = _ts_index(fp, ("time_ms",))
        fr_all = fp["funding_rate"].astype(float).reindex(df.index, method="ffill")
        srcs.append("bybit_public")
    df["funding"] = fr_all
    print(f"funding source: {'+'.join(srcs)}  覆盖 {fr_all.notna().mean()*100:.0f}%  "
          f"range [{df['funding'].min():.5f}, {df['funding'].max():.5f}]")

    # ---- OI（1h+4h 拼接，Binance Vision 补历史）----
    s = _level_series("cg_oi", ("close", "open_interest_usd", "openInterest", "c", "value"), df.index)
    sv = _jsonl("cg_oi_binance.jsonl")
    if sv is not None:
        sv = _ts_index(sv)
        sv = pd.Series(sv["close"].astype(float).values, index=sv.index).reindex(df.index, method="ffill", limit=4)
        s = s.combine_first(sv) if s is not None else sv
    if s is not None:
        df["oi"] = s
        print(f"OI: 覆盖 {s.notna().mean()*100:.0f}% bars")
    else:
        print("警告：无OI数据，OI条件自动通过")
        df["oi"] = np.nan

    # ---- 订单簿（1h+4h 拼接）----
    bids = _level_series("cg_orderbook", ("bids_usd", "bids_amount", "bids_quantity"), df.index)
    asks = _level_series("cg_orderbook", ("asks_usd", "asks_amount", "asks_quantity"), df.index)
    if bids is not None and asks is not None:
        df["ob_bids"], df["ob_asks"] = bids, asks
        print(f"orderbook: 覆盖 {bids.notna().mean()*100:.0f}% bars")
    else:
        print("警告：无订单簿历史，ob_imb 条件降级为自动通过")

    return df.sort_index()


# ----------------------------------------------------------------------
def make_synthetic(days=730, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = days * 24
    t = pd.date_range("2024-07-01", periods=n, freq="1h", tz="UTC")
    # 价格：带趋势切换的几何随机游走
    regime = np.sign(np.sin(np.arange(n) / (24 * 45) * np.pi)) * 0.00008
    ret = rng.normal(regime, 0.006)
    close = 60000 * np.exp(np.cumsum(ret))
    spread = np.abs(rng.normal(0, 0.004, n))
    high = close * (1 + spread)
    low = close * (1 - spread)
    open_ = np.roll(close, 1) * (1 + rng.normal(0, 0.001, n))
    open_[0] = 60000
    vol = rng.gamma(3, 300, n)
    tbr = np.clip(0.5 + np.tanh(-np.gradient(close) / close * 50) * -0.2 + rng.normal(0, 0.08, n), 0.2, 0.8)
    funding_8h = np.clip(np.cumsum(rng.normal(0, 2e-5, n)) + regime * 2, -0.004, 0.004)
    oi = 1e10 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))

    df = pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "volume": vol, "taker_buy_base": vol * tbr,
        "spot_close": close * (1 + rng.normal(0, 0.0003, n)),
        "spot_volume": vol * 0.6,
        "spot_taker_buy_base": vol * 0.6 * np.clip(tbr + rng.normal(0, 0.05, n), 0.2, 0.8),
        "funding": funding_8h, "oi": oi,
    }, index=t)
    return df


# ----------------------------------------------------------------------
def report(tag, trades, out_dir):
    lines = [f"# GojiBot 回测报告 — {tag}\n"]
    if trades.empty:
        lines.append("无成交。\n")
    else:
        curves = equity_curves(trades)
        lines.append(f"- 交易笔数: {len(trades)}  时间: {trades['t_entry'].min()} → {trades['t_exit'].max()}\n")
        lines.append("## 仓位方案对比\n")
        lines.append("| 方案 | 总收益% | 最大回撤% | 胜率% | PF | Sharpe~ |")
        lines.append("|---|---|---|---|---|---|")
        for name, cv in curves.items():
            m = metrics(trades, cv)
            lines.append(f"| {name} | {m['total_return_pct']} | {m['max_drawdown_pct']} | "
                         f"{m['win_rate']} | {m['profit_factor']} | {m['sharpe_approx']} |")
        lines.append("\n## 分策略表现\n")
        lines.append(per_strategy_table(trades).to_markdown())
        lines.append("\n## 出场原因分布\n")
        lines.append(trades["exit_reason"].value_counts().to_markdown())
        trades.to_csv(os.path.join(out_dir, f"trades_{tag}.csv"), index=False)
    path = os.path.join(out_dir, f"report_{tag}.md")
    open(path, "w").write("\n".join(str(x) for x in lines))
    print(f"→ {path}")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--mode", default=CFG.get("threshold_mode", "percentile"),
                    choices=["percentile", "doc_abs"])
    args = ap.parse_args()

    df = make_synthetic() if args.synthetic else load_real()
    print(f"数据: {len(df)} bars  {df.index[0]} → {df.index[-1]}")

    feat = build_features(df)
    costs = Costs(CFG["costs"]["taker_fee_pct"], CFG["costs"]["slippage_pct"])

    # 每个指标在各自覆盖段的前半校准；样本外 = 全局时间后半
    split = feat.index[int(len(feat) * CFG["calibration"]["train_frac"])]
    thr = calibrate_thresholds(feat, mode=args.mode,
                               train_frac=CFG["calibration"]["train_frac"])
    print("阈值:", json.dumps({k: round(v, 6) for k, v in thr.items()}, ensure_ascii=False))
    json.dump(thr, open(os.path.join(OUT, "thresholds.json"), "w"), indent=2)

    tr_full = run_backtest(feat, thr, costs)
    tr_oos = tr_full[tr_full["t_entry"] >= split] if not tr_full.empty else tr_full
    print(f"全样本 {len(tr_full)} 笔 / 样本外 {len(tr_oos)} 笔")

    report("full", tr_full, OUT)
    report("oos", tr_oos, OUT)

    # 资金费率分布诊断（校准合理性检查）
    fr = feat["funding"].dropna()
    diag = {f"p{p}": round(float(fr.quantile(p / 100)), 6) for p in (1, 3, 5, 10, 50, 90, 95, 97, 99)}
    json.dump(diag, open(os.path.join(OUT, "funding_distribution.json"), "w"), indent=2)
    print("funding分位数:", diag)


if __name__ == "__main__":
    main()
