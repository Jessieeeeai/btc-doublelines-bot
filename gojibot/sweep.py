#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
费率阈值三档扫描：A宽松 / B中性 / C严格。
规矩：阈值只在训练段（各指标覆盖段前半）校准；比较训练段与样本外表现，
选择的依据是训练段，样本外只做验证——防止我们自己过拟合。
    python3 sweep.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pandas as pd
from strategy import build_features, calibrate_thresholds
from backtest import run_backtest, Costs
from sizing import equity_curves, metrics, per_strategy_table
from run import load_real, CFG, OUT

CONFIGS = {
    "A_宽松": {"s01_fr_hi": 0.75, "s02_fr_ext_neg": 0.05, "s02_4h_neg": 0.10, "mirror_fr_hi": 0.90},
    "B_中性": {"s01_fr_hi": 0.85, "s02_fr_ext_neg": 0.03, "s02_4h_neg": 0.08, "mirror_fr_hi": 0.95},
    "C_严格": {"s01_fr_hi": 0.92, "s02_fr_ext_neg": 0.01, "s02_4h_neg": 0.05, "mirror_fr_hi": 0.98},
}


def seg_metrics(trades, label):
    if trades.empty:
        return {"seg": label, "trades": 0, "net%": 0, "wr%": 0, "pf": 0, "mdd%": 0}
    cv = equity_curves(trades)["risk_tiered"]
    m = metrics(trades, cv)
    return {"seg": label, "trades": m["trades"], "net%": m["total_return_pct"],
            "wr%": m["win_rate"], "pf": m["profit_factor"], "mdd%": m["max_drawdown_pct"]}


def main():
    df = load_real()
    feat = build_features(df)
    costs = Costs(CFG["costs"]["taker_fee_pct"], CFG["costs"]["slippage_pct"])
    split = feat.index[int(len(feat) * CFG["calibration"]["train_frac"])]

    rows, details = [], {}
    for name, pctl in CONFIGS.items():
        thr = calibrate_thresholds(feat, train_frac=CFG["calibration"]["train_frac"], pctl=pctl)
        tr = run_backtest(feat, thr, costs)
        tr_train = tr[tr["t_entry"] < split] if not tr.empty else tr
        tr_oos = tr[tr["t_entry"] >= split] if not tr.empty else tr
        rows.append({**seg_metrics(tr_train, "train"), "config": name})
        rows.append({**seg_metrics(tr_oos, "oos"), "config": name})
        details[name] = {
            "thresholds": {k: round(v, 7) if isinstance(v, float) else v for k, v in thr.items()},
            "per_strategy_full": per_strategy_table(tr).to_dict() if not tr.empty else {},
        }
        tr.to_csv(os.path.join(OUT, f"trades_sweep_{name}.csv"), index=False)
        print(f"[{name}] full={len(tr)} train={len(tr_train)} oos={len(tr_oos)}")

    tab = pd.DataFrame(rows)[["config", "seg", "trades", "net%", "wr%", "pf", "mdd%"]]
    print("\n== 三档对比（risk_tiered 仓位）==")
    print(tab.to_string(index=False))
    tab.to_csv(os.path.join(OUT, "sweep_summary.csv"), index=False)
    json.dump(details, open(os.path.join(OUT, "sweep_details.json"), "w"),
              ensure_ascii=False, indent=2, default=str)

    print("\n分策略明细见 results/sweep_details.json / trades_sweep_*.csv")


if __name__ == "__main__":
    main()
