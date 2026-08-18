# -*- coding: utf-8 -*-
"""
仓位层：把逐笔交易（名义盈亏%）映射到账户净值曲线的多种方案。
"""
import numpy as np
import pandas as pd

STRAT_RISK_MULT = {  # 分级风险：依据样本可信度/尾部风险
    "S01": 1.0, "S03": 0.75, "S02M": 1.0,
    "S02V1": 0.75, "S02V2": 0.75, "S02V3": 0.5,
}
LEV_CAP = 5.0  # 名义/净值 上限


def equity_curves(trades: pd.DataFrame) -> dict:
    """返回 {scheme: DataFrame(t_exit, equity)}；trades 按 t_exit 排序。"""
    if trades.empty:
        return {}
    tr = trades.sort_values("t_exit").reset_index(drop=True)
    out = {}

    # 1) 文档口径：名义盈亏%直接累加（不复利）
    doc = 100 + tr["pnl_pct"].cumsum()
    out["doc_sum"] = pd.DataFrame({"t": tr["t_exit"], "equity": doc.values})

    # 2) 固定风险 1%/笔（复利）
    def fixed_risk(risk_target, mult_map=None):
        eq, curve = 100.0, []
        for _, r in tr.iterrows():
            m = (mult_map or {}).get(r["strategy"], 1.0)
            risk_frac = r["risk_pct"] / 100.0
            if risk_frac <= 0:
                curve.append(eq)
                continue
            lev = min((risk_target * m) / risk_frac, LEV_CAP)
            eq *= 1 + lev * r["pnl_pct"] / 100.0
            curve.append(eq)
        return pd.DataFrame({"t": tr["t_exit"], "equity": curve})

    out["risk_1pct"] = fixed_risk(0.01)
    out["risk_tiered"] = fixed_risk(0.01, STRAT_RISK_MULT)
    out["risk_0p5pct"] = fixed_risk(0.005)
    return out


def metrics(trades: pd.DataFrame, curve: pd.DataFrame) -> dict:
    if trades.empty:
        return {}
    eq = curve["equity"].values
    peak = np.maximum.accumulate(eq)
    mdd = float(((eq - peak) / peak).min()) * 100
    total = float(eq[-1] / 100 - 1) * 100
    days = max((trades["t_exit"].max() - trades["t_entry"].min()).days, 1)
    rets = pd.Series(eq).pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252 * len(rets) / max(days, 1))) if rets.std() > 0 else 0.0
    wins = trades[trades["pnl_pct"] > 0]
    losses = trades[trades["pnl_pct"] <= 0]
    pf = float(wins["pnl_pct"].sum() / abs(losses["pnl_pct"].sum())) if len(losses) and losses["pnl_pct"].sum() != 0 else float("inf")
    return {
        "trades": len(trades),
        "win_rate": round(100 * len(wins) / len(trades), 1),
        "total_return_pct": round(total, 2),
        "max_drawdown_pct": round(mdd, 2),
        "profit_factor": round(pf, 2),
        "sharpe_approx": round(sharpe, 2),
        "avg_win_pct": round(float(wins["pnl_pct"].mean()), 3) if len(wins) else 0,
        "avg_loss_pct": round(float(losses["pnl_pct"].mean()), 3) if len(losses) else 0,
        "avg_hold_h": round(float(trades["hold_h"].mean()), 1),
    }


def per_strategy_table(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    g = trades.groupby("strategy")
    tab = pd.DataFrame({
        "trades": g.size(),
        "win_rate%": (g.apply(lambda x: (x["pnl_pct"] > 0).mean() * 100)).round(1),
        "sum_pnl%": g["pnl_pct"].sum().round(2),
        "avg_pnl%": g["pnl_pct"].mean().round(3),
        "worst%": g["pnl_pct"].min().round(2),
        "best%": g["pnl_pct"].max().round(2),
        "avg_hold_h": g["hold_h"].mean().round(1),
    })
    return tab.sort_values("sum_pnl%", ascending=False)
